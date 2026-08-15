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
            url = (
                f"{self._api_base}/{path}?nom={text}"
                f"&fields=nom,code,contour&boost=population&limit={limit}"
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
                results.append(
                    AdminBoundaryResult(
                        label=f"{item.get('nom', text)} ({kind_label})",
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
