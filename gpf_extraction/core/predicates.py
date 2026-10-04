#! python3  # noqa: E265

"""Prédicats géométriques du filtre spatial et leur réduction logique.

Le filtre de chaque table combine les prédicats cochés en OU, et le contour est recopié dans chacun :
deux prédicats, c'est deux fois le poids. Or tous les prédicats « positifs » entraînent l'intersection :

    Contains, Within, Touches, Crosses, Overlaps, Equals  ⇒  Intersects

donc `Intersects OR Contains` (par exemple) renvoie exactement les mêmes lignes que `Intersects` seul.
Seul `Disjoint` (le contraire de `Intersects`) échappe à cette règle. On réduit donc la liste avant de
construire le filtre : même résultat, moitié moins de contour.

Module sans dépendance QGIS (testable seul).
"""

from __future__ import annotations

from typing import Iterable

DEFAULT_PREDICATES = ["Intersects"]

#: Prédicats qui impliquent `Intersects` (deux géométries non vides qui se contiennent, sont dans
#: l'autre, se touchent, se croisent, se chevauchent ou sont égales ont au moins un point commun).
IMPLY_INTERSECTS = frozenset({"Contains", "Within", "Touches", "Crosses", "Overlaps", "Equals"})


def effective_predicates(predicates: Iterable[str]) -> list[str]:
    """Prédicats réellement envoyés : `Intersects` seul dès qu'il est coché, sauf avec `Disjoint`
    (`Intersects OR Disjoint` ne se simplifie pas proprement : on garde la demande telle quelle)."""
    unique = list(dict.fromkeys(predicates)) or list(DEFAULT_PREDICATES)
    if "Intersects" in unique and "Disjoint" not in unique:
        return ["Intersects"]
    return unique


def reduction_note(predicates: Iterable[str]) -> str:
    """Phrase à afficher quand la réduction a retiré des prédicats, sinon une chaîne vide."""
    chosen = list(dict.fromkeys(predicates))
    effective = effective_predicates(chosen)
    removed = [p for p in chosen if p not in effective]
    if not removed:
        return ""
    return f"{', '.join(removed)} déjà inclus dans {', '.join(effective)} : un seul prédicat envoyé, même résultat"
