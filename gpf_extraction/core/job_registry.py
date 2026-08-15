"""Suivi persistant des jobs d'extraction.

Un job d'extraction tourne côté serveur, indépendamment de QGIS : fermer
QGIS (ou le dialogue de suivi) n'annule rien côté Géoplateforme. Ce module
mémorise les jobs lancés (dans `QgsSettings`, donc entre deux sessions
QGIS) pour pouvoir les retrouver plus tard — savoir s'ils sont encore en
cours, prêts à télécharger, ou déjà téléchargés — via `gui/dlg_jobs.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from qgis.core import QgsSettings

from .constants import PLUGIN_NAMESPACE

SETTINGS_KEY_TRACKED_JOBS = f"{PLUGIN_NAMESPACE}/tracked_jobs"


@dataclass
class TrackedJob:
    job_id: str
    process_id: str = ""
    process_title: str = ""
    product_name: str = ""
    output_dir: str = ""
    comment: str = ""
    created_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    #: Dernier statut serveur connu (ex. "RUNNING", "SUCCESSFUL", "FAILED"),
    #: mis à jour à chaque rafraîchissement manuel depuis `dlg_jobs.py`.
    last_known_status: str = ""
    #: Renseigné une fois le résultat effectivement téléchargé.
    downloaded_path: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedJob":
        known_fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known_fields})


class JobRegistry:
    """Façade statique autour de `QgsSettings` pour la liste des jobs suivis."""

    @staticmethod
    def list_jobs() -> list[TrackedJob]:
        raw = QgsSettings().value(SETTINGS_KEY_TRACKED_JOBS, "")
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(items, list):
            return []
        return [TrackedJob.from_dict(item) for item in items if isinstance(item, dict)]

    @staticmethod
    def _save(jobs: list[TrackedJob]) -> None:
        QgsSettings().setValue(
            SETTINGS_KEY_TRACKED_JOBS,
            json.dumps([job.to_dict() for job in jobs], ensure_ascii=False),
        )

    @classmethod
    def add_job(cls, job: TrackedJob) -> None:
        jobs = [j for j in cls.list_jobs() if j.job_id != job.job_id]
        jobs.append(job)
        cls._save(jobs)

    @classmethod
    def update_job(cls, job_id: str, **changes) -> None:
        jobs = cls.list_jobs()
        for job in jobs:
            if job.job_id == job_id:
                for key, value in changes.items():
                    setattr(job, key, value)
                break
        cls._save(jobs)

    @classmethod
    def remove_job(cls, job_id: str) -> None:
        jobs = [j for j in cls.list_jobs() if j.job_id != job_id]
        cls._save(jobs)

    @classmethod
    def get_job(cls, job_id: str) -> Optional[TrackedJob]:
        for job in cls.list_jobs():
            if job.job_id == job_id:
                return job
        return None
