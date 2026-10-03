import test from "node:test";
import assert from "node:assert/strict";
import {
  findDescribedByUrl,
  isFailed,
  isRunning,
  isSuccessful,
  normalizeInputs,
  normalizeOutputIds,
  parseAtomEntries,
  parseProcessDetails,
  parseStoredData,
} from "../js/models.js";

test("normalizeInputs : liste où le title fait office d'identifiant", () => {
  const fields = normalizeInputs([
    { title: "compression", schema: { type: "string", enum: ["7zip"] }, minOccurs: 0 },
    { title: "relations", description: "tables", minOccurs: 1 },
    { title: "Durée de rétention", schema: { type: "integer" }, minOccurs: 0 },
  ]);
  assert.deepEqual(fields.map((f) => f.id), ["compression", "relations", "lifetime"]);
  assert.equal(fields[0].required, false);
  assert.equal(fields[1].required, true);
});

test("normalizeInputs : dictionnaire {id: schéma}", () => {
  const fields = normalizeInputs({ format: { title: "Format", schema: { enum: ["GPKG"] }, minOccurs: 1 } });
  assert.equal(fields[0].id, "format");
  assert.deepEqual(fields[0].schema.enum, ["GPKG"]);
});

test("normalizeOutputIds et describedby", () => {
  assert.deepEqual(normalizeOutputIds({ logs: {}, jobName: {} }), ["logs", "jobName"]);
  assert.equal(findDescribedByUrl([{ rel: "self", href: "a" }, { rel: "describedby", href: "https://x/y" }]), "https://x/y");
  assert.equal(findDescribedByUrl(undefined), null);
  assert.deepEqual(parseProcessDetails({ id: "p", inputs: [] }).outputIds, ["logs", "summary", "extractedData"]);
});

test("parseStoredData : colonne géométrique et SRS natif", () => {
  const data = parseStoredData({
    _id: "abc",
    srs: "EPSG:4326",
    type_infos: {
      relations: [
        { name: "departement", attributes: { fid: "integer", geometrie: "geometry(MultiPolygon,4326)" } },
        { name: "sans_geometrie", attributes: { fid: "integer" } },
        { attributes: {} },
      ],
    },
  });
  assert.equal(data.srs, "EPSG:4326");
  assert.equal(data.tables.length, 2);
  assert.equal(data.tables[0].geometryAttribute, "geometrie");
  assert.equal(data.tables[1].geometryAttribute, null);
});

test("statuts de job", () => {
  assert.ok(isRunning("running"));
  assert.ok(isSuccessful("successful"));
  assert.ok(isFailed("dismissed"));
  assert.ok(!isRunning("successful"));
});

test("parseAtomEntries : fichiers téléchargeables, esperluettes et métadonnées", () => {
  const xml = `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:gpf_dl="x">
    <entry><title>m</title><link href="https://h/download/e/data/extraction.json" type="application/json"/>
      <gpf_dl:mime_type>application/json</gpf_dl:mime_type></entry>
    <entry><link type="application/geopackage+sqlite3" href="https://h/download/e/data/export/data.gpkg?a=1&amp;b=2"/>
      <gpf_dl:mime_type>application/geopackage+sqlite3</gpf_dl:mime_type></entry></feed>`;
  const entries = parseAtomEntries(xml);
  assert.equal(entries.length, 2);
  assert.equal(entries[0].isMetadata, true);
  assert.equal(entries[1].isMetadata, false);
  assert.equal(entries[1].filename, "data.gpkg");
  assert.equal(entries[1].href, "https://h/download/e/data/export/data.gpkg?a=1&b=2");
});
