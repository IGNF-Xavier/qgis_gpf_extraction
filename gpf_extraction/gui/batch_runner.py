#! python3  # noqa: E265

"""Lancement successif des lots d'une extraction découpée (voir `core/job_batch.py`).

Le service n'accepte qu'un job à la fois (HTTP 429) : le lot suivant part quand le précédent est
terminé — ou en échec — depuis le suivi du job (`gui/dlg_job_monitor.py`). Les lots restants sont
conservés dans les réglages QGIS : si QGIS est fermé entre deux lots, la fenêtre « Jobs en cours »
propose de les reprendre.
"""

from __future__ import annotations

import os
import tempfile
from functools import partial

from qgis.core import Qgis
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QMessageBox

from gpf_extraction.core.exceptions import ApiRequestError
from gpf_extraction.core.job_batch import BatchQueue
from gpf_extraction.core.job_registry import JobRegistry, TrackedJob
from gpf_extraction.toolbelt import PlgLogger

#: Délai avant de réessayer quand le service répond « un job est déjà en cours » (HTTP 429).
RETRY_DELAY_MS = 15_000

#: Garde une référence sur les minuteurs de nouvelle tentative en attente.
_RETRY_TIMERS: list[QTimer] = []


def batch_output_dir(options: dict, index: int) -> str:
    """Dossier de sortie du lot `index` (1, 2, …) : un sous-dossier par lot, pour que les fichiers
    du serveur (même nom pour chaque job) ne s'écrasent pas."""
    base = options.get("output_dir") or os.path.join(tempfile.gettempdir(), "gpf_extraction_lots")
    return os.path.join(base, f"lot{index}")


def batch_gpkg_name(options: dict, index: int) -> str:
    base = options.get("gpkg_name") or ""
    return f"{base}_lot{index}" if base else ""


def launch_next_batch(client, project, parent=None) -> bool:
    """Lance le lot suivant. Renvoie vrai s'il a démarré, ou si un nouvel essai est programmé."""
    from gpf_extraction.gui.dlg_job_monitor import JobMonitorDialog  # import tardif : évite une dépendance circulaire

    state = BatchQueue.load()
    if not state:
        return False
    options = state["options"]
    total = state["total"]
    index = total - len(state["bodies"]) + 1
    body = state["bodies"][0]
    log = PlgLogger().log
    try:
        job = client.execute(state["process_id"], body)
    except ApiRequestError as exc:
        if exc.status_code == 429:
            log(message=f"Lot {index}/{total} : un job est déjà en cours, nouvelle tentative dans 15 s")
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(partial(_retry, timer, client, project, parent))
            _RETRY_TIMERS.append(timer)
            timer.start(RETRY_DELAY_MS)
            return True
        BatchQueue.clear()
        QMessageBox.warning(
            parent,
            "Extraction découpée",
            f"Le lot {index}/{total} a été refusé par le service (HTTP {exc.status_code}). "
            f"Les {len(state['bodies'])} lot(s) restant(s) sont abandonnés.",
        )
        return False
    except ConnectionError as exc:
        # Conserve la file : « Jobs en cours » permettra de reprendre une fois la connexion rétablie.
        log(message=f"Lot {index}/{total} : connexion impossible ({exc})", log_level=Qgis.MessageLevel.Warning)
        return False

    state["bodies"].pop(0)
    if state["bodies"]:
        BatchQueue.save(state)
    else:
        BatchQueue.clear()

    relations = body.get("inputs", {}).get("relations", {})
    output_dir = batch_output_dir(options, index)
    gpkg_name = batch_gpkg_name(options, index)
    product = f"{options.get('product_name', '')} (lot {index}/{total})".strip()
    JobRegistry.add_job(
        TrackedJob(
            job_id=job.job_id,
            process_id=state["process_id"],
            process_title=state.get("title", ""),
            product_name=product,
            output_dir=output_dir,
            comment=options.get("comment", ""),
            requested_tables=len(relations) if isinstance(relations, dict) else 0,
            gpkg_name=gpkg_name,
            clip_to_extent=options.get("clip_to_extent", False),
            extent_wkt=options.get("extent_wkt", ""),
            extent_crs=options.get("extent_crs", ""),
            last_known_status=job.status,
        )
    )
    monitor = JobMonitorDialog(
        client=client,
        job=job,
        output_dir=output_dir,
        add_to_project=options.get("add_to_project", True),
        project=project,
        poll_interval_seconds=options.get("poll_interval", 15),
        product_name=product,
        requested_tables=len(relations) if isinstance(relations, dict) else 0,
        gpkg_name=gpkg_name,
        clip_to_extent=options.get("clip_to_extent", False),
        extent_wkt=options.get("extent_wkt", ""),
        extent_crs=options.get("extent_crs", ""),
        parent=parent,
    )
    monitor.show()
    return True


def _retry(timer: QTimer, client, project, parent) -> None:
    if timer in _RETRY_TIMERS:
        _RETRY_TIMERS.remove(timer)
    launch_next_batch(client, project, parent)
