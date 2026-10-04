#! python3  # noqa E265

"""
    Usage from the repo root folder:

    .. code-block:: bash

        python -m unittest tests.unit.test_twkb
"""

import unittest

from gpf_extraction.core.twkb import decode, encode, to_hex

SQUARE = [[(-61.54, 16.23), (-61.52, 16.23), (-61.52, 16.25), (-61.54, 16.25), (-61.54, 16.23)]]
#: Référence partagée avec `web/tests/twkb.test.mjs` : les deux encodeurs doivent produire ces octets.
SQUARE_HEX = "c600010104bf9ad83ae099bd0fc0b8020000c0b802bfb80200"


class TestTwkb(unittest.TestCase):
    def test_header_and_reference_bytes(self):
        data = encode([SQUARE])
        self.assertEqual(data[0] & 0x0F, 6)  # multipolygone
        self.assertEqual(data[0] >> 4, 12)  # précision 6, en zigzag
        self.assertEqual(data[1], 0)  # pas de métadonnées
        self.assertEqual(to_hex([SQUARE]), SQUARE_HEX)

    def test_polygon_type(self):
        data = encode([SQUARE], multi=False)
        self.assertEqual(data[0] & 0x0F, 3)
        self.assertEqual(decode(data), [SQUARE])

    def test_round_trip_multipolygon_with_hole(self):
        outer = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        hole = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75), (0.25, 0.25)]
        other = [[(10.5, -20.5), (11.5, -20.5), (11.5, -19.5), (10.5, -20.5)]]
        geom = [[outer, hole], other]
        self.assertEqual(decode(encode(geom)), geom)

    def test_precision_and_rounding(self):
        ring = [[(700000.123, 6600000.456), (700100.5, 6600000.456), (700100.5, 6600200.9), (700000.123, 6600000.456)]]
        # en mètres, 2 décimales : la coordonnée est arrondie au centimètre
        back = decode(encode([ring], precision=2))
        self.assertEqual(back[0][0][0], (700000.12, 6600000.46))
        # précision 0 : au mètre
        self.assertEqual(decode(encode([ring], precision=0))[0][0][0], (700000.0, 6600000.0))

    def test_much_lighter_than_wkt(self):
        # contour dense de 20 000 sommets (écarts de quelques dizaines de mètres, comme une côte) :
        # ≥ 4 fois plus léger que le WKT à 6 décimales
        import math

        ring = [(-61.5 + 0.2 * math.cos(a) * (1 + 0.01 * math.sin(40 * a)), 16.2 + 0.2 * math.sin(a)) for a in (2 * math.pi * i / 20000 for i in range(20000))]
        ring.append(ring[0])
        wkt = "POLYGON((" + ",".join(f"{round(x, 6)} {round(y, 6)}" for x, y in ring) + "))"
        self.assertLess(len(to_hex([[ring]])) * 4, len(wkt))

    def test_invalid_precision(self):
        with self.assertRaises(ValueError):
            encode([SQUARE], precision=8)


if __name__ == "__main__":
    unittest.main()
