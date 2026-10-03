// Adapte le contour d'emprise à la taille acceptée par le service — équivalent de
// `gpf_extraction/core/extent_fit.py`. Fonctions pures, testées sous Node.
//
// Constaté en conditions réelles : le contour précis de la Guadeloupe (archipel, côte très
// découpée) donnait une requête de 6,8 Mo — le contour est recopié dans le filtre de *chaque*
// table — et le service répondait HTTP 500, alors que la même extraction avec une bbox passait.
//
// Stratégie « automatique », du plus fidèle au plus léger :
//   1. contour précis, s'il tient dans le budget de sommets ;
//   2. contour simplifié (Douglas-Peucker) avec une tolérance croissante, plafonnée ;
//   3. rectangles englobants (un par groupe de parties proches) : emprise entièrement couverte,
//      et plus lourde seulement de quelques dizaines de sommets ;
//   4. rectangle unique (bbox).
// Les étapes 3 et 4 sont des sur-ensembles de l'emprise (on récupère un peu plus de données,
// jamais moins). L'étape 2, elle, peut rogner la côte de quelques mètres, d'où sa tolérance bornée.

import { geometryBounds } from "./geo.js";

export const FIT_MODES = ["auto", "precise", "envelopes", "bbox"];

// Tolérances de simplification essayées (mètres), de la plus fine à la plus grossière.
export const TOLERANCES_M = [10, 25, 50, 100, 250];

const METERS_PER_DEGREE = 111320;
const RECT_STEPS = 4; // segments par côté d'un rectangle englobant (il se reprojette ensuite)

const polygonsOf = (geom) =>
  geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];

export function countVertices(geom) {
  let n = 0;
  for (const poly of polygonsOf(geom)) for (const ring of poly) n += ring.length;
  return n;
}

// ---------------------------------------------------------------- Simplification
// Distance d'un point à un segment, dans l'espace où x est déjà mis à l'échelle du cosinus de
// la latitude (sinon un degré de longitude pèserait autant qu'un degré de latitude).
function segmentDistance(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

// Douglas-Peucker itératif (une côte peut compter des centaines de milliers de sommets : pas de récursion).
function douglasPeucker(points, tolerance) {
  const n = points.length;
  if (n < 3) return points.slice();
  const keep = new Uint8Array(n);
  keep[0] = keep[n - 1] = 1;
  const stack = [[0, n - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let max = -1;
    let index = -1;
    for (let i = a + 1; i < b; i++) {
      const d = segmentDistance(points[i], points[a], points[b]);
      if (d > max) { max = d; index = i; }
    }
    if (max > tolerance) {
      keep[index] = 1;
      stack.push([a, index], [index, b]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

// Anneau fermé : coupé au point le plus éloigné du départ pour avoir deux chaînes ouvertes.
// `null` si l'anneau s'effondre (moins de 3 sommets distincts).
function simplifyRing(ring, tolerance, k) {
  const scaled = ring.map(([x, y]) => [x * k, y]);
  let far = 0;
  let farDist = -1;
  for (let i = 1; i < scaled.length - 1; i++) {
    const d = Math.hypot(scaled[i][0] - scaled[0][0], scaled[i][1] - scaled[0][1]);
    if (d > farDist) { farDist = d; far = i; }
  }
  if (far === 0) return null;
  const first = douglasPeucker(scaled.slice(0, far + 1), tolerance);
  const second = douglasPeucker(scaled.slice(far), tolerance);
  const out = first.concat(second.slice(1));
  return out.length >= 4 ? out.map(([x, y]) => [x / k, y]) : null;
}

const rectRing = ([x0, y0, x1, y1]) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];

function ringBounds(ring) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of ring) {
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}

// Simplifie un (Multi)Polygone en EPSG:4326 avec une tolérance en mètres. Un îlot qui
// s'effondre est remplacé par son rectangle englobant, un trou qui s'effondre est supprimé :
// dans les deux cas l'emprise ne fait que s'agrandir.
export function simplifyGeometry(geom, toleranceM) {
  const bounds = geometryBounds(geom);
  if (!bounds) return geom;
  const k = Math.cos((((bounds[1] + bounds[3]) / 2) * Math.PI) / 180) || 1;
  const tolerance = toleranceM / METERS_PER_DEGREE;
  const polygon = (poly) => {
    const [outer, ...holes] = poly;
    const simpleOuter = simplifyRing(outer, tolerance, k);
    if (!simpleOuter) return [rectRing(ringBounds(outer))];
    return [simpleOuter, ...holes.map((h) => simplifyRing(h, tolerance, k)).filter(Boolean)];
  };
  return geom.type === "Polygon"
    ? { type: "Polygon", coordinates: polygon(geom.coordinates) }
    : { type: "MultiPolygon", coordinates: geom.coordinates.map(polygon) };
}

// ---------------------------------------------------------------- Rectangles englobants
const unionRect = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
const rectArea = (r) => (r[2] - r[0]) * (r[3] - r[1]);
const overlaps = (a, b) => a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];

// Regroupe des rectangles : ceux qui se touchent fusionnent toujours ; deux rectangles
// voisins fusionnent si leur union ne gaspille pas trop de surface (`ratio`) ; au-delà de
// `maxRects`, on fusionne de force la paire qui gaspille le moins.
export function clusterRects(rects, { maxRects = 12, ratio = 2 } = {}) {
  let list = rects.map((r) => r.slice());
  // Garde-fou de coût : beaucoup de petites parties (îlots) → on les rattache d'abord aux plus grandes.
  const SEEDS = 150;
  if (list.length > SEEDS) {
    list.sort((a, b) => rectArea(b) - rectArea(a));
    const seeds = list.slice(0, SEEDS);
    for (const small of list.slice(SEEDS)) {
      let best = 0;
      let bestWaste = Infinity;
      seeds.forEach((s, i) => {
        const waste = rectArea(unionRect(s, small)) - rectArea(s);
        if (waste < bestWaste) { bestWaste = waste; best = i; }
      });
      seeds[best] = unionRect(seeds[best], small);
    }
    list = seeds;
  }
  for (;;) {
    let best = null;
    let bestScore = Infinity;
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const u = unionRect(list[i], list[j]);
        const waste = rectArea(u) - rectArea(list[i]) - rectArea(list[j]);
        const touching = overlaps(list[i], list[j]);
        const close = rectArea(u) <= ratio * (rectArea(list[i]) + rectArea(list[j]));
        if (!touching && !close && list.length <= maxRects) continue;
        const score = touching ? -Infinity : waste;
        if (score < bestScore || best === null) { bestScore = score; best = [i, j, u]; }
      }
    }
    if (!best) return list;
    const [i, j, u] = best;
    list = list.filter((_, index) => index !== i && index !== j);
    list.push(u);
  }
}

// Rectangle dont les côtés sont découpés en `steps` segments : une fois reprojeté (Lambert,
// UTM…), un rectangle en degrés n'est plus un rectangle, ses côtés se courbent.
function densifiedRect([x0, y0, x1, y1], steps) {
  const ring = [];
  const lerp = (a, b, t) => a + (b - a) * t;
  for (let i = 0; i < steps; i++) ring.push([lerp(x0, x1, i / steps), y0]);
  for (let i = 0; i < steps; i++) ring.push([x1, lerp(y0, y1, i / steps)]);
  for (let i = 0; i < steps; i++) ring.push([lerp(x1, x0, i / steps), y1]);
  for (let i = 0; i < steps; i++) ring.push([x0, lerp(y1, y0, i / steps)]);
  ring.push(ring[0]);
  return ring;
}

export function envelopesOf(geom, maxRects = 12) {
  const rects = clusterRects(polygonsOf(geom).map((poly) => ringBounds(poly[0])), { maxRects });
  return rects;
}

// ---------------------------------------------------------------- Choix de la stratégie
/**
 * @param {object} geom   (Multi)Polygone GeoJSON en EPSG:4326
 * @param {{mode?: string, maxVertices?: number, maxRects?: number}} options
 * @returns {{kind: "precise"|"simplified"|"envelopes"|"bbox", geometry: object|null, vertices: number,
 *            originalVertices: number, toleranceM: number, rects: number}}
 *   `geometry` est null pour `bbox` : l'appelant utilise alors la bbox (ST_MakeEnvelope).
 */
export function fitExtent(geom, { mode = "auto", maxVertices = 5000, maxRects = 12 } = {}) {
  const originalVertices = countVertices(geom);
  const result = (kind, geometry, extra = {}) => ({
    kind, geometry, originalVertices, toleranceM: 0, rects: 0,
    vertices: geometry ? countVertices(geometry) : 5, ...extra,
  });
  if (mode === "bbox") return result("bbox", null);
  if (mode === "precise") return result("precise", geom);

  if (mode === "auto") {
    if (originalVertices <= maxVertices) return result("precise", geom);
    for (const toleranceM of TOLERANCES_M) {
      const simple = simplifyGeometry(geom, toleranceM);
      if (countVertices(simple) <= maxVertices) return result("simplified", simple, { toleranceM });
    }
  }

  // « envelopes », ou repli de l'automatique quand même 250 m ne suffit pas.
  const limit = Math.max(1, Math.min(maxRects, Math.floor(maxVertices / (RECT_STEPS * 4 + 1))));
  const rects = envelopesOf(geom, limit);
  if (rects.length === 1) return result("bbox", null, { rects: 1 });
  const coordinates = rects.map((r) => [densifiedRect(r, RECT_STEPS)]);
  const envelopes = { type: "MultiPolygon", coordinates };
  return result("envelopes", envelopes, { rects: rects.length });
}

// Budget de sommets par filtre : le contour est recopié dans le filtre de chaque table, pour
// chaque prédicat. `maxBytes` / (tables × prédicats × octets par sommet), borné.
export function vertexBudget({ tables, predicates = 1, maxBytes = 1_000_000, bytesPerVertex = 22 }) {
  const copies = Math.max(1, tables) * Math.max(1, predicates);
  return Math.max(100, Math.min(50000, Math.floor(maxBytes / (copies * bytesPerVertex))));
}

const fmtInt = (n) => n.toLocaleString("fr-FR");

export function describeFit(fit) {
  switch (fit.kind) {
    case "precise":
      return `contour précis (${fmtInt(fit.vertices)} sommets)`;
    case "simplified":
      return `contour simplifié à ${fit.toleranceM} m (${fmtInt(fit.vertices)} sommets au lieu de ${fmtInt(fit.originalVertices)})`;
    case "envelopes":
      return `${fit.rects} rectangles englobants (au lieu de ${fmtInt(fit.originalVertices)} sommets)`;
    default:
      return "rectangle englobant unique";
  }
}
