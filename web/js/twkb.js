// Encodage TWKB (Tiny WKB) d'un (Multi)Polygone — équivalent de `gpf_extraction/core/twkb.py`.
//
// Le contour est recopié dans le filtre de chaque table de la requête ; en WKT il pèse ~21 octets
// par sommet. Le TWKB stocke des entiers en différences (zigzag + varint), écrits en hexadécimal :
// ~4,5 octets par sommet à 10 cm de précision sur un contour détaillé (÷ 4,6 mesuré sur la
// Guadeloupe). Côté serveur : ST_SetSRID(ST_GeomFromTWKB(decode('…', 'hex')), srid) — le TWKB ne
// porte pas de SRID. Vérifié en conditions réelles : le service d'extraction exécute cette fonction.
//
// Format : octet 1 = type (bas 4 bits : 3 polygone, 6 multipolygone) | précision en zigzag (haut
// 4 bits) ; octet 2 = métadonnées (0) ; puis nombre d'anneaux (varint) et, par anneau, nombre de
// points (varint) et points en différences entières. L'état du delta se poursuit d'un anneau et
// d'un polygone à l'autre. Le point de fermeture de chaque anneau est omis (PostGIS referme).
//
// Arithmétique (pas d'opérateurs binaires) : ils tronquent à 32 bits, or une coordonnée en
// centimètres dépasse 2^31.

const zigzag = (n) => (n >= 0 ? 2 * n : -2 * n - 1);

function pushVarint(out, n) {
  while (n >= 128) {
    out.push((n % 128) + 128);
    n = Math.floor(n / 128);
  }
  out.push(n);
}

/**
 * @param {Array} polygons  [polygone][anneau][[x, y], …], anneaux fermés
 * @param {number} precision  décimales conservées (-8 à 7) ; 6 en degrés ≈ 10 cm
 * @param {boolean} multi  MultiPolygon si vrai, sinon Polygon (un seul polygone attendu)
 * @returns {number[]} octets
 */
export function encodeTwkb(polygons, precision = 6, multi = true) {
  if (precision < -8 || precision > 7) throw new RangeError("précision TWKB hors de -8..7");
  const scale = 10 ** precision;
  const out = [(multi ? 6 : 3) | ((zigzag(precision) & 0x0f) << 4), 0];
  let px = 0;
  let py = 0;
  const polygon = (rings) => {
    pushVarint(out, rings.length);
    for (const ring of rings) {
      const points = ring.slice(0, -1); // le point de fermeture est omis
      pushVarint(out, points.length);
      for (const [x, y] of points) {
        const ix = Math.round(x * scale);
        const iy = Math.round(y * scale);
        pushVarint(out, zigzag(ix - px));
        pushVarint(out, zigzag(iy - py));
        px = ix;
        py = iy;
      }
    }
  };
  if (multi) {
    pushVarint(out, polygons.length);
    for (const poly of polygons) polygon(poly);
  } else {
    polygon(polygons[0]);
  }
  return out;
}

export const twkbHex = (polygons, precision = 6, multi = true) =>
  encodeTwkb(polygons, precision, multi).map((b) => b.toString(16).padStart(2, "0")).join("");

/** Décodeur de contrôle (tests) : renvoie [polygone][anneau][[x, y], …], anneaux refermés. */
export function decodeTwkb(bytes) {
  const typeId = bytes[0] & 0x0f;
  const zz = bytes[0] >> 4;
  const scale = 10 ** ((zz >> 1) ^ -(zz & 1));
  if (bytes[1] !== 0) throw new Error("métadonnées TWKB non gérées");
  let pos = 2;
  let px = 0;
  let py = 0;
  const varint = () => {
    let result = 0;
    let mul = 1;
    for (;;) {
      const b = bytes[pos++];
      result += (b & 0x7f) * mul;
      if (!(b & 0x80)) return result;
      mul *= 128;
    }
  };
  const unzigzag = (n) => (n % 2 === 0 ? n / 2 : -(n + 1) / 2);
  const polygon = () => {
    const rings = [];
    for (let r = varint(); r > 0; r--) {
      const ring = [];
      for (let n = varint(); n > 0; n--) {
        px += unzigzag(varint());
        py += unzigzag(varint());
        ring.push([px / scale, py / scale]);
      }
      ring.push(ring[0]);
      rings.push(ring);
    }
    return rings;
  };
  if (typeId === 3) return [polygon()];
  const polygons = [];
  for (let n = varint(); n > 0; n--) polygons.push(polygon());
  return polygons;
}
