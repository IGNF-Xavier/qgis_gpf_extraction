#! python3  # noqa: E265

"""
    Main plugin dialog: authentification, choix de l'emprise (BBox ou
    administrative), choix du produit (processus d'extraction) et de ses
    paramètres, puis lancement du job d'extraction.
"""

from __future__ import annotations

# standard
import os
from functools import partial

# PyQGIS
from qgis.core import Qgis, QgsProject, QgsRectangle
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# project
from gpf_extraction.__about__ import __plugin_name__, __uri_homepage__
from gpf_extraction.core.admin_boundary import AdminBoundaryClient
from gpf_extraction.core.constants import DEFAULT_WORKING_CRS
from gpf_extraction.core.exceptions import AdminBoundaryNotFoundError, ApiRequestError
from gpf_extraction.core.extraction_api_client import ExtractionApiClient
from gpf_extraction.core.job_registry import JobRegistry, TrackedJob
from gpf_extraction.core.stored_data import StoredDataClient
from gpf_extraction.gui.dlg_authentication import AuthenticationDialog
from gpf_extraction.gui.dlg_job_monitor import JobMonitorDialog
from gpf_extraction.gui.wdg_process_params import ProcessParamsWidget
from gpf_extraction.processing.rectangle_tool import RectangleDrawTool
from gpf_extraction.toolbelt import PlgLogger, PlgOptionsManager

# ############################################################################
# ########## Classes ###############
# ##################################

_BDTOPO_HINTS = ("bdtopo", "bd topo", "bd_topo")


class GpfExtractionDialog(QDialog):
    def __init__(
        self,
        project: QgsProject = None,
        iface: QgisInterface = None,
        locale: str = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(f"{__plugin_name__}")
        self.setWindowTitle(f"{__plugin_name__}")
        self.setMinimumSize(560, 640)

        self.iface = iface
        self.project = project
        self.locale = locale
        self.canvas = self.iface.mapCanvas() if self.iface else None

        self.log = PlgLogger().log
        self.plg_settings_mngr = PlgOptionsManager()

        self.client: ExtractionApiClient | None = None
        self.rectangle_tool = (
            RectangleDrawTool(self.project, self.canvas, DEFAULT_WORKING_CRS)
            if self.canvas
            else None
        )
        if self.rectangle_tool:
            self.rectangle_tool.signal.connect(self._on_rectangle_drawn)

        self._all_processes: list = []
        self.current_extent: QgsRectangle | None = None
        self.selected_process = None
        self.selected_process_details = None
        self.selected_stored_data = None

        self._admin_search_timer = QTimer(self)
        self._admin_search_timer.setSingleShot(True)
        self._admin_search_timer.setInterval(400)
        self._admin_search_timer.timeout.connect(self._search_admin)

        # Sans ça, le rectangle dessiné sur la carte (rubber band) reste
        # affiché après la fermeture du dialogue, et s'accumule à chaque
        # réouverture (constaté en conditions réelles).
        self.finished.connect(self._cleanup_map_tool)

        self._build_ui()
        self._refresh_auth_status()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)

        # Le contenu (emprise, produit, formulaire de paramètres dynamique,
        # sortie) est de hauteur variable selon le processus sélectionné
        # (ex. le sélecteur de tables peut afficher des dizaines de lignes) :
        # une zone défilante évite que ce contenu ne soit simplement coupé
        # (invisible tant que la fenêtre n'est pas agrandie manuellement).
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area, stretch=1)

        # -- Bandeau connexion -------------------------------------------------
        auth_layout = QHBoxLayout()
        self.lbl_auth_status = QLabel()
        auth_layout.addWidget(self.lbl_auth_status, stretch=1)
        self.btn_connect = QPushButton(self.tr("Se connecter..."))
        self.btn_connect.clicked.connect(self._open_auth)
        auth_layout.addWidget(self.btn_connect)
        self.btn_doc = QPushButton(self.tr("Documentation"))
        self.btn_doc.clicked.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )
        auth_layout.addWidget(self.btn_doc)
        layout.addLayout(auth_layout)

        # -- Emprise -------------------------------------------------------
        self.grp_extent = QGroupBox(self.tr("Emprise"))
        extent_layout = QVBoxLayout(self.grp_extent)
        self._extent_mode_group = QButtonGroup(self)
        self._extent_mode_group.setExclusive(True)

        bbox_layout = QHBoxLayout()
        self.chk_bbox = QCheckBox(self.tr("BBox dessinée sur la carte"))
        self.chk_bbox.setChecked(True)
        self._extent_mode_group.addButton(self.chk_bbox)
        bbox_layout.addWidget(self.chk_bbox)
        self.btn_draw_rectangle = QPushButton(self.tr("Dessiner l'emprise"))
        self.btn_draw_rectangle.clicked.connect(self._start_draw_rectangle)
        bbox_layout.addWidget(self.btn_draw_rectangle)
        extent_layout.addLayout(bbox_layout)

        self.chk_admin = QCheckBox(self.tr("Emprise administrative (commune, département, région)"))
        self._extent_mode_group.addButton(self.chk_admin)
        extent_layout.addWidget(self.chk_admin)

        self.txt_admin_search = QLineEdit()
        self.txt_admin_search.setPlaceholderText(
            self.tr("Rechercher une commune, un département, une région...")
        )
        self.txt_admin_search.setEnabled(False)
        self.txt_admin_search.textChanged.connect(
            lambda: self._admin_search_timer.start()
        )
        extent_layout.addWidget(self.txt_admin_search)

        self.list_admin_results = QListWidget()
        self.list_admin_results.setEnabled(False)
        self.list_admin_results.setMaximumHeight(90)
        self.list_admin_results.itemSelectionChanged.connect(self._on_admin_selected)
        extent_layout.addWidget(self.list_admin_results)

        self.lbl_extent_value = QLabel(self.tr("Aucune emprise choisie."))
        self.lbl_extent_value.setWordWrap(True)
        extent_layout.addWidget(self.lbl_extent_value)

        self.chk_bbox.toggled.connect(self._update_extent_mode)
        self.chk_admin.toggled.connect(self._update_extent_mode)

        layout.addWidget(self.grp_extent)

        # -- Produit ---------------------------------------------------------
        self.grp_process = QGroupBox(self.tr("Produit à extraire"))
        process_layout = QVBoxLayout(self.grp_process)

        self.txt_process_filter = QLineEdit()
        self.txt_process_filter.setPlaceholderText(self.tr("Filtrer (ex. BD TOPO)..."))
        self.txt_process_filter.textChanged.connect(self._filter_processes)
        process_layout.addWidget(self.txt_process_filter)

        self.list_processes = QListWidget()
        self.list_processes.setMaximumHeight(120)
        self.list_processes.itemSelectionChanged.connect(self._on_process_selected)
        process_layout.addWidget(self.list_processes)

        self.params_widget = ProcessParamsWidget()
        self.params_widget.changed.connect(self._validate)
        process_layout.addWidget(self.params_widget)

        self.lbl_params_status = QLabel()
        self.lbl_params_status.setWordWrap(True)
        self.lbl_params_status.setStyleSheet("color: #a33;")
        process_layout.addWidget(self.lbl_params_status)

        layout.addWidget(self.grp_process)

        # -- Sortie -----------------------------------------------------------
        self.grp_output = QGroupBox(self.tr("Résultat"))
        output_layout = QVBoxLayout(self.grp_output)

        self.chk_add_to_project = QCheckBox(self.tr("Ajouter le résultat au projet"))
        self.chk_add_to_project.setChecked(True)
        output_layout.addWidget(self.chk_add_to_project)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel(self.tr("Dossier de sortie :")))
        self.txt_output_folder = QLineEdit()
        self.txt_output_folder.setPlaceholderText(
            self.tr("Par défaut : dossier temporaire du système")
        )
        folder_layout.addWidget(self.txt_output_folder, stretch=1)
        self.btn_output_folder = QPushButton("...")
        self.btn_output_folder.setMaximumWidth(30)
        self.btn_output_folder.clicked.connect(self._select_output_folder)
        folder_layout.addWidget(self.btn_output_folder)
        output_layout.addLayout(folder_layout)

        comment_layout = QHBoxLayout()
        comment_layout.addWidget(QLabel(self.tr("Commentaire (optionnel) :")))
        self.txt_comment = QLineEdit()
        self.txt_comment.setPlaceholderText(
            self.tr("Pour retrouver ce job plus facilement dans « Jobs en cours »")
        )
        comment_layout.addWidget(self.txt_comment, stretch=1)
        output_layout.addLayout(comment_layout)


        layout.addWidget(self.grp_output)

        # -- Boutons -----------------------------------------------------------
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        # Hors de la zone défilante : toujours visible, sans avoir à faire
        # défiler jusqu'en bas.
        outer_layout.addWidget(self.button_box)

        self._set_content_enabled(False)

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------
    def _open_auth(self) -> None:
        dlg = AuthenticationDialog(self)
        if dlg.exec():
            self._refresh_auth_status()

    def _refresh_auth_status(self) -> None:
        settings = self.plg_settings_mngr.get_plg_settings()
        connected = bool(settings.qgis_auth_id)
        if connected:
            self.lbl_auth_status.setText(self.tr("Connecté à la Géoplateforme."))
            self.btn_connect.setText(self.tr("Changer de compte..."))
            self.client = ExtractionApiClient(
                authcfg=settings.qgis_auth_id, api_base=settings.api_base
            )
            self._load_processes()
        else:
            self.lbl_auth_status.setText(
                self.tr("Non connecté : connectez-vous pour lister les produits disponibles.")
            )
            self.btn_connect.setText(self.tr("Se connecter..."))
            self.client = None

        self._set_content_enabled(connected)
        self._validate()

        if not connected:
            self.txt_output_folder.setText("")
        elif not self.txt_output_folder.text():
            self.txt_output_folder.setText(settings.last_output_dir or "")

    def _set_content_enabled(self, enabled: bool) -> None:
        self.grp_extent.setEnabled(enabled)
        self.grp_process.setEnabled(enabled)
        self.grp_output.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Emprise : BBox
    # ------------------------------------------------------------------
    def _update_extent_mode(self) -> None:
        bbox_mode = self.chk_bbox.isChecked()
        self.btn_draw_rectangle.setEnabled(bbox_mode)
        self.txt_admin_search.setEnabled(not bbox_mode)
        self.list_admin_results.setEnabled(not bbox_mode)

    def _start_draw_rectangle(self) -> None:
        if not self.rectangle_tool:
            return
        self.showMinimized()
        self.iface.mainWindow().activateWindow()
        self.canvas.setMapTool(self.rectangle_tool)

    def _on_rectangle_drawn(self) -> None:
        self.showNormal()
        self.activateWindow()
        # Sans ça, l'outil de dessin reste l'outil actif du canevas
        # indéfiniment : tout clic ultérieur sur la carte (y compris après
        # la fermeture du dialogue) redéclenche un dessin de rectangle au
        # lieu du comportement normal de QGIS (constaté en conditions
        # réelles : le curseur restait "bloqué" en mode dessin d'emprise).
        if self.canvas and self.canvas.mapTool() is self.rectangle_tool:
            self.canvas.unsetMapTool(self.rectangle_tool)
        self.current_extent = self.rectangle_tool.new_extent
        self._update_extent_label()
        self._validate()

    def _update_extent_label(self) -> None:
        if not self.current_extent:
            self.lbl_extent_value.setText(self.tr("Aucune emprise choisie."))
            return
        rect = self.current_extent
        self.lbl_extent_value.setText(
            self.tr("Emprise ({crs}) : {xmin:.4f}, {ymin:.4f} → {xmax:.4f}, {ymax:.4f}").format(
                crs=DEFAULT_WORKING_CRS,
                xmin=rect.xMinimum(),
                ymin=rect.yMinimum(),
                xmax=rect.xMaximum(),
                ymax=rect.yMaximum(),
            )
        )
        self.params_widget.set_extent(self.current_extent, DEFAULT_WORKING_CRS)

    # ------------------------------------------------------------------
    # Emprise : administrative
    # ------------------------------------------------------------------
    def _search_admin(self) -> None:
        text = self.txt_admin_search.text().strip()
        self.list_admin_results.clear()
        if len(text) < 2:
            return
        try:
            results = AdminBoundaryClient().search(text)
        except AdminBoundaryNotFoundError:
            item = QListWidgetItem(self.tr("Aucun résultat."))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_admin_results.addItem(item)
            return
        except ConnectionError as exc:
            self.log(
                message=f"Erreur lors de la recherche administrative : {exc}",
                log_level=Qgis.MessageLevel.Warning,
            )
            return

        for result in results:
            item = QListWidgetItem(result.label)
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.list_admin_results.addItem(item)

    def _on_admin_selected(self) -> None:
        items = self.list_admin_results.selectedItems()
        if not items:
            return
        result = items[0].data(Qt.ItemDataRole.UserRole)
        if result is None:
            return
        self.current_extent = result.geometry.boundingBox()
        self._update_extent_label()
        self._validate()

    # ------------------------------------------------------------------
    # Produits (processus)
    # ------------------------------------------------------------------
    def _load_processes(self) -> None:
        if not self.client:
            return
        try:
            self._all_processes = self.client.list_processes(page=1, limit=200)
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.critical(
                self,
                self.tr("Erreur"),
                self.tr("Impossible de récupérer la liste des produits disponibles :\n{}").format(
                    exc
                ),
            )
            self._all_processes = []

        def sort_key(process):
            title_lower = (process.title or process.id).lower()
            is_bdtopo = any(hint in title_lower for hint in _BDTOPO_HINTS)
            return (0 if is_bdtopo else 1, title_lower)

        self._all_processes.sort(key=sort_key)
        self._populate_process_list(self._all_processes)

    def _populate_process_list(self, processes) -> None:
        self.list_processes.clear()
        for process in processes:
            item = QListWidgetItem(process.title or process.id)
            item.setData(Qt.ItemDataRole.UserRole, process)
            item.setToolTip(process.description)
            self.list_processes.addItem(item)

    def _filter_processes(self, text: str) -> None:
        text = text.strip().lower()
        if not text:
            self._populate_process_list(self._all_processes)
            return
        filtered = [
            p
            for p in self._all_processes
            if text in (p.title or "").lower()
            or text in p.id.lower()
            or text in (p.description or "").lower()
        ]
        self._populate_process_list(filtered)

    def _on_process_selected(self) -> None:
        items = self.list_processes.selectedItems()
        if not items or not self.client:
            self.selected_process = None
            self.selected_process_details = None
            self.selected_stored_data = None
            self.params_widget.set_process(None)
            self._validate()
            return

        process = items[0].data(Qt.ItemDataRole.UserRole)
        self.selected_process = process
        try:
            self.selected_process_details = self.client.get_process(process.id)
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.warning(
                self,
                self.tr("Avertissement"),
                self.tr(
                    "Impossible de récupérer le détail du produit « {} » : {}\n"
                    "Le formulaire de paramètres restera vide (utilisez l'édition avancée)."
                ).format(process.title, exc),
            )
            self.selected_process_details = None

        self.params_widget.set_process(self.selected_process_details)
        if self.current_extent:
            self.params_widget.set_extent(self.current_extent, DEFAULT_WORKING_CRS)

        described_by_url = (
            self.selected_process_details.described_by_url
            if self.selected_process_details
            else None
        )
        self.selected_stored_data = None
        if described_by_url:
            try:
                self.selected_stored_data = StoredDataClient(authcfg=self.client.authcfg).get(
                    described_by_url
                )
                self.params_widget.set_stored_data(self.selected_stored_data)
            except (ApiRequestError, ConnectionError) as exc:
                self.log(
                    message=f"Impossible de récupérer la description de la donnée "
                    f"stockée ({described_by_url}) : {exc}",
                    log_level=Qgis.MessageLevel.Warning,
                )
                self.params_widget.set_stored_data(None)
        else:
            self.params_widget.set_stored_data(None)

        self._validate()

    # ------------------------------------------------------------------
    # Nettoyage
    # ------------------------------------------------------------------
    def _cleanup_map_tool(self, _result: int = None) -> None:
        if not self.rectangle_tool:
            return
        if self.canvas and self.canvas.mapTool() is self.rectangle_tool:
            self.canvas.unsetMapTool(self.rectangle_tool)
        self.rectangle_tool.clear()

    # ------------------------------------------------------------------
    # Sortie
    # ------------------------------------------------------------------
    def _select_output_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("Choisir un dossier de sortie"), self.txt_output_folder.text()
        )
        if directory:
            self.txt_output_folder.setText(directory)

    # ------------------------------------------------------------------
    # Validation / soumission
    # ------------------------------------------------------------------
    def _validate(self) -> None:
        ok = bool(self.client) and self.current_extent is not None and self.selected_process is not None

        params_message = ""
        if ok:
            params_ready, params_message = self.params_widget.is_ready()
            ok = ok and params_ready
        self.lbl_params_status.setText(params_message)

        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _on_accept(self) -> None:
        try:
            body = self.params_widget.get_body()
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Paramètres invalides"), str(exc))
            return

        output_dir = self.txt_output_folder.text().strip() or None
        if output_dir:
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    self.tr("Erreur"),
                    self.tr("Impossible d'utiliser le dossier de sortie :\n{}").format(exc),
                )
                return

        try:
            job = self.client.execute(self.selected_process.id, body)
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.critical(
                self,
                self.tr("Erreur"),
                self.tr("Le lancement de l'extraction a échoué :\n{}").format(exc),
            )
            return

        settings = self.plg_settings_mngr.get_plg_settings()
        settings.last_output_dir = output_dir or ""
        self.plg_settings_mngr.save_from_object(settings)

        product_name = (
            self.selected_stored_data.name
            if self.selected_stored_data
            else (self.selected_process.title if self.selected_process else "")
        )

        # Nombre de tables sélectionnées dans le formulaire, pour le rapport
        # de génération affiché après téléchargement (comparaison avec le
        # nombre de couches réellement livrées par le serveur). N'a de sens
        # que pour les processus exposant le sélecteur de tables (`relations`).
        relations_value = body.get("inputs", {}).get("relations")
        requested_tables = len(relations_value) if isinstance(relations_value, dict) else 0

        JobRegistry.add_job(
            TrackedJob(
                job_id=job.job_id,
                process_id=self.selected_process.id,
                process_title=self.selected_process.title,
                product_name=product_name,
                output_dir=output_dir or "",
                comment=self.txt_comment.text().strip(),
                requested_tables=requested_tables,
                last_known_status=job.status,
            )
        )

        # Non-bloquant : le suivi continue en arrière-plan (fenêtre indépendante,
        # cf. dlg_job_monitor.py), le job restant par ailleurs retrouvable via
        # le menu « Jobs en cours » même si cette fenêtre-ci ou QGIS ferment.
        monitor = JobMonitorDialog(
            client=self.client,
            job=job,
            output_dir=output_dir,
            add_to_project=self.chk_add_to_project.isChecked(),
            project=self.project,
            poll_interval_seconds=settings.status_check_sleep,
            product_name=product_name,
            requested_tables=requested_tables,
            parent=self.iface.mainWindow() if self.iface else None,
        )
        monitor.show()
        self.accept()
