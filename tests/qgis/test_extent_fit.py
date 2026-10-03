#! python3  # noqa E265

"""
    Usage from the repo root folder:

    .. code-block:: bash

        python -m unittest tests.qgis.test_extent_fit
"""

# standard library
import math

from qgis.core import QgsGeometry
from qgis.testing import unittest

# project
from gpf_extraction.core.extent_fit import (
    FIT_AUTO,
    FIT_BBOX,
    FIT_ENVELOPES,
    FIT_PRECISE,
    cluster_rects,
    fit_extent,
    vertex_budget,
    vertex_count,
    wkt_precision,
)


def island(cx: float, cy: float, r: float, n: int) -> QgsGeometry:
    """Polygone à contour très découpé : cercle bruité à haute fréquence."""
    points = []
    for i in range(n):
        a = 2 * math.pi * i / n
        noise = 1 + 0.02 * math.sin(a * 300) + 0.01 * math.sin(a * 1700)
        points.append(f"{cx + r * noise * math.cos(a):.7f} {cy + r * noise * math.sin(a):.7f}")
    points.append(points[0])
    return QgsGeometry.fromWkt(f"POLYGON(({', '.join(points)}))")


def archipelago() -> QgsGeometry:
    """Grande île détaillée, une moyenne proche, et deux îlots lointains."""
    parts = [
        island(-61.5, 16.2, 0.25, 40000),
        island(-61.3, 15.95, 0.1, 4000),
        island(-62.6, 15.0, 0.03, 800),
        island(-60.2, 17.0, 0.04, 800),
    ]
    return QgsGeometry.collectGeometry(parts)


class TestExtentFit(unittest.TestCase):
    def test_precise_when_under_budget(self):
        fit = fit_extent(island(0, 0, 1, 500), 4326, FIT_AUTO, max_vertices=1000)
        self.assertEqual(fit.kind, FIT_PRECISE)

    def test_simplifies_when_over_budget(self):
        geom = archipelago()
        fit = fit_extent(geom, 4326, FIT_AUTO, max_vertices=8000)
        self.assertEqual(fit.kind, "simplified")
        self.assertLessEqual(fit.vertices, 8000)
        self.assertLess(fit.vertices, vertex_count(geom) / 5)
        self.assertGreaterEqual(fit.tolerance_m, 10)
        self.assertIn("simplifié", fit.describe())

    def test_simplification_keeps_every_part(self):
        # Les îlots sont conservés (ou absorbés par un voisin), jamais supprimés.
        geom = archipelago()
        fit = fit_extent(geom, 4326, FIT_AUTO, max_vertices=8000)
        for part in geom.asGeometryCollection():
            self.assertTrue(fit.geometry.intersects(part))
            uncovered = part.difference(fit.geometry).area() / part.area()
            self.assertLess(uncovered, 1e-3)

    def test_envelopes_when_simplification_is_not_enough(self):
        geom = archipelago()
        fit = fit_extent(geom, 4326, FIT_AUTO, max_vertices=120)
        self.assertEqual(fit.kind, FIT_ENVELOPES)
        self.assertGreaterEqual(fit.rects, 2)
        self.assertLessEqual(fit.vertices, 120)
        for part in geom.asGeometryCollection():
            self.assertLess(part.difference(fit.geometry).area(), 1e-9)

    def test_forced_modes(self):
        geom = archipelago()
        self.assertEqual(fit_extent(geom, 4326, FIT_PRECISE, max_vertices=10).kind, FIT_PRECISE)
        bbox = fit_extent(geom, 4326, FIT_BBOX)
        self.assertEqual(bbox.kind, FIT_BBOX)
        self.assertIsNone(bbox.geometry)
        self.assertEqual(fit_extent(geom, 4326, FIT_ENVELOPES).kind, FIT_ENVELOPES)

    def test_single_zone_collapses_to_bbox(self):
        fit = fit_extent(island(0, 0, 1, 20000), 4326, FIT_AUTO, max_vertices=100)
        self.assertEqual(fit.kind, FIT_BBOX)
        self.assertIsNone(fit.geometry)

    def test_projected_srid_uses_meters(self):
        # EPSG:2975 (RGR92 / UTM 40S) : unité = mètre, la tolérance n'est pas convertie en degrés.
        geom = island(340000, 7650000, 20000, 20000)
        fit = fit_extent(geom, 2975, FIT_AUTO, max_vertices=3000)
        self.assertEqual(fit.kind, "simplified")
        self.assertLessEqual(fit.vertices, 3000)

    def test_cluster_rects(self):
        self.assertEqual(cluster_rects([(0, 0, 1, 1), (0.5, 0.5, 2, 2)]), [(0, 0, 2, 2)])
        self.assertEqual(len(cluster_rects([(0, 0, 1, 1), (50, 50, 51, 51)])), 2)
        self.assertEqual(len(cluster_rects([(0, 0, 1, 1), (50, 50, 51, 51), (100, 0, 101, 1)], max_rects=2)), 2)
        many = [(i % 30 * 0.5, i // 30 * 0.5, i % 30 * 0.5 + 0.01, i // 30 * 0.5 + 0.01) for i in range(600)]
        self.assertLessEqual(len(cluster_rects(many, max_rects=12)), 12)

    def test_vertex_budget(self):
        self.assertGreater(vertex_budget(3), vertex_budget(59))
        self.assertLess(vertex_budget(3, predicates=2), vertex_budget(3, predicates=1))
        self.assertEqual(vertex_budget(5000), 100)

    def test_wkt_precision(self):
        self.assertEqual(wkt_precision(4326), 6)
        self.assertEqual(wkt_precision(2154), 2)
        geom = QgsGeometry.fromWkt("POINT(0.123456789 1.987654321)")
        self.assertEqual(geom.asWkt(wkt_precision(4326)), "Point (0.123457 1.987654)")


if __name__ == "__main__":
    unittest.main()
