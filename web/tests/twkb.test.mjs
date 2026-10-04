import test from "node:test";
import assert from "node:assert/strict";
import { decodeTwkb, encodeTwkb, twkbHex } from "../js/twkb.js";
import { bboxToPolygon } from "../js/geo.js";
import { buildRelations, extentExpression } from "../js/builder.js";

const SQUARE = [[[-61.54, 16.23], [-61.52, 16.23], [-61.52, 16.25], [-61.54, 16.25], [-61.54, 16.23]]];
// Référence partagée avec tests/unit/test_twkb.py : les deux encodeurs doivent produire ces octets.
const SQUARE_HEX = "c600010104bf9ad83ae099bd0fc0b8020000c0b802bfb80200";

test("TWKB : en-tête et octets de référence identiques à l'encodeur Python", () => {
  const bytes = encodeTwkb([SQUARE]);
  assert.equal(bytes[0] & 0x0f, 6);
  assert.equal(bytes[0] >> 4, 12);
  assert.equal(bytes[1], 0);
  assert.equal(twkbHex([SQUARE]), SQUARE_HEX);
});

test("TWKB : Polygon, trous et multipolygone font l'aller-retour", () => {
  assert.deepEqual(decodeTwkb(encodeTwkb([SQUARE], 6, false)), [SQUARE]);
  const outer = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];
  const hole = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75], [0.25, 0.25]];
  const other = [[[10.5, -20.5], [11.5, -20.5], [11.5, -19.5], [10.5, -20.5]]];
  const geom = [[outer, hole], other];
  assert.deepEqual(decodeTwkb(encodeTwkb(geom)), geom);
});

test("TWKB : coordonnées projetées (au-delà de 2^31 en centimètres), arrondi à la précision", () => {
  const ring = [[[700000.123, 6600000.456], [700100.5, 6600000.456], [700100.5, 6600200.9], [700000.123, 6600000.456]]];
  assert.deepEqual(decodeTwkb(encodeTwkb([ring], 2))[0][0][0], [700000.12, 6600000.46]);
  assert.deepEqual(decodeTwkb(encodeTwkb([ring], 0))[0][0][0], [700000, 6600000]);
  assert.throws(() => encodeTwkb([ring], 8), RangeError);
});

test("filtre : TWKB en option, ST_SetSRID, précision réduite pour un contour simplifié", () => {
  const geometry = { type: "Polygon", coordinates: SQUARE };
  const precise = extentExpression({ srid: 4326, geometry, encoding: "twkb" });
  assert.match(precise, /^ST_SetSRID\(ST_GeomFromTWKB\(decode\('[0-9a-f]+','hex'\)\), 4326\)$/);
  // précision 5 (« coarse ») : en-tête 0xaX au lieu de 0xcX — zigzag(5) = 10
  assert.match(extentExpression({ srid: 4326, geometry, encoding: "twkb", coarse: true }), /decode\('a[0-9a-f]/);
  assert.match(precise, /decode\('c[0-9a-f]/);
  // sans encodage demandé : WKT, comme avant
  assert.match(extentExpression({ srid: 4326, geometry }), /^ST_GeomFromText\('POLYGON/);
  // projeté : 2 décimales (zigzag(2) = 4 → 0x4X), 0 si grossier (0x0X)
  const lambert = { type: "Polygon", coordinates: [[[700000, 6600000], [700100, 6600000], [700100, 6600100], [700000, 6600000]]] };
  assert.match(extentExpression({ srid: 2154, geometry: lambert, encoding: "twkb" }), /decode\('4[0-9a-f]/);
  assert.match(extentExpression({ srid: 2154, geometry: lambert, encoding: "twkb", coarse: true }), /decode\('0[0-9a-f]/);
});

test("filtre TWKB : bien plus léger que le WKT, une copie par table", () => {
  const ring = [];
  for (let i = 0; i < 20000; i++) {
    const a = (2 * Math.PI * i) / 20000;
    ring.push([-61.5 + 0.2 * Math.cos(a) * (1 + 0.01 * Math.sin(40 * a)), 16.2 + 0.2 * Math.sin(a)]);
  }
  ring.push(ring[0]);
  const geometry = { type: "Polygon", coordinates: [ring] };
  const tables = ["a", "b", "c"].map((name) => ({ name, attributes: { fid: "integer", geom: "geometry" }, geometryAttribute: "geom" }));
  const wkt = JSON.stringify(buildRelations(tables, { srid: 4326, geometry }, ["Intersects"])).length;
  const twkb = JSON.stringify(buildRelations(tables, { srid: 4326, geometry, encoding: "twkb" }, ["Intersects"])).length;
  assert.ok(twkb * 4 < wkt, `TWKB ${twkb} o contre WKT ${wkt} o`);
  assert.equal(JSON.stringify(buildRelations(tables, { srid: 4326, bbox: [0, 0, 1, 1], encoding: "twkb" }, ["Intersects"])).includes("ST_MakeEnvelope"), true);
  assert.ok(bboxToPolygon([0, 0, 1, 1]));
});
