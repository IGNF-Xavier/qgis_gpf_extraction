import test from "node:test";
import assert from "node:assert/strict";
import { effectivePredicates, reductionNote } from "../js/predicates.js";
import { FAITHFUL_MAX_TOLERANCE_M, MAX_BATCHES, isFaithful, planBatches, splitEvenly } from "../js/batch.js";
import { buildRelations, tableFilter } from "../js/builder.js";
import { fitExtent } from "../js/extent-fit.js";

const table = { name: "t", attributes: { fid: "integer", geom: "geometry" }, geometryAttribute: "geom" };

test("prédicats : Intersects absorbe les prédicats qui l'impliquent, sauf avec Disjoint", () => {
  assert.deepEqual(effectivePredicates(["Intersects", "Contains"]), ["Intersects"]);
  assert.deepEqual(effectivePredicates(["Contains", "Intersects", "Within", "Touches", "Crosses", "Overlaps", "Equals"]), ["Intersects"]);
  assert.deepEqual(effectivePredicates(["Contains", "Within"]), ["Contains", "Within"]); // sans Intersects : rien à réduire
  assert.deepEqual(effectivePredicates(["Intersects", "Disjoint"]), ["Intersects", "Disjoint"]);
  assert.deepEqual(effectivePredicates([]), ["Intersects"]);
  assert.deepEqual(effectivePredicates(["Disjoint", "Disjoint"]), ["Disjoint"]);
});

test("prédicats : la note explique ce qui a été retiré", () => {
  assert.equal(reductionNote(["Intersects"]), "");
  assert.match(reductionNote(["Intersects", "Contains", "Within"]), /^Contains, Within déjà inclus dans Intersects/);
  assert.equal(reductionNote(["Contains", "Within"]), "");
});

test("filtre : Intersects + Contains n'envoie (et ne recopie) qu'un seul prédicat", () => {
  const extent = { srid: 4326, bbox: [2, 48, 3, 49] };
  assert.equal(tableFilter(table, extent, ["Intersects", "Contains"]), "ST_Intersects(geom, ST_MakeEnvelope(2, 48, 3, 49, 4326))");
  assert.equal(
    tableFilter(table, extent, ["Contains", "Within"]),
    "(ST_Contains(geom, ST_MakeEnvelope(2, 48, 3, 49, 4326)) OR ST_Within(geom, ST_MakeEnvelope(2, 48, 3, 49, 4326)))",
  );
  const geometry = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
  const both = JSON.stringify(buildRelations([table], { srid: 4326, geometry, encoding: "twkb" }, ["Intersects", "Contains"]));
  const one = JSON.stringify(buildRelations([table], { srid: 4326, geometry, encoding: "twkb" }, ["Intersects"]));
  assert.equal(both, one);
});

test("lots : fidélité, planification et répartition", () => {
  assert.ok(isFaithful(null));
  assert.ok(isFaithful({ kind: "precise" }));
  assert.ok(isFaithful({ kind: "simplified", toleranceM: FAITHFUL_MAX_TOLERANCE_M }));
  assert.ok(!isFaithful({ kind: "simplified", toleranceM: FAITHFUL_MAX_TOLERANCE_M + 1 }));
  assert.ok(!isFaithful({ kind: "envelopes" }));
  assert.ok(!isFaithful({ kind: "bbox" }));

  // le contour est fidèle jusqu'à 10 tables par requête
  const fitFor = (n) => (n <= 10 ? { kind: "simplified", toleranceM: 25 } : { kind: "bbox" });
  assert.equal(planBatches(8, fitFor), 1); // une seule requête suffit
  assert.equal(planBatches(1, () => ({ kind: "bbox" })), 1); // rien à découper
  assert.equal(planBatches(25, fitFor), 3); // 3 lots de 9, 8, 8
  assert.equal(planBatches(59, fitFor), 6); // 6 lots de 10, 10, 10, 10, 10, 9
  assert.equal(planBatches(500, fitFor), 1); // plus de MAX_BATCHES lots nécessaires : on ne découpe pas
  assert.ok(MAX_BATCHES >= 6);
  assert.equal(planBatches(30, () => ({ kind: "bbox" })), 1); // même un lot d'une table ne suffit pas
  assert.equal(planBatches(5, () => null), 1); // pas de contour (rectangle) : jamais de découpage

  assert.deepEqual(splitEvenly([1, 2, 3, 4, 5, 6, 7], 3), [[1, 2, 3], [4, 5], [6, 7]]);
  assert.deepEqual(splitEvenly([1, 2], 5), [[1], [2]]);
  assert.deepEqual(splitEvenly([], 3), [[]]);
});

test("ajustement d'après la taille encodée : le budget en octets remplace l'estimation par sommet", () => {
  const ring = [];
  for (let i = 0; i < 3000; i++) {
    const a = (2 * Math.PI * i) / 3000;
    ring.push([-61.5 + 0.2 * Math.cos(a) * (1 + 0.004 * Math.sin(30 * a)), 16.2 + 0.2 * Math.sin(a)]);
  }
  ring.push(ring[0]);
  const geometry = { type: "Polygon", coordinates: [ring] };
  // « taille » factice : 10 octets par sommet
  const sizeOf = (geom) => geom.coordinates.reduce((n, poly) => n + (Array.isArray(poly[0][0]) ? poly.reduce((m, r) => m + r.length, 0) : poly.length), 0) * 10;
  const cache = new Map();
  const roomy = fitExtent(geometry, { maxBytes: 100_000, sizeOf, cache });
  assert.equal(roomy.kind, "precise");
  assert.ok(roomy.encodedBytes > 0 && roomy.encodedBytes <= 100_000);
  const tight = fitExtent(geometry, { maxBytes: 8_000, sizeOf, cache });
  assert.equal(tight.kind, "simplified");
  assert.ok(tight.encodedBytes <= 8_000, `taille ${tight.encodedBytes}`);
  assert.ok(tight.toleranceM >= 10);
  // le cache est réutilisé : un second appel au même budget renvoie le même contour sans le recalculer
  assert.equal(fitExtent(geometry, { maxBytes: 8_000, sizeOf, cache }).geometry, tight.geometry);
  // budget minuscule : on retombe sur la bbox (un seul groupe de rectangles)
  assert.equal(fitExtent(geometry, { maxBytes: 50, sizeOf, cache }).kind, "bbox");
});
