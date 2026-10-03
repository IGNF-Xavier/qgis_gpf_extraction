import test from "node:test";
import assert from "node:assert/strict";
import { bboxToPolygon, geojsonToWkt, geometryBounds, wktDecimals } from "../js/geo.js";
import { buildRelations } from "../js/builder.js";
import { clusterRects, countVertices, describeFit, fitExtent, simplifyGeometry, vertexBudget } from "../js/extent-fit.js";

// Île à contour très découpé : cercle de rayon `r` degrés, bruité de ±2 % à haute fréquence.
function island(cx, cy, r, n) {
  const ring = [];
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n;
    const noise = 1 + 0.02 * Math.sin(a * 300) + 0.01 * Math.sin(a * 1700);
    ring.push([cx + r * noise * Math.cos(a), cy + r * noise * Math.sin(a)]);
  }
  ring.push(ring[0]);
  return [ring];
}
// Archipel type Guadeloupe : une grande île très détaillée et trois petites, éloignées.
const archipelago = () => ({
  type: "MultiPolygon",
  coordinates: [island(-61.5, 16.2, 0.25, 60000), island(-61.3, 15.95, 0.1, 5000), island(-62.6, 15.0, 0.03, 800), island(-60.2, 17.0, 0.04, 800)],
});

test("simplification : moins de sommets, écart borné par la tolérance", () => {
  const geom = archipelago();
  const simple = simplifyGeometry(geom, 50);
  assert.ok(countVertices(simple) < countVertices(geom) / 10);
  assert.equal(simple.coordinates.length, 4);
  // les bornes ne bougent que de quelques dizaines de mètres au plus (50 m ≈ 0,00045°)
  const [a, b] = [geometryBounds(geom), geometryBounds(simple)];
  a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 0.0006, `borne ${i}`));
  // chaque anneau reste fermé
  for (const poly of simple.coordinates) for (const ring of poly) assert.deepEqual(ring[0], ring[ring.length - 1]);
});

test("simplification : un îlot qui s'effondre devient son rectangle, un trou qui s'effondre disparaît", () => {
  const tiny = [[[0, 0], [0.00001, 0], [0.00001, 0.00001], [0, 0.00001], [0, 0]]];
  const out = simplifyGeometry({ type: "Polygon", coordinates: tiny }, 100);
  assert.equal(out.coordinates[0].length, 5); // rectangle englobant
  const big = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];
  const hole = [[0.5, 0.5], [0.50001, 0.5], [0.50001, 0.50001], [0.5, 0.50001], [0.5, 0.5]];
  const holed = simplifyGeometry({ type: "Polygon", coordinates: [big, hole] }, 100);
  assert.equal(holed.coordinates.length, 1);
});

test("auto : contour précis tant qu'il tient dans le budget", () => {
  const fit = fitExtent(bboxToPolygon([0, 0, 1, 1]), { maxVertices: 100 });
  assert.equal(fit.kind, "precise");
});

test("auto : simplifie quand le contour dépasse le budget", () => {
  const geom = archipelago();
  const fit = fitExtent(geom, { maxVertices: 8000 });
  assert.equal(fit.kind, "simplified");
  assert.ok(fit.toleranceM >= 10 && fit.toleranceM <= 250);
  assert.ok(fit.vertices <= 8000);
  assert.match(describeFit(fit), /simplifié à \d+ m/);
});

test("auto : rectangles englobants quand aucune simplification ne suffit", () => {
  const geom = archipelago();
  const fit = fitExtent(geom, { maxVertices: 120 });
  assert.equal(fit.kind, "envelopes");
  assert.ok(fit.rects >= 2 && fit.rects <= 4);
  assert.ok(fit.vertices <= 120);
  // sur-ensemble : les bornes de l'emprise sont couvertes
  const [a, b] = [geometryBounds(geom), geometryBounds(fit.geometry)];
  assert.ok(b[0] <= a[0] && b[1] <= a[1] && b[2] >= a[2] && b[3] >= a[3]);
});

test("modes forcés : precise garde tout, bbox ne renvoie pas de géométrie, envelopes regroupe", () => {
  const geom = archipelago();
  assert.equal(fitExtent(geom, { mode: "precise", maxVertices: 10 }).geometry, geom);
  const bbox = fitExtent(geom, { mode: "bbox" });
  assert.equal(bbox.kind, "bbox");
  assert.equal(bbox.geometry, null);
  assert.equal(fitExtent(geom, { mode: "envelopes" }).kind, "envelopes");
});

test("un seul groupe de rectangles = bbox", () => {
  const fit = fitExtent({ type: "Polygon", coordinates: island(0, 0, 1, 50000) }, { maxVertices: 100 });
  assert.equal(fit.kind, "bbox");
});

test("regroupement : rectangles qui se touchent fusionnés, îles lointaines séparées", () => {
  const near = clusterRects([[0, 0, 1, 1], [0.5, 0.5, 2, 2]], { maxRects: 12 });
  assert.deepEqual(near, [[0, 0, 2, 2]]);
  const far = clusterRects([[0, 0, 1, 1], [50, 50, 51, 51]], { maxRects: 12 });
  assert.equal(far.length, 2);
  const forced = clusterRects([[0, 0, 1, 1], [50, 50, 51, 51], [100, 0, 101, 1]], { maxRects: 2 });
  assert.equal(forced.length, 2);
});

test("regroupement : des centaines d'îlots restent traitables et bornés", () => {
  const rects = Array.from({ length: 600 }, (_, i) => [(i % 30) * 0.5, Math.floor(i / 30) * 0.5, (i % 30) * 0.5 + 0.01, Math.floor(i / 30) * 0.5 + 0.01]);
  const out = clusterRects(rects, { maxRects: 12 });
  assert.ok(out.length <= 12);
});

test("budget de sommets : décroît avec le nombre de tables et de prédicats, borné", () => {
  assert.ok(vertexBudget({ tables: 3 }) > vertexBudget({ tables: 59 }));
  assert.ok(vertexBudget({ tables: 3, predicates: 2 }) < vertexBudget({ tables: 3, predicates: 1 }));
  assert.equal(vertexBudget({ tables: 5000 }), 100);
  assert.equal(vertexBudget({ tables: 0 }) <= 50000, true);
});

test("la requête Guadeloupe à 3 tables reste sous le budget en mode automatique", () => {
  const table = (name) => ({ name, attributes: { fid: "integer", geom: "geometry" }, geometryAttribute: "geom" });
  const tables = ["a", "b", "c"].map(table);
  const geom = archipelago();
  const maxVertices = vertexBudget({ tables: 3, predicates: 1 });
  const fit = fitExtent(geom, { maxVertices });
  const body = JSON.stringify(buildRelations(tables, { srid: 4326, geometry: fit.geometry, bbox: geometryBounds(fit.geometry) }, ["Intersects"]));
  const raw = JSON.stringify(buildRelations(tables, { srid: 4326, geometry: geom, bbox: geometryBounds(geom) }, ["Intersects"]));
  assert.ok(body.length < 100_000, `corps simplifié : ${body.length} octets`);
  assert.ok(raw.length > 5 * body.length);
});

test("WKT : moins de décimales, 6 en degrés et 2 en mètres", () => {
  assert.equal(geojsonToWkt({ type: "Polygon", coordinates: [[[0.123456789, 1.987654321], [1, 1], [1, 2], [0.123456789, 1.987654321]]] }, 6),
    "POLYGON((0.123457 1.987654,1 1,1 2,0.123457 1.987654))");
  assert.equal(wktDecimals(bboxToPolygon([-61, 15, -60, 16])), 6);
  assert.equal(wktDecimals(bboxToPolygon([600000, 1700000, 700000, 1800000])), 2);
});
