#! python3  # noqa: E265

"""Découpage d'une extraction en plusieurs jobs successifs (« lots » de tables).

Le contour de l'emprise est recopié dans le filtre de chaque table : plus on coche de tables, plus il
faut le réduire pour que la requête reste légère (cf. `core/extent_fit.py`). Passé un certain nombre
de tables on retombe sur des rectangles ou la bbox. Plutôt que de dégrader l'emprise, on peut répartir
les tables en plusieurs jobs : chacun garde un contour fidèle. Le service n'accepte qu'un job à la
fois (HTTP 429) : les lots sont donc lancés **successivement**, le suivant partant quand le précédent
est terminé.

Ce module contient la planification (pure, testable sans QGIS) et la file des lots restants,
conservée dans les réglages QGIS pour survivre à une fermeture de QGIS.
"""

from __future__ import annotations

import json
import math
from typing import Callable, Optional, Sequence, TypeVar

from gpf_extraction.core.constants import PLUGIN_NAMESPACE

T = TypeVar("T")

#: Un contour est jugé « fidèle » jusqu'à cette tolérance de simplification (mètres) : au-delà, on
#: préfère répartir les tables en plusieurs jobs plutôt que de simplifier davantage.
FAITHFUL_MAX_TOLERANCE_M = 50

#: Nombre maximal de lots proposés : chaque job dure de l'ordre de plusieurs minutes.
MAX_BATCHES = 8

SETTINGS_KEY_PENDING_BATCHES = f"{PLUGIN_NAMESPACE}/pending_batches"


def is_faithful(fit) -> bool:
    """Le contour est-il précis, ou simplifié d'au plus `FAITHFUL_MAX_TOLERANCE_M` ?"""
    if fit is None:
        return True  # pas de contour (bbox dessinée) : rien à dégrader
    if fit.kind == "precise":
        return True
    return fit.kind == "simplified" and fit.tolerance_m <= FAITHFUL_MAX_TOLERANCE_M


def plan_batches(table_count: int, fit_for: Callable[[int], object]) -> int:
    """Nombre de lots à proposer (1 = pas de découpage).

    :param table_count: nombre de tables à extraire (avec géométrie).
    :param fit_for: `fit_for(n)` renvoie le contour retenu si une requête porte sur `n` tables.
    Découpe seulement si une seule requête dégrade le contour **et** qu'au plus `MAX_BATCHES` lots
    suffisent à le garder fidèle.
    """
    if table_count < 2 or is_faithful(fit_for(table_count)):
        return 1
    for batches in range(2, min(MAX_BATCHES, table_count) + 1):
        if is_faithful(fit_for(math.ceil(table_count / batches))):
            return batches
    return 1


def split_evenly(items: Sequence[T], batches: int) -> list[list[T]]:
    """Répartit `items` en `batches` groupes consécutifs de tailles presque égales."""
    batches = max(1, min(batches, len(items))) if items else 1
    base, extra = divmod(len(items), batches)
    out, start = [], 0
    for index in range(batches):
        size = base + (1 if index < extra else 0)
        out.append(list(items[start : start + size]))
        start += size
    return out


class BatchQueue:
    """File persistante des lots restants : `{process_id, title, bodies: [...], total, options: {...}}`."""

    @staticmethod
    def load() -> Optional[dict]:
        from qgis.core import QgsSettings

        raw = QgsSettings().value(SETTINGS_KEY_PENDING_BATCHES, "")
        if not raw:
            return None
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return state if isinstance(state, dict) and state.get("bodies") else None

    @staticmethod
    def save(state: dict) -> None:
        from qgis.core import QgsSettings

        QgsSettings().setValue(SETTINGS_KEY_PENDING_BATCHES, json.dumps(state, ensure_ascii=False))

    @staticmethod
    def clear() -> None:
        from qgis.core import QgsSettings

        QgsSettings().setValue(SETTINGS_KEY_PENDING_BATCHES, "")

    @classmethod
    def pending_count(cls) -> int:
        state = cls.load()
        return len(state["bodies"]) if state else 0
