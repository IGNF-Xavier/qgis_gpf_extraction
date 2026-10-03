#! python3  # noqa: E265

"""Adapte le contour d'emprise à la taille acceptée par le service d'extraction.

Constaté en conditions réelles : le contour précis de la Guadeloupe (archipel,
côte très découpée, ~100 000 sommets) donnait une requête de ~6,8 Mo — le
contour est recopié dans le filtre de *chaque* table — et le service répondait
HTTP 500, alors que la même extraction avec une bbox passait.

Stratégie « automatique », du plus fidèle au plus léger :

1. contour précis, s'il tient dans le budget de sommets ;
2. contour simplifié (Douglas-Peucker) puis élargi de la même tolérance
   (buffer), avec une tolérance croissante et plafonnée : l'emprise d'origine
   reste entièrement couverte ;
3. rectangles englobants (un par groupe de parties proches) ;
4. rectangle unique (bbox).

Chaque étape recouvre l'emprise : on peut récupérer un peu plus de données,
pratiquement jamais moins (résidu mesuré sur la Guadeloupe à 10 m : 192 m² sur
~1 600 km²). L'option « découper à l'emprise » du plugin retire l'excédent
après téléchargement. Le seuil réel du service
n'est pas documenté. Mesuré sur la Guadeloupe (3 tables) : filtres de ~190 Ko chacun → HTTP 500,
filtres de ~10 Ko → accepté. Le budget par défaut (60 Ko par requête) reste donc proche de la
valeur qui a fonctionné ; le seuil exact n'est pas connu.

Module indépendant de l'interface (uniquement `qgis.core`), donc testable seul.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsGeometry, QgsRectangle

try:  # QGIS >= 3.22
    _CAP_FLAT = Qgis.EndCapStyle.Flat
    _JOIN_MITER = Qgis.JoinStyle.Miter
except AttributeError:  # QGIS 3.16 – 3.20
    _CAP_FLAT = QgsGeometry.CapStyle.Flat
    _JOIN_MITER = QgsGeometry.JoinStyle.Miter

FIT_AUTO = "auto"
FIT_PRECISE = "precise"
FIT_ENVELOPES = "envelopes"
FIT_BBOX = "bbox"
FIT_MODES = (FIT_AUTO, FIT_PRECISE, FIT_ENVELOPES, FIT_BBOX)

#: Tolérances de simplification essayées (mètres), de la plus fine à la plus grossière.
TOLERANCES_M = (10, 25, 50, 100, 250)

#: Poids visé pour les filtres spatiaux d'une requête (le contour est recopié dans chaque table).
DEFAULT_BUDGET_BYTES = 60_000
BYTES_PER_VERTEX = 22
MIN_VERTICES = 100
MAX_VERTICES = 50_000

_METERS_PER_DEGREE = 111_320
_RECT_STEPS = 4  # points ajoutés par côté d'un rectangle (il se reprojette ensuite)


@dataclass
class ExtentFit:
    """Contour retenu pour le filtre. `geometry` est None pour `bbox` : l'appelant
    utilise alors le rectangle (`ST_MakeEnvelope`)."""

    kind: str  # FIT_PRECISE (précis), "simplified", FIT_ENVELOPES ou FIT_BBOX
    geometry: Optional[QgsGeometry]
    vertices: int
    original_vertices: int
    tolerance_m: float = 0.0
    rects: int = 0

    def describe(self) -> str:
        if self.kind == FIT_PRECISE:
            return f"contour précis ({self.vertices:,} sommets)".replace(",", " ")
        if self.kind == "simplified":
            return (
                f"contour simplifié à {self.tolerance_m:g} m "
                f"({self.vertices:,} sommets au lieu de {self.original_vertices:,})"
            ).replace(",", " ")
        if self.kind == FIT_ENVELOPES:
            return f"{self.rects} rectangles englobants (au lieu de {self.original_vertices:,} sommets)".replace(",", " ")
        return "rectangle englobant unique"


def vertex_count(geometry: QgsGeometry) -> int:
    return geometry.constGet().nCoordinates() if not geometry.isNull() else 0


def vertex_budget(
    tables: int,
    predicates: int = 1,
    max_bytes: int = DEFAULT_BUDGET_BYTES,
    bytes_per_vertex: int = BYTES_PER_VERTEX,
) -> int:
    """Budget de sommets par filtre : `max_bytes` / (tables × prédicats × octets par sommet), borné."""
    copies = max(1, tables) * max(1, predicates)
    return max(MIN_VERTICES, min(MAX_VERTICES, max_bytes // (copies * bytes_per_vertex)))


def is_geographic(srid: int) -> bool:
    crs = QgsCoordinateReferenceSystem(f"EPSG:{srid}")
    return crs.isValid() and crs.isGeographic()


def wkt_precision(srid: int) -> int:
    """Décimales utiles du WKT : 6 en degrés (≈ 10 cm), 2 en mètres (1 cm). Le défaut de
    `asWkt()` (17) alourdit inutilement la requête."""
    return 6 if is_geographic(srid) else 2


def _to_units(meters: float, srid: int) -> float:
    return meters / _METERS_PER_DEGREE if is_geographic(srid) else meters


# ---------------------------------------------------------------- Rectangles englobants
Rect = tuple[float, float, float, float]


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(r: Rect) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def cluster_rects(rects: list[Rect], max_rects: int = 12, ratio: float = 2.0) -> list[Rect]:
    """Regroupe des rectangles : ceux qui se touchent fusionnent toujours ; deux voisins
    fusionnent si leur union ne gaspille pas trop de surface (`ratio`) ; au-delà de
    `max_rects`, on fusionne de force la paire qui gaspille le moins."""
    items = list(rects)
    seeds = 150  # garde-fou de coût : beaucoup d'îlots sont d'abord rattachés aux plus grands
    if len(items) > seeds:
        items.sort(key=_area, reverse=True)
        head, tail = items[:seeds], items[seeds:]
        for small in tail:
            best = min(range(len(head)), key=lambda i: _area(_union(head[i], small)) - _area(head[i]))
            head[best] = _union(head[best], small)
        items = head
    while True:
        best_pair = None
        best_score = float("inf")
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                union = _union(items[i], items[j])
                waste = _area(union) - _area(items[i]) - _area(items[j])
                touching = _overlap(items[i], items[j])
                close = _area(union) <= ratio * (_area(items[i]) + _area(items[j]))
                if not touching and not close and len(items) <= max_rects:
                    continue
                score = float("-inf") if touching else waste
                if best_pair is None or score < best_score:
                    best_score, best_pair = score, (i, j, union)
        if best_pair is None:
            return items
        i, j, union = best_pair
        items = [r for index, r in enumerate(items) if index not in (i, j)] + [union]


def _envelopes(geometry: QgsGeometry, max_rects: int) -> list[Rect]:
    parts = geometry.asGeometryCollection() or [geometry]
    rects: list[Rect] = []
    for part in parts:
        box = part.boundingBox()
        rects.append((box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()))
    return cluster_rects(rects, max_rects=max_rects)


def _rect_geometry(rect: Rect) -> QgsGeometry:
    # Densifié : une fois reprojeté (Lambert, UTM…), un rectangle en degrés a des côtés courbes.
    return QgsGeometry.fromRect(QgsRectangle(*rect)).densifyByCount(_RECT_STEPS)


def _simplify_and_grow(parts: list[QgsGeometry], tolerance: float) -> Optional[QgsGeometry]:
    """Simplifie chaque partie (Douglas-Peucker) puis l'élargit de la même tolérance.

    Chaque sommet écarté est à moins de `tolerance` du contour simplifié, que le buffer
    (jointure en onglet, limite 2 : au moins aussi large qu'un buffer arrondi) recouvre donc
    entièrement. Partie par partie : `simplify()` sur l'ensemble supprime les petits îlots, ce
    qui ferait perdre des données. Un îlot qui s'effondre est remplacé par son rectangle."""
    grown_parts: list[QgsGeometry] = []
    for part in parts:
        simple = part.simplify(tolerance)
        grown = None
        if not simple.isNull() and not simple.isEmpty():
            grown = simple.buffer(tolerance, 1, _CAP_FLAT, _JOIN_MITER, 2.0)
        if grown is None or grown.isNull() or grown.isEmpty():
            grown = QgsGeometry.fromRect(part.boundingBox().buffered(tolerance))
        grown_parts.append(grown)
    merged = QgsGeometry.unaryUnion(grown_parts)  # des parties voisines peuvent se chevaucher après le buffer
    return None if merged.isNull() or merged.isEmpty() else merged


# ---------------------------------------------------------------- Choix de la stratégie
def fit_extent(
    geometry: QgsGeometry,
    srid: int,
    mode: str = FIT_AUTO,
    max_vertices: int = 5000,
    max_rects: int = 12,
) -> ExtentFit:
    """Choisit le contour à envoyer.

    :param geometry: contour de l'emprise, déjà dans le SRID `srid`.
    :param srid: SRID de `geometry` (donne l'unité des tolérances : degrés ou mètres).
    :param mode: `auto`, `precise`, `envelopes` ou `bbox`.
    :param max_vertices: budget de sommets pour un filtre (cf. `vertex_budget`).
    """
    original = vertex_count(geometry)

    def result(kind: str, geom: Optional[QgsGeometry], **extra) -> ExtentFit:
        return ExtentFit(kind, geom, vertex_count(geom) if geom is not None else 5, original, **extra)

    if mode == FIT_BBOX:
        return result(FIT_BBOX, None)
    if mode == FIT_PRECISE:
        return result(FIT_PRECISE, geometry)

    if mode == FIT_AUTO:
        if original <= max_vertices:
            return result(FIT_PRECISE, geometry)
        parts = geometry.asGeometryCollection() or [geometry]
        for meters in TOLERANCES_M:
            grown = _simplify_and_grow(parts, _to_units(meters, srid))
            if grown is not None and vertex_count(grown) <= max_vertices:
                return result("simplified", grown, tolerance_m=meters)

    # `envelopes`, ou repli de l'automatique quand même 250 m ne suffit pas.
    limit = max(1, min(max_rects, max_vertices // (_RECT_STEPS * 4 + 1)))
    rects = _envelopes(geometry, limit)
    if len(rects) == 1:
        return result(FIT_BBOX, None, rects=1)
    union = QgsGeometry.collectGeometry([_rect_geometry(r) for r in rects])
    return result(FIT_ENVELOPES, union, rects=len(rects))
