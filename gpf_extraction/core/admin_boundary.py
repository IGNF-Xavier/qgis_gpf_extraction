"""Recherche d'emprises administratives (commune, département, région) par nom.

Utilise le WFS public et non authentifié de la Géoplateforme
(https://data.geopf.fr/wfs/ows), qui diffuse ADMIN EXPRESS — les limites
administratives officielles de l'IGN, mises à jour en continu
(`LIMITES_ADMINISTRATIVES_EXPRESS.LATEST`) — en GeoJSON (EPSG:4326).

Remplace l'API tierce "Découpage administratif" (geo.api.gouv.fr), utilisée
jusqu'en 3.4.3 : constaté en conditions réelles qu'elle ne renvoie plus le
contour (`contour`) des départements ni des régions, quels que soient les
paramètres essayés (`fields=contour`, `geometry=contour`, avec ou sans
filtre `nom`/`code`) — seules les communes restaient exploitables. Le WFS de
la Géoplateforme, déjà utilisé par ailleurs dans ce plugin, n'a pas cette
limitation et renvoie les trois niveaux avec le même schéma d'attributs
(`nom_officiel`, `code_insee`, ...) que les tables BD TOPO du service
d'extraction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsGeometry

from ..network.http_client import NetworkClient
from .constants import ADMIN_BOUNDARY_API_BASE
from .exceptions import AdminBoundaryNotFoundError

_WFS_LAYER_PREFIX = "LIMITES_ADMINISTRATIVES_EXPRESS.LATEST"

#: (type WFS, libellé affiché, champ de désambiguïsation ou None, tri par
#: population) pour chaque niveau administratif recherché. Le tri par
#: population (communes seulement : les deux autres niveaux n'ont pas ce
#: champ) reproduit le comportement de l'ancienne API (`boost=population`) :
#: entre deux communes homonymes, la plus peuplée apparaît en premier.
_ADMIN_KINDS = (
    ("commune", "Commune", "code_insee_du_departement", True),
    ("departement", "Département", "code_insee_de_la_region", False),
    ("region", "Région", None, False),
)


@dataclass
class AdminBoundaryResult:
    label: str
    kind: str
    code: str
    geometry: QgsGeometry  # EPSG:4326


#: Rectangle englobant (EPSG:4326) pour la France métropolitaine : aucune
#: entité "pays" n'existe au niveau région/département, donc pas d'équivalent
#: WFS direct ; un rectangle généreux (marge de mer incluse) sert de
#: préréglage pratique plutôt qu'une union de toutes les régions
#: métropolitaines (fastidieuse et inutilement précise pour cet usage).
_METROPOLE_LABEL = "France métropolitaine"
_METROPOLE_WKT = "POLYGON((-5.5 41.0, 10.0 41.0, 10.0 51.5, -5.5 51.5, -5.5 41.0))"

#: (libellé, code INSEE) des 5 départements d'outre-mer proposés en
#: préréglage — pas les collectivités d'outre-mer (Saint-Martin,
#: Saint-Barthélemy, Saint-Pierre-et-Miquelon, ...), qui ne sont pas des
#: départements. Leur géométrie réelle est récupérée en direct (une seule
#: requête WFS pour les 5) par `preset_results()`, avec repli sur un
#: rectangle si le WFS est indisponible.
_DOM_PRESETS = (
    ("Guadeloupe (971)", "971", "POLYGON((-61.85 15.83, -60.95 15.83, -60.95 16.55, -61.85 16.55, -61.85 15.83))"),
    ("Martinique (972)", "972", "POLYGON((-61.25 14.35, -60.77 14.35, -60.77 14.90, -61.25 14.90, -61.25 14.35))"),
    ("Guyane (973)", "973", "POLYGON((-54.60 2.05, -51.55 2.05, -51.55 5.85, -54.60 5.85, -54.60 2.05))"),
    ("La Réunion (974)", "974", "POLYGON((55.20 -21.40, 55.85 -21.40, 55.85 -20.85, 55.20 -20.85, 55.20 -21.40))"),
    ("Mayotte (976)", "976", "POLYGON((45.00 -13.05, 45.35 -13.05, 45.35 -12.60, 45.00 -12.60, 45.00 -13.05))"),
)

#: Codes INSEE des 5 DOM ci-dessus — utilisé pour savoir si l'emprise
#: actuellement choisie est un DOM, indépendamment du libellé.
DOM_DEPARTMENT_CODES = frozenset(code for _, code, _ in _DOM_PRESETS)


def preset_results() -> list[AdminBoundaryResult]:
    """Résultats préréglés : France métropolitaine (rectangle fixe) et
    chaque DOM (géométrie réelle récupérée en une seule requête WFS ; repli
    sur un rectangle par DOM si cette requête échoue — jamais bloquant)."""
    results = [
        AdminBoundaryResult(
            label=f"{_METROPOLE_LABEL} (préréglage)",
            kind="Préréglage",
            code="",
            geometry=QgsGeometry.fromWkt(_METROPOLE_WKT),
        )
    ]

    real_geometries: dict[str, QgsGeometry] = {}
    try:
        codes = ",".join(f"'{code}'" for _, code, _ in _DOM_PRESETS)
        client = AdminBoundaryClient()
        response = client._network.get(
            f"{client._api_base}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
            f"&TYPENAME={_WFS_LAYER_PREFIX}:departement&OUTPUTFORMAT=application/json"
            f"&CQL_FILTER=code_insee IN ({codes})"
        )
        if response.ok:
            data = json.loads(response.body.decode("utf-8"))
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                code = str(props.get("code_insee", ""))
                geometry = _geojson_geometry_to_qgs_geometry(feature.get("geometry"))
                if code and geometry is not None and not geometry.isEmpty():
                    real_geometries[code] = geometry
    except (ConnectionError, ValueError, TypeError):
        pass  # repli silencieux sur les rectangles ci-dessous

    for label, code, fallback_wkt in _DOM_PRESETS:
        geometry = real_geometries.get(code) or QgsGeometry.fromWkt(fallback_wkt)
        results.append(
            AdminBoundaryResult(
                label=f"{label} (préréglage)", kind="Préréglage", code=code, geometry=geometry
            )
        )
    return results


class AdminBoundaryClient:
    """Client pour le WFS ADMIN EXPRESS de la Géoplateforme."""

    def __init__(self, api_base: str = ADMIN_BOUNDARY_API_BASE):
        self._api_base = api_base.rstrip("/")
        self._network = NetworkClient(authcfg="")

    def search(self, text: str, limit: int = 8) -> list[AdminBoundaryResult]:
        """Recherche des entités administratives par nom (commune, département,
        région confondus).

        :param text: texte recherché, n'importe où dans le nom (insensible à
            la casse et aux accents grâce à `ILIKE`).
        :type text: str
        :param limit: nombre maximum de résultats par niveau administratif,
            defaults to 8
        :type limit: int, optional

        :return: liste des correspondances trouvées, avec leur géométrie.
        :rtype: list[AdminBoundaryResult]
        """
        text = (text or "").strip()
        if len(text) < 2:
            return []

        # Échappement CQL : une quote simple s'échappe en la doublant (comme
        # en SQL standard, dont CQL_FILTER reprend la syntaxe des littéraux).
        escaped = text.replace("'", "''")

        results: list[AdminBoundaryResult] = []
        for type_name, kind_label, extra_field, sort_by_population in _ADMIN_KINDS:
            fields = "nom_officiel,code_insee,geometrie"
            if extra_field:
                fields += f",{extra_field}"
            url = (
                f"{self._api_base}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
                f"&TYPENAME={_WFS_LAYER_PREFIX}:{type_name}&OUTPUTFORMAT=application/json"
                f"&PROPERTYNAME={fields}&COUNT={limit}"
                f"&CQL_FILTER=nom_officiel ILIKE '%25{escaped}%25'"
            )
            if sort_by_population:
                url += "&SORTBY=population D"
            response = self._network.get(url)
            if not response.ok:
                continue
            try:
                data = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            features = data.get("features") if isinstance(data, dict) else None
            if not isinstance(features, list):
                continue
            for feature in features:
                props = feature.get("properties", {}) or {}
                geometry = _geojson_geometry_to_qgs_geometry(feature.get("geometry"))
                if geometry is None or geometry.isEmpty():
                    continue
                disambiguator = props.get(extra_field) if extra_field else None
                label = f"{props.get('nom_officiel', text)} ({kind_label}"
                if disambiguator:
                    label += f" {disambiguator}"
                label += ")"
                results.append(
                    AdminBoundaryResult(
                        label=label,
                        kind=kind_label,
                        code=str(props.get("code_insee", "")),
                        geometry=geometry,
                    )
                )

        if not results:
            raise AdminBoundaryNotFoundError(
                f"Aucune entité administrative ne correspond à « {text} »."
            )
        return results


def _geojson_geometry_to_qgs_geometry(geom: Optional[dict]) -> Optional[QgsGeometry]:
    """Convertit une géométrie GeoJSON Polygon/MultiPolygon en `QgsGeometry`.

    Pas de dépendance externe (pas de GDAL/shapely nécessaire) : construction
    directe d'un WKT à partir des coordonnées GeoJSON.
    """
    if not geom:
        return None
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
