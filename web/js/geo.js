// Géométrie, recherche administrative et préréglages — équivalent de
// `gpf_extraction/core/admin_boundary.py`.

import { GEOCODING_SEARCH, WFS_BASE, WFS_ADMIN_LAYER_PREFIX } from "./config.js";

const fmt = (n) => String(Math.round(n * 1e7) / 1e7);

// ---------------------------------------------------------------- GeoJSON ↔ WKT
const ringToWkt = (ring) => "(" + ring.map(([x, y]) => `${fmt(x)} ${fmt(y)}`).join(",") + ")";

export function geojsonToWkt(geom) {
  if (!geom || !geom.type) return null;
  if (geom.type === "Polygon") return `POLYGON(${geom.coordinates.map(ringToWkt).join(",")})`;
  if (geom.type === "MultiPolygon") {
    return `MULTIPOLYGON(${geom.coordinates.map((poly) => `(${poly.map(ringToWkt).join(",")})`).join(",")})`;
  }
  return null;
}

function forEachCoordinate(geom, fn) {
  const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
  for (const poly of polygons) for (const ring of poly) for (const pt of ring) fn(pt);
}

export function geometryBounds(geom) {
  let xmin = Infinity, ymin = Infinity, xmax = -Infinity, ymax = -Infinity;
  forEachCoordinate(geom, ([x, y]) => {
    if (x < xmin) xmin = x;
    if (x > xmax) xmax = x;
    if (y < ymin) ymin = y;
    if (y > ymax) ymax = y;
  });
  return Number.isFinite(xmin) ? [xmin, ymin, xmax, ymax] : null;
}

export function bboxToPolygon([x0, y0, x1, y1]) {
  return { type: "Polygon", coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] };
}

// ---------------------------------------------------------------- Reprojection
export function reprojectGeometry(geom, transform) {
  const mapRing = (ring) => ring.map((pt) => transform(pt));
  if (geom.type === "Polygon") return { type: "Polygon", coordinates: geom.coordinates.map(mapRing) };
  if (geom.type === "MultiPolygon") {
    return { type: "MultiPolygon", coordinates: geom.coordinates.map((poly) => poly.map(mapRing)) };
  }
  return geom;
}

// Boîte englobante d'un rectangle reprojeté : les côtés sont échantillonnés (un
// rectangle n'en reste pas un après reprojection), comme `transformBoundingBox` de QGIS.
export function transformBbox([x0, y0, x1, y1], transform, steps = 20) {
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const x = x0 + (x1 - x0) * t;
    const y = y0 + (y1 - y0) * t;
    pts.push([x, y0], [x, y1], [x0, y], [x1, y]);
  }
  const out = pts.map((p) => transform(p));
  const xs = out.map((p) => p[0]);
  const ys = out.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// Définitions proj4 des projections les plus courantes (hors EPSG:4326/3857, intégrées).
export const PROJ_DEFS = {
  "EPSG:2154": "+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
  "EPSG:4171": "+proj=longlat +ellps=GRS80 +no_defs",
  "EPSG:2972": "+proj=utm +zone=22 +ellps=GRS80 +units=m +no_defs",
  "EPSG:2975": "+proj=utm +zone=40 +south +ellps=GRS80 +units=m +no_defs",
  "EPSG:4471": "+proj=utm +zone=38 +south +ellps=GRS80 +units=m +no_defs",
  "EPSG:5490": "+proj=utm +zone=20 +ellps=GRS80 +units=m +no_defs",
  "EPSG:4559": "+proj=utm +zone=20 +ellps=GRS80 +units=m +no_defs",
};

// Fonction de transformation EPSG:4326 → `crs`, ou null si la projection n'est pas gérée.
export function makeTransformFrom4326(proj4, crs) {
  const code = String(crs || "").trim().toUpperCase();
  if (!code || code === "EPSG:4326") return (pt) => pt;
  try {
    if (PROJ_DEFS[code] && !proj4.defs(code)) proj4.defs(code, PROJ_DEFS[code]);
    const converter = proj4("EPSG:4326", code);
    return (pt) => converter.forward(pt);
  } catch {
    return null;
  }
}

export function srid(crs) {
  const m = /(\d+)\s*$/.exec(String(crs || ""));
  return m ? Number(m[1]) : 4326;
}

// ---------------------------------------------------------------- Recherche administrative
// Catégories de l'API de géocodage retenues → (libellé, champ de désambiguïsation).
const ADMIN_KINDS = {
  commune: ["Commune", "depcode"],
  "département": ["Département", null],
  "région": ["Région", null],
};

export async function searchAdmin(text, fetchImpl = fetch, limit = 20) {
  text = (text || "").trim();
  if (text.length < 2) return [];
  const url =
    `${GEOCODING_SEARCH}?q=${encodeURIComponent(text)}&index=poi&category=administratif` +
    `&returntruegeometry=true&limit=${limit}`;
  const response = await fetchImpl(url);
  if (!response.ok) throw new Error(`Recherche administrative : HTTP ${response.status}`);
  const data = await response.json();
  const results = [];
  for (const feature of data.features || []) {
    const props = feature.properties || {};
    const kindKey = (props.category || []).find((c) => c in ADMIN_KINDS);
    if (!kindKey) continue; // ex. « epci » : hors périmètre
    const [kind, disambiguatorField] = ADMIN_KINDS[kindKey];
    // `truegeometry` est un GeoJSON encodé en chaîne ; sans lui `geometry` n'est
    // qu'un point représentatif, inutilisable comme emprise.
    if (!props.truegeometry) continue;
    let geometry;
    try {
      geometry = JSON.parse(props.truegeometry);
    } catch {
      continue;
    }
    if (!geometryBounds(geometry)) continue;
    let disambiguator = disambiguatorField ? props[disambiguatorField] : null;
    if (Array.isArray(disambiguator)) disambiguator = disambiguator[0];
    const label = `${props.toponym || text} (${kind}${disambiguator ? " " + disambiguator : ""})`;
    const code = Array.isArray(props.citycode) ? props.citycode[0] : props.citycode || "";
    results.push({ label, kind, code: String(code), geometry });
  }
  return results;
}

// ---------------------------------------------------------------- Préréglages
const METROPOLE_BBOX = [-5.5, 41.0, 10.0, 51.5];

// (libellé, code INSEE, rectangle de repli si le WFS est indisponible)
export const DOM_PRESETS = [
  ["Guadeloupe (971)", "971", [-61.85, 15.83, -60.95, 16.55]],
  ["Martinique (972)", "972", [-61.25, 14.35, -60.77, 14.9]],
  ["Guyane (973)", "973", [-54.6, 2.05, -51.55, 5.85]],
  ["La Réunion (974)", "974", [55.2, -21.4, 55.85, -20.85]],
  ["Mayotte (976)", "976", [45.0, -13.05, 45.35, -12.6]],
];
export const DOM_CODES = new Set(DOM_PRESETS.map(([, code]) => code));

// France métropolitaine (rectangle : aucune entité « pays » n'existe) + les 5 DOM avec
// leur vrai contour, obtenu en une seule requête WFS par code INSEE (repli sur un
// rectangle par DOM si elle échoue — jamais bloquant).
export async function loadPresets(fetchImpl = fetch) {
  const presets = [{ label: "France métropolitaine (préréglage)", kind: "Préréglage", code: "", geometry: bboxToPolygon(METROPOLE_BBOX) }];
  const real = {};
  try {
    const codes = DOM_PRESETS.map(([, code]) => `'${code}'`).join(",");
    const url =
      `${WFS_BASE}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=${WFS_ADMIN_LAYER_PREFIX}:departement` +
      `&OUTPUTFORMAT=application/json&CQL_FILTER=${encodeURIComponent(`code_insee IN (${codes})`)}`;
    const response = await fetchImpl(url);
    if (response.ok) {
      const data = await response.json();
      for (const feature of data.features || []) {
        const code = String((feature.properties || {}).code_insee || "");
        if (code && feature.geometry && geometryBounds(feature.geometry)) real[code] = feature.geometry;
      }
    }
  } catch {
    /* repli silencieux sur les rectangles */
  }
  for (const [label, code, bbox] of DOM_PRESETS) {
    presets.push({ label: `${label} (préréglage)`, kind: "Préréglage", code, geometry: real[code] || bboxToPolygon(bbox) });
  }
  return presets;
}

// Avertit si l'emprise est un DOM et que le titre du produit dit explicitement ne pas
// couvrir les DOM (ex. « France entière (hors DOM) »). Heuristique de nommage : muette
// si le titre ne dit rien dans un sens ou l'autre.
export function domCoverageWarning(processTitle, adminResult) {
  if (!adminResult || !DOM_CODES.has(adminResult.code)) return "";
  if (!/hors dom/i.test(processTitle || "")) return "";
  return `Le produit choisi indique ne pas couvrir les DOM (titre : « ${processTitle} ») : aucune donnée n'est probablement disponible sur ce territoire pour ce produit.`;
}
