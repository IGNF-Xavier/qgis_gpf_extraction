"""Recherche d'emprises administratives (commune, département, région) par nom.

La recherche libre par nom (`AdminBoundaryClient.search`) utilise l'API de
géocodage de la Géoplateforme (https://data.geopf.fr/geocodage/search,
`index=poi&category=administratif`), avec `returntruegeometry=true` pour
obtenir une géométrie précise plutôt que le point renvoyé par défaut — cette
API est conçue pour la recherche interactive (score de pertinence déjà
calculé, pas besoin de trier nous-mêmes), contrairement au WFS brut utilisé
en 3.4.4 (trois requêtes séparées, une par niveau administratif, triées à la
main). Les préréglages DOM (`preset_results`), eux, restent sur le WFS ADMIN
EXPRESS (`https://data.geopf.fr/wfs/ows`) : une recherche par code INSEE
exact n'a pas besoin de score de pertinence, et le WFS s'y prête bien.

Historique : jusqu'en 3.4.3, la recherche passait par l'API tierce
"Découpage administratif" (geo.api.gouv.fr), qui a cessé de renvoyer le
contour des départements et des régions (constaté en conditions réelles,
quels que soient les paramètres essayés) — seules les communes restaient
exploitables. La 3.4.4 avait basculé vers le WFS de la Géoplateforme pour
corriger ça ; la 3.4.5 passe à l'API de géocodage pour la recherche libre,
plus adaptée à cet usage (une seule requête pour les trois niveaux, triée
par pertinence).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from qgis.core import QgsGeometry

from ..network.http_client import NetworkClient
from .constants import ADMIN_BOUNDARY_API_BASE, GEOCODING_SEARCH_BASE
from .exceptions import AdminBoundaryNotFoundError

_WFS_LAYER_PREFIX = "LIMITES_ADMINISTRATIVES_EXPRESS.LATEST"

#: (catégorie renvoyée par l'API de géocodage, libellé affiché, champ de
#: désambiguïsation dans `properties` ou None). Seules ces trois catégories
#: sont retenues parmi celles que `category=administratif` peut renvoyer
#: (elle inclut aussi les EPCI, hors périmètre de cette recherche). Pas de
#: désambiguïsation pour département/région : contrairement aux communes,
#: leurs noms sont uniques en France, une confusion n'est pas possible.
_ADMIN_KINDS = {
    "commune": ("Commune", "depcode"),
    "département": ("Département", None),
    "région": ("Région", None),
}


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
    """Client pour la recherche d'emprise administrative (API de géocodage +
    WFS ADMIN EXPRESS de la Géoplateforme, cf. le docstring du module)."""

    def __init__(self, api_base: str = ADMIN_BOUNDARY_API_BASE):
        self._api_base = api_base.rstrip("/")
        self._network = NetworkClient(authcfg="")

    def search(self, text: str, limit: int = 20) -> list[AdminBoundaryResult]:
        """Recherche des entités administratives par nom (commune, département,
        région confondus), via l'API de géocodage de la Géoplateforme.

        :param text: texte recherché, n'importe où dans le nom.
        :type text: str
        :param limit: nombre maximum de résultats demandés à l'API avant
            filtrage (elle mélange commune/département/région/EPCI, seuls
            les trois premiers nous intéressent ici — un EPCI bien classé
            peut donc réduire le nombre de résultats utiles reçus). 20 est le
            maximum accepté par l'API avec `returntruegeometry` activé,
            defaults to 20
        :type limit: int, optional

        :return: liste des correspondances trouvées, avec leur géométrie.
        :rtype: list[AdminBoundaryResult]
        """
        text = (text or "").strip()
        if len(text) < 2:
            return []

        url = (
            f"{GEOCODING_SEARCH_BASE}?q={quote(text)}&index=poi"
            f"&category=administratif&returntruegeometry=true&limit={limit}"
        )
        response = self._network.get(url)
        if not response.ok:
            raise AdminBoundaryNotFoundError(
                f"Aucune entité administrative ne correspond à « {text} »."
            )
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdminBoundaryNotFoundError(
                f"Aucune entité administrative ne correspond à « {text} »."
            ) from exc
        features = data.get("features") if isinstance(data, dict) else None

        results: list[AdminBoundaryResult] = []
        for feature in features or []:
            props = feature.get("properties", {}) or {}
            categories = props.get("category") or []
            kind_info = next(
                (_ADMIN_KINDS[c] for c in categories if c in _ADMIN_KINDS), None
            )
            if kind_info is None:
                continue  # ex. "epci" : hors périmètre de cette recherche
            kind_label, disambiguator_field = kind_info

            # `truegeometry` est un GeoJSON encodé en chaîne (pas un objet
            # imbriqué) ; sans lui, `geometry` n'est qu'un point représentatif
            # — inutilisable comme emprise pour un filtre spatial, donc
            # ignoré plutôt que de construire une emprise trompeuse.
            true_geometry_raw = props.get("truegeometry")
            if not true_geometry_raw:
                continue
            try:
                true_geometry = json.loads(true_geometry_raw)
            except (TypeError, ValueError):
                continue
            geometry = _geojson_geometry_to_qgs_geometry(true_geometry)
            if geometry is None or geometry.isEmpty():
                continue

            disambiguator = None
            if disambiguator_field:
                values = props.get(disambiguator_field)
                disambiguator = values[0] if isinstance(values, list) and values else values
            toponym = props.get("toponym") or text
            label = f"{toponym} ({kind_label}"
            if disambiguator:
                label += f" {disambiguator}"
            label += ")"

            citycodes = props.get("citycode")
            code = citycodes[0] if isinstance(citycodes, list) and citycodes else ""
            results.append(
                AdminBoundaryResult(label=label, kind=kind_label, code=str(code), geometry=geometry)
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
