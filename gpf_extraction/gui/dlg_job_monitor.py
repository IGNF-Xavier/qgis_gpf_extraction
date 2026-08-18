#! python3  # noqa: E265

"""Suivi d'un job d'extraction (polling asynchrone + téléchargement du résultat).

Ce dialogue n'est **pas modal** : il ne bloque pas l'utilisation du reste
de QGIS pendant qu'un job tourne côté serveur (potentiellement plusieurs
minutes). Le job est par ailleurs mémorisé dans `core/job_registry.py`, ce
qui permet de le retrouver plus tard (statut, téléchargement) via
`gui/dlg_jobs.py`, y compris après fermeture et réouverture de QGIS.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import QCoreApplication, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from gpf_extraction.core.exceptions import ApiRequestError, JobFailedError
from gpf_extraction.core.extraction_api_client import ExtractionApiClient
from gpf_extraction.core.gpkg_merge import count_layers
from gpf_extraction.core.job_registry import JobRegistry
from gpf_extraction.core.models import JobStatus
from gpf_extraction.gui.job_result_loader import load_results
from gpf_extraction.toolbelt import PlgLogger

#: Garde une référence Python vivante sur chaque dialogue non-modal affiché,
#: pour ne pas dépendre de l'appelant (celui qui a créé le dialogue peut se
#: fermer avant que le suivi ne se termine). Nettoyé au fur et à mesure via
#: le signal `finished`.
_ACTIVE_MONITORS: list["JobMonitorDialog"] = []


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
        requested_tables: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Extraction en cours"))
        self.setMinimumWidth(420)
        # Non-modal : ne bloque pas le reste de QGIS pendant le suivi.
        self.setModal(False)

        self.log = PlgLogger().log
        self._client = client
        self._job = job
        self._output_dir = output_dir
        self._add_to_project = add_to_project
        self._project = project
        self._product_name = product_name
        self._requested_tables = requested_tables
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

        hint = QLabel(
            self.tr(
                "Cette fenêtre peut être fermée sans interrompre l'extraction : "
                "retrouvez-la plus tard via le menu « Jobs en cours »."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.rejected.connect(self._cancel_or_close)
        layout.addWidget(self.button_box)

        _ACTIVE_MONITORS.append(self)
        self.finished.connect(self._on_dialog_finished)

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, poll_interval_seconds) * 1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    def _on_dialog_finished(self, _result: int) -> None:
        if self in _ACTIVE_MONITORS:
            _ACTIVE_MONITORS.remove(self)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        try:
            self._job = self._client.get_job(self._job.job_id)
        except (ApiRequestError, ConnectionError) as exc:
            self._append_log(self.tr("Erreur lors de la vérification du statut : {}").format(exc))
            return

        self.lbl_status.setText(
            self.tr("Job {} : {}").format(self._job.job_id, self._job.status)
        )
        JobRegistry.update_job(self._job.job_id, last_known_status=self._job.status)
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
        dest_dir.mkdir(parents=True, exist_ok=True)

        self._append_log(self.tr("Téléchargement vers {}...").format(dest_dir))
        try:
            downloaded_paths = self._client.download_all_results(
                result.extract_data_href, dest_dir
            )
        except (ApiRequestError, ConnectionError) as exc:
            self._append_log(self.tr("Échec du téléchargement : {}").format(exc))
            self._finish_as_closable()
            return

        self._downloaded_path = str(dest_dir)
        JobRegistry.update_job(self._job.job_id, downloaded_path=self._downloaded_path)
        for downloaded_path in downloaded_paths:
            self._append_log(self.tr("Téléchargé : {}").format(downloaded_path))
        self._append_generation_report(downloaded_paths)

        if self._add_to_project:
            load_results(
                downloaded_paths,
                self._project,
                self._product_name,
                log=self._append_log,
                parent=self,
            )

        self.finished_ok.emit(self._downloaded_path)
        self._finish_as_closable()

    def _append_generation_report(self, downloaded_paths: list[Path]) -> None:
        """Journalise un petit rapport de génération : nombre de tables
        demandées à la soumission comparé au nombre de couches réellement
        livrées par le serveur, et échecs de téléchargement éventuels
        (fichiers individuels en échec, cf. `download_all_results`)."""
        data_paths = [p for p in downloaded_paths if p.suffix.lower() != ".json"]
        delivered = count_layers(data_paths)
        if self._requested_tables:
            self._append_log(
                self.tr("Rapport : {} table(s) demandée(s), {} couche(s) livrée(s).").format(
                    self._requested_tables, delivered
                )
            )
            if delivered != self._requested_tables:
                self._append_log(
                    self.tr(
                        "⚠ Écart entre le nombre de tables demandées et de couches livrées "
                        "— vérifiez la sélection et les journaux ci-dessus."
                    )
                )
        failures = getattr(self._client, "last_download_failures", None) or []
        if failures:
            self._append_log(
                self.tr("⚠ {} fichier(s) n'ont pas pu être téléchargés :").format(len(failures))
            )
            for failure in failures:
                self._append_log(f"  - {failure}")

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
            except (ApiRequestError, ConnectionError) as exc:
                self.log(
                    message=f"Erreur lors de l'annulation du job {self._job.job_id} : {exc}",
                    log_level=Qgis.MessageLevel.Warning,
                )
            JobRegistry.remove_job(self._job.job_id)
            self.reject()
        else:
            self.accept()
