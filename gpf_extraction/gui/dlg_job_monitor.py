#! python3  # noqa: E265

"""Suivi d'un job d'extraction (polling asynchrone + téléchargement du résultat)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from gpf_extraction.core.csw_client import CswClient
from gpf_extraction.core.exceptions import ApiRequestError, JobFailedError
from gpf_extraction.core.extraction_api_client import ExtractionApiClient
from gpf_extraction.core.models import JobStatus
from gpf_extraction.core.style_bundle import fetch_style_files, match_candidates_for_table
from gpf_extraction.gui.dlg_style_choice import StyleChoiceDialog
from gpf_extraction.toolbelt import PlgLogger


class JobMonitorDialog(QDialog):
    finished_ok = pyqtSignal(str)  # émis avec le chemin du fichier téléchargé

    def __init__(
        self,
        client: ExtractionApiClient,
        job: JobStatus,
        output_dir: Optional[str],
        add_to_project: bool,
        project: QgsProject,
        poll_interval_seconds: int = 15,
        product_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Extraction en cours"))
        self.setMinimumWidth(420)

        self.log = PlgLogger().log
        self._client = client
        self._job = job
        self._output_dir = output_dir
        self._add_to_project = add_to_project
        self._project = project
        self._product_name = product_name
        self._downloaded_path: Optional[str] = None

        layout = QVBoxLayout(self)

        self.lbl_status = QLabel(self.tr("Job {} : {}").format(job.job_id, job.status))
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # indéterminé : l'API ne fournit pas de %
        layout.addWidget(self.progress_bar)

        self.txt_logs = QPlainTextEdit(self)
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMinimumHeight(120)
        layout.addWidget(self.txt_logs)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.rejected.connect(self._cancel_or_close)
        layout.addWidget(self.button_box)

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, poll_interval_seconds) * 1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        try:
            self._job = self._client.get_job(self._job.job_id)
        except ApiRequestError as exc:
            self._append_log(self.tr("Erreur lors de la vérification du statut : {}").format(exc))
            return

        self.lbl_status.setText(
            self.tr("Job {} : {}").format(self._job.job_id, self._job.status)
        )
        if self._job.message:
            self._append_log(self._job.message)

        if self._job.is_successful:
            self._timer.stop()
            self._on_success()
        elif self._job.is_failed:
            self._timer.stop()
            self._on_failure()

    def _append_log(self, message: str) -> None:
        self.txt_logs.appendPlainText(message)

    # ------------------------------------------------------------------
    # Fin de job
    # ------------------------------------------------------------------
    def _on_success(self) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self._append_log(self.tr("Extraction terminée, récupération du résultat..."))

        try:
            result = self._client.get_job_results(self._job.job_id)
        except (ApiRequestError, JobFailedError) as exc:
            self._append_log(self.tr("Impossible de récupérer le résultat : {}").format(exc))
            self._finish_as_closable()
            return

        if result.logs:
            self._append_log(result.logs)

        if not result.extract_data_href:
            self._append_log(
                self.tr(
                    "Aucun fichier de résultat renvoyé par l'API (voir le résumé : {})"
                ).format(result.summary_href or "-")
            )
            self._finish_as_closable()
            return

        dest_dir = Path(self._output_dir) if self._output_dir else Path(tempfile.gettempdir())
        filename = Path(urlparse(result.extract_data_href).path).name or f"{self._job.job_id}.zip"
        dest_path = dest_dir / filename

        self._append_log(self.tr("Téléchargement vers {}...").format(dest_path))
        try:
            self._client.download_result(result.extract_data_href, dest_path)
        except ConnectionError as exc:
            self._append_log(self.tr("Échec du téléchargement : {}").format(exc))
            self._finish_as_closable()
            return

        self._downloaded_path = str(dest_path)
        self._append_log(self.tr("Téléchargement terminé : {}").format(dest_path))

        if self._add_to_project:
            self._add_result_to_project(dest_path)

        self.finished_ok.emit(self._downloaded_path)
        self._finish_as_closable()

    def _on_failure(self) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._append_log(
            self.tr("L'extraction a échoué (statut : {}).").format(self._job.status)
        )
        self._finish_as_closable()

    def _finish_as_closable(self) -> None:
        # Le bouton "Close" a le rôle RejectRole : il déclenche donc le
        # signal `rejected`, déjà branché sur `_cancel_or_close`, qui
        # accepte la boîte de dialogue puisque le timer est alors arrêté.
        self.button_box.clear()
        self.button_box.addButton(QDialogButtonBox.StandardButton.Close)

    # ------------------------------------------------------------------
    # Annulation
    # ------------------------------------------------------------------
    def _cancel_or_close(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            try:
                self._client.delete_job(self._job.job_id)
            except ApiRequestError as exc:
                self.log(
                    message=f"Erreur lors de l'annulation du job {self._job.job_id} : {exc}",
                    log_level=Qgis.MessageLevel.Warning,
                )
            self.reject()
        else:
            self.accept()

    # ------------------------------------------------------------------
    # Ajout au projet
    # ------------------------------------------------------------------
    def _add_result_to_project(self, path: Path) -> None:
        """Tente d'ajouter le fichier téléchargé au projet QGIS.

        Le format exact renvoyé par le service n'étant pas garanti (archive
        zip, GeoPackage, ...), cette méthode reste best-effort : en cas
        d'échec, le fichier reste disponible sur disque et l'utilisateur en
        est informé.
        """
        candidate_path = str(path)
        if path.suffix.lower() == ".zip":
            candidate_path = f"/vsizip/{path}"

        added_layers: list[QgsVectorLayer] = []

        layer = QgsVectorLayer(candidate_path, path.stem, "ogr")
        if layer.isValid():
            sub_layers = layer.dataProvider().subLayers() if layer.dataProvider() else []
            if len(sub_layers) > 1:
                for sub_layer_info in sub_layers:
                    # format "index!!::!!name!!::!!feature_count!!::!!geom_type"
                    name = sub_layer_info.split(QgsVectorLayer.sublayerSeparator())[1]
                    sub_uri = f"{candidate_path}|layername={name}"
                    sub_layer = QgsVectorLayer(sub_uri, name, "ogr")
                    if sub_layer.isValid():
                        self._project.addMapLayer(sub_layer)
                        added_layers.append(sub_layer)
            else:
                self._project.addMapLayer(layer)
                added_layers.append(layer)
            self._append_log(self.tr("Résultat ajouté au projet."))
        else:
            self._append_log(
                self.tr(
                    "Le résultat n'a pas pu être chargé automatiquement comme couche "
                    "vecteur. Fichier disponible ici : {}"
                ).format(path)
            )
            return

        self._apply_styles(added_layers)

    # ------------------------------------------------------------------
    # Styles (catalogue CSW)
    # ------------------------------------------------------------------
    def _apply_styles(self, layers: list[QgsVectorLayer]) -> None:
        """Cherche, télécharge et applique les styles (SLD) référencés par le
        catalogue de métadonnées pour le produit extrait, s'il y en a.

        Fonctionnalité entièrement best-effort : toute erreur (réseau,
        absence de fiche, absence de style...) est simplement journalisée,
        sans jamais interrompre le déroulement normal de l'extraction.
        """
        if not self._product_name or not layers:
            return

        try:
            csw_client = CswClient()
            record_id = csw_client.find_record_id(self._product_name)
            if not record_id:
                self._append_log(
                    self.tr(
                        "Aucune fiche de métadonnées trouvée pour « {} » : pas de style "
                        "appliqué automatiquement."
                    ).format(self._product_name)
                )
                return

            resources = csw_client.get_style_resources(record_id)
            if not resources:
                self._append_log(
                    self.tr("Aucun style référencé pour « {} ».").format(self._product_name)
                )
                return

            self._append_log(
                self.tr("Styles trouvés dans le catalogue, téléchargement...")
            )
            candidates = fetch_style_files(resources)
        except Exception as exc:  # noqa: BLE001 - fonctionnalité best-effort
            self.log(
                message=f"Recherche/téléchargement des styles CSW échoué : {exc}",
                log_level=Qgis.MessageLevel.Warning,
            )
            return

        if not candidates:
            self._append_log(self.tr("Aucun fichier de style exploitable n'a été trouvé."))
            return

        ambiguous: dict[str, list] = {}
        layers_by_name: dict[str, QgsVectorLayer] = {}
        for layer in layers:
            layers_by_name[layer.name()] = layer
            matches = match_candidates_for_table(candidates, layer.name())
            if len(matches) == 1:
                self._apply_sld(layer, matches[0].sld_path)
            elif len(matches) > 1:
                ambiguous[layer.name()] = matches

        if ambiguous:
            dlg = StyleChoiceDialog(ambiguous, parent=self)
            if dlg.exec():
                for layer_name, choice in dlg.get_choices().items():
                    if choice is not None:
                        self._apply_sld(layers_by_name[layer_name], choice.sld_path)

    def _apply_sld(self, layer: QgsVectorLayer, sld_path: Path) -> None:
        message, ok = layer.loadSldStyle(str(sld_path))
        if ok:
            layer.triggerRepaint()
            self._append_log(self.tr("Style « {} » appliqué à « {} ».").format(
                sld_path.name, layer.name()
            ))
        else:
            self._append_log(
                self.tr("Échec de l'application du style « {} » à « {} » : {}").format(
                    sld_path.name, layer.name(), message
                )
            )
