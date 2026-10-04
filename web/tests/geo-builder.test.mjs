import test from "node:test";
import assert from "node:assert/strict";
import {
  bboxToPolygon,
  domCoverageWarning,
  geojsonToWkt,
  geometryBounds,
  loadPresets,
  makeTransformFrom4326,
  reprojectGeometry,
  searchAdmin,
  srid,
  transformBbox,
} from "../js/geo.js";
import { buildBody, buildRelations, curlCommand, extentExpression, missingForLaunch, tableFilter } from "../js/builder.js";

const table = { name: "departement", attributes: { fid: "integer", geometrie: "geometry(MultiPolygon,4326)", nom: "text" }, geometryAttribute: "geometrie" };

test("WKT : Polygon et MultiPolygon", () => {
  assert.equal(geojsonToWkt({ type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }), "POLYGON((0 0,1 0,1 1,0 0))");
  assert.equal(
    geojsonToWkt({ type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] }),
    "MULTIPOLYGON(((0 0,1 0,1 1,0 0)))",
  );
  assert.equal(geojsonToWkt({ type: "Point", coordinates: [0, 0] }), null);
});

test("bornes d'une géométrie", () => {
  assert.deepEqual(geometryBounds(bboxToPolygon([2, 47, 3, 48])), [2, 47, 3, 48]);
});

test("filtre : un seul prédicat sans parenthèse, plusieurs combinés en OU", () => {
  const extent = { srid: 4326, bbox: [2, 48, 3, 49] };
  assert.equal(tableFilter(table, extent, ["Intersects"]), "ST_Intersects(geometrie, ST_MakeEnvelope(2, 48, 3, 49, 4326))");
  // Contains et Within n'impliquent pas l'un l'autre : ils restent combinés en OU
  assert.equal(
    tableFilter(table, extent, ["Contains", "Within"]),
    "(ST_Contains(geometrie, ST_MakeEnvelope(2, 48, 3, 49, 4326)) OR ST_Within(geometrie, ST_MakeEnvelope(2, 48, 3, 49, 4326)))",
  );
  // Intersects absorbe Contains : même résultat, une seule copie de l'emprise
  assert.equal(tableFilter(table, extent, ["Intersects", "Contains"]), "ST_Intersects(geometrie, ST_MakeEnvelope(2, 48, 3, 49, 4326))");
  assert.match(tableFilter(table, extent, []), /^ST_Intersects/); // jamais de filtre vide
});

test("le vrai contour prime sur la bbox (ST_GeomFromText, pas ST_MakeEnvelope)", () => {
  const expr = extentExpression({ srid: 4326, geometry: bboxToPolygon([0, 0, 1, 1]), bbox: [0, 0, 1, 1] });
  assert.match(expr, /^ST_GeomFromText\('POLYGON/);
  assert.doesNotMatch(expr, /ST_MakeEnvelope/);
});

test("table sans géométrie : pas de filtre ; sans emprise : pas de filtre", () => {
  const noGeom = { name: "t", attributes: { fid: "integer" }, geometryAttribute: null };
  const relations = buildRelations([noGeom, table], { srid: 4326, bbox: [0, 0, 1, 1] }, ["Intersects"]);
  assert.equal(relations.t.filters, undefined);
  assert.ok(relations.departement.filters);
  assert.equal(buildRelations([table], null, ["Intersects"]).departement.filters, undefined);
});

test("reprojection : le filtre suit la SRID native, pas la projection de sortie", () => {
  const fakeProj4 = { defs: () => true, __call: null };
  const proj4 = Object.assign(
    () => ({ forward: ([x, y]) => [x * 1000, y * 1000] }),
    fakeProj4,
  );
  const forward = makeTransformFrom4326(proj4, "EPSG:2154");
  assert.deepEqual(forward([1, 2]), [1000, 2000]);
  assert.deepEqual(makeTransformFrom4326(proj4, "EPSG:4326")([1, 2]), [1, 2]);
  const moved = reprojectGeometry(bboxToPolygon([1, 1, 2, 2]), forward);
  assert.deepEqual(geometryBounds(moved), [1000, 1000, 2000, 2000]);
  assert.deepEqual(transformBbox([1, 1, 2, 2], forward), [1000, 1000, 2000, 2000]);
  assert.equal(srid("EPSG:2154"), 2154);
  assert.equal(srid(""), 4326);
});

test("projection inconnue : makeTransformFrom4326 renvoie null", () => {
  const proj4 = Object.assign(() => { throw new Error("inconnue"); }, { defs: () => true });
  assert.equal(makeTransformFrom4326(proj4, "EPSG:99999"), null);
});

test("corps de requête : jobName non demandé, valeurs vides omises", () => {
  const process = {
    inputs: [{ id: "relations" }, { id: "srs" }, { id: "format" }, { id: "append" }, { id: "lifetime" }, { id: "compression" }],
    outputIds: ["logs", "summary", "extractedData", "jobName"],
  };
  const body = buildBody(process, { srs: "EPSG:2154", format: "GPKG", append: true, lifetime: 0, compression: "" }, { departement: { attributes: [] } });
  assert.deepEqual(Object.keys(body.outputs), ["logs", "summary", "extractedData"]);
  assert.equal(body.inputs.srs, "EPSG:2154");
  assert.equal(body.inputs.append, true);
  assert.equal(body.inputs.lifetime, 0); // l'UI n'envoie pas 0 ; le builder ne filtre que vide/undefined
  assert.equal("compression" in body.inputs, false);
});

test("processus sans relations : l'emprise remplit le champ qui y ressemble, sinon bbox", () => {
  const bbox = [2, 48, 3, 49];
  const withField = buildBody({ inputs: [{ id: "emprise" }, { id: "format" }], outputIds: ["logs"] }, { format: "GPKG" }, {}, bbox);
  assert.deepEqual(withField.inputs.emprise, bbox);
  assert.equal(withField.inputs.bbox, undefined);
  const without = buildBody({ inputs: [{ id: "format" }], outputIds: ["logs"] }, { format: "GPKG" }, {}, bbox);
  assert.deepEqual(without.inputs.bbox, bbox);
  const withRelations = buildBody({ inputs: [{ id: "relations" }], outputIds: ["logs"] }, {}, { t: {} }, bbox);
  assert.equal(withRelations.inputs.bbox, undefined);
});

test("commande curl : jeton jamais écrit en clair", () => {
  const curl = curlCommand("https://x/execution", { a: "l'été" });
  assert.match(curl, /\$TOKEN/);
  assert.match(curl, /l'\\''été/);
});

test("missingForLaunch", () => {
  const ok = { authenticated: true, hasProcess: true, extent: {}, tablesCount: 2, hasRelationsField: true, srsSupported: true };
  assert.deepEqual(missingForLaunch(ok), []);
  assert.equal(missingForLaunch({ ...ok, authenticated: false, tablesCount: 0 }).length, 2);
});

test("avertissement DOM : seulement pour un DOM et un titre « hors DOM »", () => {
  const guadeloupe = { code: "971" };
  assert.match(domCoverageWarning("BDFORET - France entière (hors DOM)", guadeloupe), /ne pas couvrir les DOM/);
  assert.equal(domCoverageWarning("BDTOPO - France entière (dont DOM)", guadeloupe), "");
  assert.equal(domCoverageWarning("BDFORET (hors DOM)", { code: "76540" }), "");
  assert.equal(domCoverageWarning("GPU_EXTRACTION", guadeloupe), "");
});

const fakeFetch = (payload, ok = true) => async () => ({ ok, status: ok ? 200 : 500, json: async () => payload });

test("searchAdmin : filtre les EPCI, exige truegeometry, désambiguïse les communes", async () => {
  const geom = JSON.stringify(bboxToPolygon([0, 0, 1, 1]));
  const payload = {
    features: [
      { properties: { toponym: "Rouen", category: ["administratif", "commune"], depcode: ["76"], citycode: ["76540"], truegeometry: geom } },
      { properties: { toponym: "Métropole Rouen Normandie", category: ["administratif", "epci"], truegeometry: geom } },
      { properties: { toponym: "Rhône", category: ["administratif", "département"], citycode: ["69"], truegeometry: geom } },
      { properties: { toponym: "Sans contour", category: ["administratif", "commune"], depcode: ["01"] } },
    ],
  };
  const results = await searchAdmin("Rouen", fakeFetch(payload));
  assert.deepEqual(results.map((r) => r.label), ["Rouen (Commune 76)", "Rhône (Département)"]);
  assert.equal(results[0].code, "76540");
  assert.deepEqual(await searchAdmin("R", fakeFetch(payload)), []);
});

test("loadPresets : 6 préréglages, repli sur rectangle si le WFS échoue", async () => {
  const failing = async () => { throw new Error("réseau"); };
  const fallback = await loadPresets(failing);
  assert.equal(fallback.length, 6);
  assert.equal(fallback[0].label, "France métropolitaine (préréglage)");
  assert.ok(fallback.every((p) => geometryBounds(p.geometry)));
  const real = { type: "Polygon", coordinates: [[[1, 1], [2, 1], [2, 2], [1, 1]]] };
  const wfs = fakeFetch({ features: [{ properties: { code_insee: "971" }, geometry: real }] });
  const presets = await loadPresets(wfs);
  assert.deepEqual(presets.find((p) => p.code === "971").geometry, real);
  assert.notDeepEqual(presets.find((p) => p.code === "972").geometry, real);
});
