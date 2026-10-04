// Construction du corps de requête d'extraction — équivalent de
// `wdg_relations_builder.py` / `wdg_process_params.py`. Fonctions pures, testées sous Node.

import { geojsonToWkt, wktDecimals } from "./geo.js";
import { effectivePredicates } from "./predicates.js";
import { twkbHex } from "./twkb.js";
import { OUTPUTS_NOT_REQUESTED, fieldDefault, fieldEnum, fieldType } from "./models.js";

export const PREDICATE_SQL = {
  Intersects: "ST_Intersects",
  Contains: "ST_Contains",
  Within: "ST_Within",
  Disjoint: "ST_Disjoint",
  Touches: "ST_Touches",
  Crosses: "ST_Crosses",
  Overlaps: "ST_Overlaps",
  Equals: "ST_Equals",
};
export const DEFAULT_PREDICATES = ["Intersects"];

// `extent` est exprimé dans la SRID *native de la donnée stockée* (jamais dans la
// projection de sortie choisie : le filtre est évalué contre la colonne géométrique
// source, `srs` ne reprojette que le résultat — les confondre renvoie silencieusement
// zéro entité, constaté en conditions réelles).
//   extent = { srid, geometry?: GeoJSON, bbox?: [xmin, ymin, xmax, ymax],
//              encoding?: "wkt" (défaut) | "twkb", coarse?: boolean }
// `coarse` : contour simplifié puis élargi d'au moins 10 m, dont on peut arrondir les coordonnées
// d'un cran de plus en TWKB (≤ 1 m, bien en deçà de l'élargissement).
export function extentExpression(extent) {
  if (!extent) return null;
  if (extent.geometry) {
    const decimals = wktDecimals(extent.geometry);
    if (extent.encoding === "twkb") {
      const polygons = extent.geometry.type === "Polygon" ? [extent.geometry.coordinates] : extent.geometry.coordinates;
      const geographic = decimals === 6;
      const precision = geographic ? (extent.coarse ? 5 : 6) : extent.coarse ? 0 : 2;
      // Le TWKB ne porte pas de SRID : ST_SetSRID.
      return `ST_SetSRID(ST_GeomFromTWKB(decode('${twkbHex(polygons, precision)}','hex')), ${extent.srid})`;
    }
    const wkt = geojsonToWkt(extent.geometry, decimals);
    if (wkt) return `ST_GeomFromText('${wkt}', ${extent.srid})`;
  }
  if (extent.bbox) {
    const [x0, y0, x1, y1] = extent.bbox;
    return `ST_MakeEnvelope(${x0}, ${y0}, ${x1}, ${y1}, ${extent.srid})`;
  }
  return null;
}

// Un seul prédicat → sans parenthèse superflue ; plusieurs → combinés en OU.
export function tableFilter(table, extent, predicates) {
  const expr = extentExpression(extent);
  if (!table.geometryAttribute || !expr) return null;
  // `Intersects OR Contains` = `Intersects` : on n'envoie (et ne recopie) que ce qui change le résultat.
  const chosen = effectivePredicates(predicates && predicates.length ? predicates : DEFAULT_PREDICATES);
  const clauses = chosen.map((p) => `${PREDICATE_SQL[p]}(${table.geometryAttribute}, ${expr})`);
  return clauses.length === 1 ? clauses[0] : `(${clauses.join(" OR ")})`;
}

export function buildRelations(tables, extent, predicates) {
  const relations = {};
  for (const table of tables) {
    const entry = { attributes: Object.keys(table.attributes) };
    const filter = tableFilter(table, extent, predicates);
    if (filter) entry.filters = filter;
    relations[table.name] = entry;
  }
  return relations;
}

// Fragments de nom de champ évoquant une emprise (pour les processus sans `relations`).
const EXTENT_FIELD_HINTS = ["bbox", "emprise", "extent", "envelope", "footprint", "zone"];
const looksLikeExtentField = (id) => EXTENT_FIELD_HINTS.some((hint) => id.toLowerCase().includes(hint));

// `values` : valeurs saisies pour les champs génériques (clé = id d'input) ; une valeur
// `undefined`/vide est omise. `relations` : déjà construit (cf. `buildRelations`).
// `fallbackBbox` ([xmin, ymin, xmax, ymax] en EPSG:4326) : pour un processus sans input
// `relations`, renseigne le champ qui ressemble à une emprise, ou à défaut `bbox` — à
// corriger via le mode JSON avancé si le processus attend une autre forme.
export function buildBody(process, values, relations, fallbackBbox = null) {
  const inputs = {};
  let extentFilled = false;
  for (const field of process.inputs) {
    if (field.id === "relations") {
      inputs.relations = relations;
      extentFilled = true; // l'emprise est déjà injectée table par table
      continue;
    }
    let value = values[field.id];
    if ((value === undefined || value === null || value === "") && fallbackBbox && looksLikeExtentField(field.id)) {
      value = fallbackBbox;
    }
    if (value === undefined || value === null || value === "") continue;
    if (looksLikeExtentField(field.id)) extentFilled = true;
    inputs[field.id] = value;
  }
  if (!extentFilled && fallbackBbox && inputs.bbox === undefined) inputs.bbox = fallbackBbox;
  const outputs = {};
  for (const id of process.outputIds) if (!OUTPUTS_NOT_REQUESTED.has(id)) outputs[id] = {};
  return { inputs, outputs };
}

// Valeur initiale d'un champ générique, selon son schéma (sans les cas particuliers
// gérés par l'UI : format, append, srs).
export function initialValue(field) {
  const def = fieldDefault(field);
  if (def !== undefined && def !== null) return def;
  const e = fieldEnum(field);
  if (e && field.required) return e[0];
  if (fieldType(field) === "boolean") return false;
  return undefined;
}

// Le format « GPKG » est le plus directement exploitable dans QGIS.
export function preferredEnumValue(options) {
  for (const preferred of ["GPKG", "GeoPackage", "ESRI SHAPEFILE", "GEOJSON"]) {
    const found = options.find((o) => String(o).toUpperCase() === preferred.toUpperCase());
    if (found !== undefined) return found;
  }
  return options[0];
}

export const isMultilayerFormat = (format) => ["GPKG", "PGDUMP"].includes(String(format || "").toUpperCase());

export function curlCommand(url, body) {
  const json = JSON.stringify(body).replace(/'/g, "'\\''");
  return (
    `curl -X POST '${url}' \\\n` +
    `  -H "Authorization: Bearer $TOKEN" \\\n` +
    `  -H "Content-Type: application/json" \\\n` +
    `  --data-binary '${json}'`
  );
}

// Pourquoi le bouton « Lancer » est inactif (liste vide = prêt).
export function missingForLaunch({ authenticated, hasProcess, extent, tablesCount, hasRelationsField, srsSupported }) {
  const missing = [];
  if (!authenticated) missing.push("Collez un jeton d'accès (section Connexion).");
  if (!extent) missing.push("Choisissez une emprise.");
  if (!hasProcess) missing.push("Choisissez un produit.");
  if (hasProcess && hasRelationsField && tablesCount === 0) missing.push("Cochez au moins une table.");
  if (!srsSupported) missing.push("Projection native de la donnée non gérée : utilisez le mode JSON avancé.");
  return missing;
}
