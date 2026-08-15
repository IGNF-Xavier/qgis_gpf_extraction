"""Petits utilitaires de normalisation de texte, partagés par les modules de
correspondance approximative (catalogue CSW, fichiers de style)."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    """Ramène un texte à ses seuls caractères alphanumériques en minuscules,
    pour des comparaisons insensibles à la casse, aux espaces, accents
    d'encodage et à la ponctuation."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())
