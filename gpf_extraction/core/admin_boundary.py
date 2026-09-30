"""Recherche d'emprises administratives (commune, département, région) par nom.

Utilise l'API publique et non authentifiée "Découpage administratif"
(https://geo.api.gouv.fr), qui renvoie directement le contour géométrique
(GeoJSON, EPSG:4326) de l'entité recherchée — ce qui évite de dépendre d'un
service WFS pour cette seule fonctionnalité.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsGeometry

from ..network.http_client import NetworkClient
from .constants import ADMIN_BOUNDARY_API_BASE
from .exceptions import AdminBoundaryNotFoundError

#: (chemin API, libellé du type) pour chaque type d'entité recherchée.
_ADMIN_KINDS = (
    ("communes", "Commune"),
    ("departements", "Département"),
    ("regions", "Région"),
)


@dataclass
class AdminBoundaryResult:
    label: str
    kind: str
    code: str
    geometry: QgsGeometry  # EPSG:4326


#: Rectangles englobants (EPSG:4326) pour la France métropolitaine et chaque
#: département d'outre-mer, en repli à la recherche par nom ci-dessus.
#:
#: `geo.api.gouv.fr` ne renvoie plus le contour (`contour`) des départements
#: ni des régions — constaté en conditions réelles, quel que soit le
#: paramètre essayé (`fields=contour`, `geometry=contour`, avec ou sans
#: filtre `nom`/`code`) : seul le contour des *communes* est encore fourni.
#: Un contour précis à l'échelle d'un département ou de la France entière
#: n'est donc plus disponible via cette API ; ces rectangles, volontairement
#: un peu généreux (incluent une marge de mer autour des côtes), servent de
#: préréglage pratique — l'utilisateur reste libre de dessiner une BBox plus
#: précise si besoin. Aucun contour pour les collectivités d'outre-mer
#: (Saint-Martin, Saint-Barthélemy, Saint-Pierre-et-Miquelon, ...) : elles ne
#: sont pas des départements au sens de cette API.
#: (libellé, WKT du rectangle, code INSEE du département — vide pour la
#: métropole, qui n'en a pas un seul) : ce code sert aussi à repérer, côté
#: `dlg_main.py`, qu'une emprise DOM est sélectionnée, pour avertir si le
#: produit choisi ne semble pas couvrir les DOM (cf. `DOM_DEPARTMENT_CODES`).
PRESET_EXTENTS: tuple[tuple[str, str, str], ...] = (
    ("France métropolitaine", "POLYGON((-5.5 41.0, 10.0 41.0, 10.0 51.5, -5.5 51.5, -5.5 41.0))", ""),
    ("Guadeloupe (971)", "POLYGON((-61.85 15.83, -60.95 15.83, -60.95 16.55, -61.85 16.55, -61.85 15.83))", "971"),
    ("Martinique (972)", "POLYGON((-61.25 14.35, -60.77 14.35, -60.77 14.90, -61.25 14.90, -61.25 14.35))", "972"),
    ("Guyane (973)", "POLYGON((-54.60 2.05, -51.55 2.05, -51.55 5.85, -54.60 5.85, -54.60 2.05))", "973"),
    ("La Réunion (974)", "POLYGON((55.20 -21.40, 55.85 -21.40, 55.85 -20.85, 55.20 -20.85, 55.20 -21.40))", "974"),
    ("Mayotte (976)", "POLYGON((45.00 -13.05, 45.35 -13.05, 45.35 -12.60, 45.00 -12.60, 45.00 -13.05))", "976"),
)

#: Codes INSEE des 5 départements d'outre-mer parmi les préréglages
#: ci-dessus — utilisé pour savoir si l'emprise actuellement choisie est un
#: DOM, indépendamment du libellé (dont la traduction pourrait changer).
DOM_DEPARTMENT_CODES = frozenset(code for _, _, code in PRESET_EXTENTS if code)


def preset_results() -> list[AdminBoundaryResult]:
    """Résultats préréglés (France métropolitaine, chaque DOM) : aucun appel
    réseau, la géométrie est un rectangle englobant construit localement —
    voir `PRESET_EXTENTS`."""
    return [
        AdminBoundaryResult(
            label=f"{label} (préréglage)",
            kind="Préréglage",
            code=code,
            geometry=QgsGeometry.fromWkt(wkt),
        )
        for label, wkt, code in PRESET_EXTENTS
    ]


class AdminBoundaryClient:
    """Client pour l'API "Découpage administratif" (geo.api.gouv.fr)."""

    def __init__(self, api_base: str = ADMIN_BOUNDARY_API_BASE):
        self._api_base = api_base.rstrip("/")
        self._network = NetworkClient(authcfg="")

    def search(self, text: str, limit: int = 8) -> list[AdminBoundaryResult]:
        """Recherche des entités administratives par nom (commune, département,
        région confondus).

        :param text: texte recherché (nom, ou début de nom).
        :type text: str
        :param limit: nombre maximum de résultats par type d'entité, defaults to 8
        :type limit: int, optional

        :return: liste des correspondances trouvées, avec leur géométrie.
        :rtype: list[AdminBoundaryResult]
        """
        text = (text or "").strip()
        if len(text) < 2:
            return []

        results: list[AdminBoundaryResult] = []
        for path, kind_label in _ADMIN_KINDS:
            # `codeDepartement` (communes) / `codeRegion` (départements) sont
            # demandés pour désambiguïser les homonymes (ex. plusieurs
            # communes "Montreuil" en France) directement dans le libellé.
            extra_field = "codeDepartement" if path == "communes" else "codeRegion"
            url = (
                f"{self._api_base}/{path}?nom={text}"
                f"&fields=nom,code,contour,{extra_field}&boost=population&limit={limit}"
            )
            response = self._network.get(url)
            if not response.ok:
                continue
            try:
                items = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                contour = item.get("contour")
                if not contour:
                    continue
                geometry = _geojson_geometry_to_qgs_geometry(contour)
                if geometry is None or geometry.isEmpty():
                    continue
                disambiguator = item.get(extra_field)
                label = f"{item.get('nom', text)} ({kind_label}"
                if disambiguator:
                    label += f" {disambiguator}"
                label += ")"
                results.append(
                    AdminBoundaryResult(
                        label=label,
                        kind=kind_label,
                        code=str(item.get("code", "")),
                        geometry=geometry,
                    )
                )

        if not results:
            raise AdminBoundaryNotFoundError(
                f"Aucune entité administrative ne correspond à « {text} »."
            )
        return results


def _geojson_geometry_to_qgs_geometry(geom: dict) -> Optional[QgsGeometry]:
    """Convertit une géométrie GeoJSON Polygon/MultiPolygon en `QgsGeometry`.

    Pas de dépendance externe (pas de GDAL/shapely nécessaire) : construction
    directe d'un WKT à partir des coordonnées GeoJSON.
    """
    geom_type = geom.get("type")
    coordinates = geom.get("coordinates")
    if not geom_type or coordinates is None:
        return None

    if geom_type == "Polygon":
        wkt = f"POLYGON({_rings_to_wkt(coordinates)})"
    elif geom_type == "MultiPolygon":
        polygons = ",".join(f"({_rings_to_wkt(poly)})" for poly in coordinates)
        wkt = f"MULTIPOLYGON({polygons})"
    else:
        return None

    geometry = QgsGeometry.fromWkt(wkt)
    if geometry.isNull():
        return None
    return geometry


def _rings_to_wkt(rings: list) -> str:
    ring_strings = []
    for ring in rings:
        points = ",".join(f"{x} {y}" for x, y in ring)
        ring_strings.append(f"({points})")
    return ",".join(ring_strings)
