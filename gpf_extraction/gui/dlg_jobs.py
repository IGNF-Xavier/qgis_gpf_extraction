#! python3  # noqa: E265

"""Liste des jobs d'extraction suivis : en cours, prêts à télécharger, ou
déjà téléchargés — y compris ceux lancés lors d'une session QGIS
précédente (un job continue de tourner côté serveur indépendamment de
QGIS, cf. `core/job_registry.py`)."""

from __future__ import annotations

import os
from pathlib import Path

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from gpf_extraction.core.exceptions import ApiRequestError, JobFailedError
from gpf_extraction.core.extraction_api_client import ExtractionApiClient
from gpf_extraction.core.gpkg_merge import count_layers, remove_empty_layers
from gpf_extraction.core.job_registry import JobRegistry, TrackedJob
from gpf_extraction.gui.job_result_loader import load_results
from gpf_extraction.toolbelt import PlgLogger, PlgOptionsManager

_COLUMNS = ("Titre", "Commentaire", "Identifiant du job", "État", "Créé le")

_RUNNING_STATUSES = ("RUNNING", "ACCEPTED", "WAITING", "PROGRESS")
_FAILED_STATUSES = ("FAILED", "DISMISSED")


class JobsDialog(QDialog):
    def __init__(self, project: QgsProject = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Jobs d'extraction en cours"))
        self.setMinimumSize(760, 360)

        self.log = PlgLogger().log
        self.project = project or QgsProject.instance()
        self._client: ExtractionApiClient | None = None

        layout = QVBoxLayout(self)

        self.lbl_info = QLabel(
            self.tr(
                "Un job continue de tourner sur le serveur même si vous fermez QGIS : "
                "retrouvez-le ici pour suivre son statut ou récupérer son résultat."
            )
        )
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([self.tr(c) for c in _COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        # Par défaut, QTableWidget étire la dernière colonne pour occuper
        # tout l'espace restant et empêche son redimensionnement manuel :
        # désactivé pour que la colonne "Créé le" reste redimensionnable.
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table)

        buttons_layout = QHBoxLayout()
        self.btn_import_from_server = QPushButton(self.tr("Importer les jobs du serveur"))
        self.btn_import_from_server.setToolTip(
            self.tr(
                "Retrouve les jobs connus du serveur mais absents de ce suivi local "
                "(ex. lancés avant une mise à jour du plugin)."
            )
        )
        self.btn_import_from_server.clicked.connect(self._import_from_server)
        buttons_layout.addWidget(self.btn_import_from_server)

        self.btn_refresh = QPushButton(self.tr("Rafraîchir le statut"))
        self.btn_refresh.clicked.connect(self._refresh_selected)
        buttons_layout.addWidget(self.btn_refresh)

        self.btn_download = QPushButton(self.tr("Télécharger le résultat"))
        self.btn_download.clicked.connect(self._download_selected)
        buttons_layout.addWidget(self.btn_download)

        self.btn_open_folder = QPushButton(self.tr("Ouvrir le dossier"))
        self.btn_open_folder.clicked.connect(self._open_folder_selected)
        buttons_layout.addWidget(self.btn_open_folder)

        self.btn_forget = QPushButton(self.tr("Oublier"))
        self.btn_forget.clicked.connect(self._forget_selected)
        buttons_layout.addWidget(self.btn_forget)

        buttons_layout.addStretch(1)
        self.btn_close = QPushButton(self.tr("Fermer"))
        self.btn_close.clicked.connect(self.accept)
        buttons_layout.addWidget(self.btn_close)
        layout.addLayout(buttons_layout)

        self._reload_table()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Client API (créé à la demande, seulement si une session est active)
    # ------------------------------------------------------------------
    def _get_client(self) -> ExtractionApiClient | None:
        if self._client is not None:
            return self._client
        settings = PlgOptionsManager.get_plg_settings()
        if not settings.qgis_auth_id:
            QMessageBox.warning(
                self,
                self.tr("Non connecté"),
                self.tr("Connectez-vous à la Géoplateforme pour rafraîchir ou télécharger un job."),
            )
            return None
        self._client = ExtractionApiClient(authcfg=settings.qgis_auth_id, api_base=settings.api_base)
        return self._client

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    def _status_label(self, job: TrackedJob) -> str:
        if job.downloaded_path:
            return self.tr("Téléchargé → {}").format(job.downloaded_path)
        status = (job.last_known_status or "").upper()
        if status in _FAILED_STATUSES:
            return self.tr("Échoué ({})").format(job.last_known_status)
        if status == "SUCCESSFUL":
            return self.tr("Prêt à télécharger")
        if status in _RUNNING_STATUSES:
            return self.tr("En cours ({})").format(job.last_known_status)
        return self.tr("Statut inconnu (rafraîchir)")

    def _reload_table(self) -> None:
        jobs = JobRegistry.list_jobs()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = (
                job.process_title or job.product_name or "-",
                job.comment or "",
                job.job_id,
                self._status_label(job),
                job.created_iso,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(1000, job.job_id)  # Qt.UserRole, évite l'import de Qt ici
                self.table.setItem(row, col, item)
        self._update_buttons()

    def _selected_job(self) -> TrackedJob | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        job_id = selected[0].data(1000)
        return JobRegistry.get_job(job_id)

    def _update_buttons(self) -> None:
        job = self._selected_job()
        self.btn_refresh.setEnabled(job is not None and not job.downloaded_path)
        self.btn_download.setEnabled(
            job is not None
            and not job.downloaded_path
            and (job.last_known_status or "").upper() == "SUCCESSFUL"
        )
        self.btn_open_folder.setEnabled(job is not None and bool(job.downloaded_path))
        self.btn_forget.setEnabled(job is not None)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _import_from_server(self) -> None:
        """Récupère la liste des jobs connus du serveur et importe dans le
        suivi local ceux qui n'y sont pas déjà (ex. lancés avant une mise à
        jour du plugin, ou depuis une autre installation) : le job continue
        d'exister côté serveur indépendamment du suivi local."""
        client = self._get_client()
        if client is None:
            return
        try:
            server_jobs = client.list_jobs()
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.warning(
                self,
                self.tr("Erreur"),
                self.tr("Impossible de récupérer la liste des jobs :\n{}").format(exc),
            )
            return

        known_ids = {job.job_id for job in JobRegistry.list_jobs()}
        imported = 0
        process_titles: dict[str, str] = {}
        for server_job in server_jobs:
            if not server_job.job_id or server_job.job_id in known_ids:
                continue
            if server_job.process_id not in process_titles:
                try:
                    process_titles[server_job.process_id] = client.get_process(
                        server_job.process_id
                    ).title
                except (ApiRequestError, ConnectionError):
                    process_titles[server_job.process_id] = server_job.process_id
            JobRegistry.add_job(
                TrackedJob(
                    job_id=server_job.job_id,
                    process_id=server_job.process_id,
                    process_title=process_titles[server_job.process_id],
                    product_name=process_titles[server_job.process_id],
                    comment=self.tr("Importé depuis le serveur"),
                    last_known_status=server_job.status,
                )
            )
            imported += 1

        self._reload_table()
        QMessageBox.information(
            self,
            self.tr("Import terminé"),
            self.tr("{} job(s) importé(s) depuis le serveur.").format(imported)
            if imported
            else self.tr("Aucun job supplémentaire trouvé sur le serveur."),
        )

    def _refresh_selected(self) -> None:
        job = self._selected_job()
        client = self._get_client()
        if job is None or client is None:
            return
        try:
            status = client.get_job(job.job_id)
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.warning(
                self,
                self.tr("Erreur"),
                self.tr("Impossible de récupérer le statut du job :\n{}").format(exc),
            )
            return
        JobRegistry.update_job(job.job_id, last_known_status=status.status)
        self._reload_table()

    def _download_selected(self) -> None:
        job = self._selected_job()
        client = self._get_client()
        if job is None or client is None:
            return

        try:
            result = client.get_job_results(job.job_id)
        except (ApiRequestError, JobFailedError, ConnectionError) as exc:
            QMessageBox.warning(
                self,
                self.tr("Erreur"),
                self.tr("Impossible de récupérer le résultat du job :\n{}").format(exc),
            )
            return

        if not result.extract_data_href:
            QMessageBox.information(
                self,
                self.tr("Résultat indisponible"),
                self.tr("L'API n'a renvoyé aucun fichier de résultat pour ce job."),
            )
            return

        import tempfile

        dest_dir = Path(job.output_dir) if job.output_dir else Path(tempfile.gettempdir())
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            downloaded_paths = client.download_all_results(result.extract_data_href, dest_dir)
        except (ApiRequestError, ConnectionError) as exc:
            QMessageBox.critical(
                self,
                self.tr("Erreur"),
                self.tr("Échec du téléchargement :\n{}").format(exc),
            )
            return

        JobRegistry.update_job(job.job_id, downloaded_path=str(dest_dir))
        self._reload_table()

        data_paths = [p for p in downloaded_paths if p.suffix.lower() != ".json"]

        # Compté avant le nettoyage des couches vides : ce nombre reflète ce
        # que le serveur a réellement livré. Le nettoyage retire ensuite
        # volontairement des couches (celles sans aucune entité) ; ce n'est
        # pas un écart à signaler comme une anomalie.
        delivered = count_layers(data_paths)
        removed_layers = remove_empty_layers(data_paths)

        report_lines = []
        if job.requested_tables:
            report_lines.append(
                self.tr("{} table(s) demandée(s), {} couche(s) livrée(s) par le serveur.").format(
                    job.requested_tables, delivered
                )
            )
            if delivered != job.requested_tables:
                report_lines.append(
                    self.tr(
                        "⚠ Écart entre le nombre de tables demandées et de couches livrées."
                    )
                )
        if removed_layers:
            report_lines.append(
                self.tr("{} couche(s) vide(s) (0 entité) retirée(s) : {}").format(
                    len(removed_layers), ", ".join(sorted(removed_layers))
                )
            )
        failures = getattr(client, "last_download_failures", None) or []
        if failures:
            report_lines.append(
                self.tr("⚠ {} fichier(s) n'ont pas pu être téléchargés : {}").format(
                    len(failures), "; ".join(failures)
                )
            )
        report_text = ("\n\n" + "\n".join(report_lines)) if report_lines else ""
        if report_lines:
            # Journalisé en plus de la boîte de dialogue ci-dessous (message
            # transitoire, perdu si QGIS se ferme ou plante avant que
            # l'utilisateur ne l'ait lu) : reste consultable après coup dans
            # le panneau des messages QGIS.
            self.log(
                message="Rapport de génération ({}) :\n{}".format(
                    job.process_title or job.job_id, "\n".join(report_lines)
                ),
                log_level=Qgis.MessageLevel.Info,
            )

        file_list = "\n".join(p.name for p in downloaded_paths)
        reply = QMessageBox.question(
            self,
            self.tr("Téléchargement terminé"),
            self.tr(
                "Résultat téléchargé dans :\n{}\n\nFichier(s) :\n{}{}\n\n"
                "Ajouter les couches au projet actuel ?"
            ).format(dest_dir, file_list, report_text),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            load_results(
                downloaded_paths,
                self.project,
                job.product_name,
                log=lambda msg: self.log(message=msg, log_level=Qgis.MessageLevel.NoLevel),
                parent=self,
            )

    def _open_folder_selected(self) -> None:
        job = self._selected_job()
        if job is None or not job.downloaded_path:
            return
        # `downloaded_path` est le dossier contenant les fichiers téléchargés
        # (un job peut produire plusieurs fichiers, cf. core/atom_feed.py).
        if os.path.isdir(job.downloaded_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.downloaded_path))

    def _forget_selected(self) -> None:
        job = self._selected_job()
        if job is None:
            return

        status = (job.last_known_status or "").upper()
        if not job.downloaded_path and status in _RUNNING_STATUSES:
            reply = QMessageBox.question(
                self,
                self.tr("Oublier ce job"),
                self.tr(
                    "Ce job semble encore en cours côté serveur. L'oublier n'annule pas "
                    "l'extraction (elle continuera sur le serveur), mais vous ne pourrez "
                    "plus la retrouver depuis ce plugin. Continuer ?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        JobRegistry.remove_job(job.job_id)
        self._reload_table()
