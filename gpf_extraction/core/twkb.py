#! python3  # noqa: E265

"""Encodage TWKB (Tiny WKB) d'un (Multi)Polygone, pour alléger le filtre spatial.

Le contour est recopié dans le filtre de chaque table de la requête ; en WKT il pèse
~21 octets par sommet. Le TWKB stocke les coordonnées en entiers, en différences par
rapport au point précédent (zigzag + varint), puis la requête l'écrit en hexadécimal :
~4,5 octets par sommet à 10 cm de précision sur un contour détaillé (÷ 4,6 mesuré sur la
Guadeloupe), un peu plus sur un contour simplifié (les écarts entre sommets sont plus grands).
Côté serveur : `ST_SetSRID(ST_GeomFromTWKB(decode('…', 'hex')), srid)` — le TWKB ne porte pas
de SRID. Vérifié en conditions réelles : le service d'extraction exécute cette fonction.

Format (spec TWKB) : octet 1 = type (bas 4 bits : 3 polygone, 6 multipolygone) | précision en
zigzag (haut 4 bits) ; octet 2 = métadonnées (0 : ni bbox, ni taille, ni identifiants) ; puis,
pour un polygone, le nombre d'anneaux (varint) et, par anneau, le nombre de points (varint)
suivi des points en différences entières. L'état du delta se poursuit d'un anneau à l'autre et
d'un polygone à l'autre. Le point de fermeture de chaque anneau est omis (le lecteur PostGIS
referme les anneaux).

Module sans dépendance QGIS : les polygones sont des listes imbriquées
`[polygone][anneau][(x, y), …]`, anneaux fermés (premier point répété à la fin).
"""

from __future__ import annotations

from typing import Sequence

Ring = Sequence[Sequence[float]]
Polygon = Sequence[Ring]

_TYPE_POLYGON = 3
_TYPE_MULTIPOLYGON = 6


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode(polygons: Sequence[Polygon], precision: int = 6, multi: bool = True) -> bytes:
    """Encode des polygones en TWKB.

    :param polygons: `[polygone][anneau][(x, y), …]`, anneaux fermés.
    :param precision: nombre de décimales conservées (de -8 à 7) ; 6 en degrés ≈ 10 cm.
    :param multi: MultiPolygon si vrai, sinon Polygon (un seul polygone attendu).
    """
    if not -8 <= precision <= 7:
        raise ValueError("précision TWKB hors de -8..7")
    scale = 10**precision
    state = [0, 0]

    def ring_bytes(ring: Ring) -> bytes:
        points = ring[:-1]  # le point de fermeture est omis
        out = bytearray(_varint(len(points)))
        for x, y in points:
            ix, iy = round(x * scale), round(y * scale)
            out += _varint(_zigzag(ix - state[0])) + _varint(_zigzag(iy - state[1]))
            state[0], state[1] = ix, iy
        return bytes(out)

    def polygon_bytes(rings: Polygon) -> bytes:
        return _varint(len(rings)) + b"".join(ring_bytes(r) for r in rings)

    if multi:
        body = _varint(len(polygons)) + b"".join(polygon_bytes(p) for p in polygons)
        type_id = _TYPE_MULTIPOLYGON
    else:
        body = polygon_bytes(polygons[0])
        type_id = _TYPE_POLYGON
    header = type_id | ((_zigzag(precision) & 0x0F) << 4)
    return bytes([header, 0]) + body


def to_hex(polygons: Sequence[Polygon], precision: int = 6, multi: bool = True) -> str:
    return encode(polygons, precision, multi).hex()


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def decode(data: bytes) -> list[list[list[tuple[float, float]]]]:
    """Décodeur de contrôle (tests) : renvoie `[polygone][anneau][(x, y), …]`, anneaux refermés."""
    type_id = data[0] & 0x0F
    zz = data[0] >> 4
    scale = 10 ** ((zz >> 1) ^ -(zz & 1))
    if data[1] != 0:
        raise ValueError("métadonnées TWKB non gérées")
    state = [0, 0]

    def unzigzag(n: int) -> int:
        return (n >> 1) ^ -(n & 1)

    def read_polygon(pos: int):
        nrings, pos = _read_varint(data, pos)
        rings = []
        for _ in range(nrings):
            count, pos = _read_varint(data, pos)
            ring = []
            for _ in range(count):
                dx, pos = _read_varint(data, pos)
                dy, pos = _read_varint(data, pos)
                state[0] += unzigzag(dx)
                state[1] += unzigzag(dy)
                ring.append((state[0] / scale, state[1] / scale))
            ring.append(ring[0])
            rings.append(ring)
        return rings, pos

    if type_id == _TYPE_POLYGON:
        rings, _ = read_polygon(2)
        return [rings]
    count, pos = _read_varint(data, 2)
    polygons = []
    for _ in range(count):
        rings, pos = read_polygon(pos)
        polygons.append(rings)
    return polygons
