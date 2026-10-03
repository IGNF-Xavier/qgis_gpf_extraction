// Normalisation défensive des réponses de l'API d'extraction (OGC API - Processes).
//
// Le schéma des entrées d'un processus n'est pas typé dans l'OpenAPI du service :
// `inputs` peut être un dictionnaire {id: schéma} ou une liste d'objets dont le
// `title` fait office d'identifiant. Même logique que `gpf_extraction/core/models.py`.

export const DEFAULT_OUTPUT_IDS = ["logs", "summary", "extractedData"];

// Outputs déclarés par le service mais à ne pas demander dans le corps d'exécution :
// `jobName` est refusé s'il est demandé vide (HTTP 400, constaté en conditions réelles).
export const OUTPUTS_NOT_REQUESTED = new Set(["jobName"]);

// Certains titres sont des libellés humains, pas l'identifiant attendu dans `inputs`.
const TITLE_TO_INPUT_ID = { "durée de rétention": "lifetime" };

const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

export function normalizeInputs(raw) {
  const fields = [];
  if (isObject(raw)) {
    for (const [id, value] of Object.entries(raw)) {
      const schemaHolder = isObject(value) ? value : {};
      fields.push({
        id: String(id),
        title: String(schemaHolder.title || id),
        description: String(schemaHolder.description || ""),
        schema: schemaHolder.schema ?? schemaHolder,
        required: ![0, null, undefined].includes(schemaHolder.minOccurs ?? 1),
        raw: schemaHolder,
      });
    }
  } else if (Array.isArray(raw)) {
    for (let item of raw) {
      if (!isObject(item)) continue;
      if (isObject(item.input) && Object.keys(item).length === 1) item = item.input;
      let id = String(item.id || item.name || item.title || "");
      id = TITLE_TO_INPUT_ID[id.toLowerCase()] || id;
      if (!id) {
        const keys = Object.keys(item);
        if (keys.length !== 1) continue;
        id = keys[0];
        item = isObject(item[id]) ? item[id] : {};
      }
      fields.push({
        id,
        title: String(item.title || id),
        description: String(item.description || ""),
        schema: item.schema ?? item,
        required: String(item.minOccurs ?? 1) !== "0",
        raw: item,
      });
    }
  }
  return fields;
}

export const fieldType = (f) => (isObject(f.schema) ? f.schema.type || "" : "");
export const fieldEnum = (f) => (isObject(f.schema) && Array.isArray(f.schema.enum) ? f.schema.enum : null);
export const fieldDefault = (f) => (isObject(f.schema) ? f.schema.default : undefined);

export function normalizeOutputIds(raw) {
  if (isObject(raw)) return Object.keys(raw);
  if (Array.isArray(raw)) return raw.filter(isObject).map((o) => o.id || o.name).filter(Boolean).map(String);
  return [];
}

export function findDescribedByUrl(links) {
  if (!Array.isArray(links)) return null;
  const link = links.find((l) => isObject(l) && l.rel === "describedby" && l.href);
  return link ? String(link.href) : null;
}

export function parseProcessSummary(data) {
  return { id: String(data.id ?? ""), title: String(data.title || data.id || ""), description: String(data.description || "") };
}

export function parseProcessDetails(data) {
  const outputIds = normalizeOutputIds(data.outputs);
  return {
    id: String(data.id ?? ""),
    title: String(data.title || data.id || ""),
    description: String(data.description || ""),
    inputs: normalizeInputs(data.inputs),
    outputIds: outputIds.length ? outputIds : [...DEFAULT_OUTPUT_IDS],
    describedByUrl: findDescribedByUrl(data.links),
  };
}

export function parseStoredData(data) {
  const relations = (data.type_infos && data.type_infos.relations) || [];
  const tables = relations
    .filter((r) => isObject(r) && r.name)
    .map((r) => {
      const attributes = isObject(r.attributes) ? r.attributes : {};
      const geometryAttribute =
        Object.entries(attributes).find(([, type]) => typeof type === "string" && type.startsWith("geometry"))?.[0] || null;
      return { name: String(r.name), attributes, geometryAttribute };
    });
  return { id: String(data._id ?? ""), name: String(data.name || ""), srs: String(data.srs || ""), tables };
}

export function parseJob(data) {
  return {
    jobId: String(data.jobID ?? ""),
    status: String(data.status ?? ""),
    message: String(data.message || ""),
    created: data.created ?? null,
    finished: data.finished ?? null,
    processId: String(data.processID || ""),
  };
}

const RUNNING = ["RUNNING", "ACCEPTED", "WAITING", "PROGRESS"];
export const isRunning = (status) => RUNNING.includes(String(status).toUpperCase());
export const isSuccessful = (status) => String(status).toUpperCase() === "SUCCESSFUL";
export const isFailed = (status) => ["FAILED", "DISMISSED"].includes(String(status).toUpperCase());

// Flux Atom (INSPIRE Download Service) renvoyé par le lien `extractData` : liste les
// fichiers réellement téléchargeables. Analyse par expressions régulières (pas de
// dépendance au DOM, donc testable sous Node).
export function parseAtomEntries(xml) {
  const entries = [];
  for (const block of String(xml).match(/<entry[\s>][\s\S]*?<\/entry>/g) || []) {
    const link = block.match(/<link\b[^>]*>/);
    if (!link) continue;
    const href = (link[0].match(/\bhref="([^"]*)"/) || [])[1];
    if (!href) continue;
    const mime =
      (block.match(/<(?:\w+:)?mime_type>([^<]*)<\/(?:\w+:)?mime_type>/) || [])[1] ||
      (link[0].match(/\btype="([^"]*)"/) || [])[1] ||
      "";
    const url = href.replace(/&amp;/g, "&");
    const filename = decodeURIComponent(url.split("?")[0].split("/").filter(Boolean).pop() || "fichier");
    entries.push({ href: url, mimeType: mime, filename, isMetadata: mime === "application/json" || filename.toLowerCase().endsWith(".json") });
  }
  return entries;
}
