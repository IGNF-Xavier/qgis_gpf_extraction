// Contrôleur de l'interface web : relie les modules purs (API, géométrie, construction de
// requête) au DOM. Tout texte venant de l'API est inséré via `textContent` (jamais en HTML).

import { ExtractionApi, ApiError, describeApiError } from "./api.js";
import { AuthState, handleRedirect, oidcConfigured, startLogin } from "./auth.js";
import {
  DEFAULT_PREDICATES, PREDICATE_SQL, buildBody, buildRelations, curlCommand, initialValue,
  isMultilayerFormat, missingForLaunch, preferredEnumValue,
} from "./builder.js";
import { API_BASE, FILTER_BUDGET_BYTES, POLL_INTERVAL_MS, REPO_URL, WEB_VERSION } from "./config.js";
import { describeFit, fitExtent, vertexBudget } from "./extent-fit.js";
import {
  bboxToPolygon, domCoverageWarning, geometryBounds, loadPresets, makeTransformFrom4326,
  reprojectGeometry, searchAdmin, srid, transformBbox,
} from "./geo.js";
import { JOB_FILTERS, pageWindow, paginateJobs, sortNewestFirst } from "./jobs-list.js";
import { createMap } from "./map.js";
import { fieldEnum, fieldType, isFailed, isRunning, isSuccessful } from "./models.js";
import proj4 from "proj4";

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) node.append(child);
  return node;
};
// Identifiants uniques pour relier <label for> et <input> générés dynamiquement (DSFR).
let uid = 0;
const nextId = (prefix) => `${prefix}-${++uid}`;

// Cases à cocher / boutons radio au format DSFR : <div class="fr-…-group"><input><label></div>.
function dsfrChoice(type, { name, text, checked = false, small = true, hint = "" }) {
  const id = nextId(type);
  const input = el("input", { type, id, checked });
  if (name) input.name = name;
  const label = el("label", { className: "fr-label", htmlFor: id }, text);
  if (hint) label.append(el("span", { className: "fr-hint-text", textContent: hint }));
  const wrap = el("div", { className: `fr-${type}-group${small ? ` fr-${type}-group--sm` : ""}` }, input, label);
  return { wrap, input, label };
}
const store = {
  get: (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set: (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota ou stockage indisponible */ } },
};

const auth = new AuthState();
const api = new ExtractionApi({ getToken: () => auth.token });

const state = {
  processes: [],
  selection: new Map(),   // au plus un produit : id -> { process, storedData, checkedTables, values, controls, tableFilter, jsonEdit, body, ui }
  pending: new Set(),     // produit choisi dont le chargement est en cours
  extent: null,           // { label, geometry (EPSG:4326), bbox, code, precise, fits: Map (contours adaptés, par budget) }
  fitMode: "auto",        // contour envoyé au serveur : auto | precise | envelopes | bbox
  adminResult: null, missing: [],
  predicates: new Set(DEFAULT_PREDICATES),
  jobs: store.get("gpf_web_jobs", []),
  results: new Map(),     // jobId -> { files, summary, warnings } (en mémoire seulement)
};

// ------------------------------------------------------------------ Utilitaires
async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = el("textarea", { value: text });
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  if (button) {
    const label = button.textContent;
    button.textContent = "Copié ✓";
    setTimeout(() => { button.textContent = label; }, 1500);
  }
}

function showError(error, context = {}) {
  $("errorMessage").textContent = describeApiError(error, context);
  $("errorReport").value = error instanceof ApiError ? error.report() : String(error && error.message ? error.message : error);
  $("errorReport").hidden = !$("errorReport").value;
  $("errorCopy").hidden = $("errorReport").hidden;
  if (window.dsfr) window.dsfr($("errorDialog")).modal.disclose();
  else window.alert($("errorMessage").textContent); // DSFR indisponible : au moins afficher le message
}
$("errorCopy").addEventListener("click", (e) => copyText($("errorReport").value, e.currentTarget));

// ------------------------------------------------------------------ 1. Connexion
function refreshAuthUI() {
  const status = $("authStatus");
  const alert = $("authAlert");
  let tone = "info";
  if (!auth.token) {
    status.textContent = "Non connecté : sans jeton, la recherche d'emprise et la construction de la requête fonctionnent, mais pas la liste des produits ni le lancement.";
  } else if (auth.isExpired) {
    status.textContent = "Jeton expiré : collez-en un nouveau.";
    tone = "error";
  } else {
    const left = auth.secondsLeft;
    status.textContent = left === null ? "Jeton en place (expiration inconnue)." : `Jeton valide encore ${Math.max(1, Math.round(left / 60))} min.`;
    tone = "success";
  }
  alert.className = `fr-alert fr-alert--sm fr-alert--${tone}`;
  $("oidcLogin").hidden = !oidcConfigured();
  refreshRequest();
}
auth.onChange = () => {
  refreshAuthUI();
  if (auth.authenticated) {
    loadProducts();
    loadServerJobs();
  }
};
$("tokenUse").addEventListener("click", () => {
  auth.setToken($("tokenInput").value, $("tokenRemember").checked);
  $("tokenInput").value = "";
  if (auth.authenticated) advanceFrom("stepAuthBody", state.extent ? "stepProductBody" : "stepExtentBody");
});
$("tokenClear").addEventListener("click", () => {
  auth.clear();
  state.processes = [];
  renderProducts();
  resetServerJobs();
});
$("oidcLogin").addEventListener("click", () => startLogin());
setInterval(refreshAuthUI, 30000);

// ------------------------------------------------------------------ 2. Emprise
const drawButton = $("drawBbox");
const DRAW_LABEL = drawButton.textContent;
const mapApi = createMap({
  target: "map",
  onBox: (bbox) => applyBbox(bbox),
  onDrawChange: (active) => { drawButton.textContent = active ? "Cliquez-glissez sur la carte…" : DRAW_LABEL; },
});

function setExtent({ label, geometry, code = "", precise }) {
  const bbox = geometryBounds(geometry);
  state.extent = { label, geometry, bbox, code, precise, fits: new Map() };
  const [x0, y0, x1, y1] = bbox;
  // Le résumé est toujours la bounding box ; le contour précis (s'il existe) est ce qui
  // part réellement dans le filtre — d'où la précision ci-dessous.
  $("extentLabel").textContent =
    `Emprise « ${label} » (EPSG:4326) : ${x0.toFixed(4)}, ${y0.toFixed(4)} → ${x1.toFixed(4)}, ${y1.toFixed(4)}` +
    (precise ? " (rectangle englobant affiché à titre indicatif ; le filtre envoyé au serveur utilise le contour, simplifié ou remplacé par des rectangles s'il est trop lourd : voir l'étape 5)" : "");
  mapApi.showExtent(geometry, bbox);
  refreshRequest();
}

function selectAdmin(result) {
  state.adminResult = result;
  setExtent({ label: result.label, geometry: result.geometry, code: result.code, precise: true });
}

// Les onglets « Recherche administrative » / « Rectangle » sont gérés par le DSFR (fr-tabs).

const tag = (label, onClick) => {
  const button = el("button", { type: "button", className: "fr-tag", textContent: label });
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", (event) => {
    event.stopImmediatePropagation(); // le DSFR basculerait aria-pressed lui-même (et désélectionnerait au 2e clic)
    onClick(button);
  });
  return el("li", {}, button);
};

let searchTimer = null;
$("adminSearch").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const list = $("adminResults");
    const text = $("adminSearch").value.trim();
    list.replaceChildren();
    if (text.length < 2) return;
    try {
      const results = await searchAdmin(text);
      if (text !== $("adminSearch").value.trim()) return; // réponse périmée
      if (!results.length) list.append(el("li", { className: "fr-hint-text", textContent: "Aucun résultat." }));
      for (const result of results) {
        list.append(tag(result.label, (button) => {
          for (const b of list.querySelectorAll("button")) b.setAttribute("aria-pressed", "false");
          button.setAttribute("aria-pressed", "true");
          selectAdmin(result);
        }));
      }
    } catch (error) {
      list.append(el("li", { className: "fr-hint-text", textContent: `Recherche indisponible (${error.message}).` }));
    }
  }, 350);
});

loadPresets().then((presets) => {
  for (const preset of presets) {
    $("presets").append(tag(preset.label.replace(" (préréglage)", ""), (button) => {
      for (const b of $("presets").querySelectorAll("button")) b.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      selectAdmin(preset);
    }));
  }
});

// Rectangle dessiné à la souris (ou saisi à la main) : le rectangle EST l'emprise utilisée.
drawButton.addEventListener("click", () => {
  if (!mapApi.startDraw()) $("extentLabel").textContent = "La carte n'est pas disponible : saisissez les coordonnées du rectangle.";
});
function applyBbox(bbox) {
  [$("bboxXmin").value, $("bboxYmin").value, $("bboxXmax").value, $("bboxYmax").value] = bbox.map((n) => +n.toFixed(6));
  state.adminResult = null;
  for (const b of document.querySelectorAll("#presets button, #adminResults button")) b.setAttribute("aria-pressed", "false");
  setExtent({ label: "BBox", geometry: bboxToPolygon(bbox), precise: false });
}
$("fitMode").addEventListener("change", () => {
  state.fitMode = $("fitMode").value;
  refreshRequest();
});
$("bboxApply").addEventListener("click", () => {
  const [x0, y0, x1, y1] = ["bboxXmin", "bboxYmin", "bboxXmax", "bboxYmax"].map((id) => parseFloat($(id).value));
  if ([x0, y0, x1, y1].some(Number.isNaN) || x0 >= x1 || y0 >= y1) {
    $("extentLabel").textContent = "Rectangle invalide : renseignez ouest < est et sud < nord.";
    return;
  }
  applyBbox([x0, y0, x1, y1]);
});

// ------------------------------------------------------------------ 3. Produits
async function loadProducts() {
  if (!auth.authenticated) return;
  $("productStatus").textContent = "Chargement des produits…";
  try {
    state.processes = await api.listProcesses();
    $("productStatus").textContent = `${state.processes.length} produit(s) disponible(s).`;
    renderProducts();
    renderServerJobs(); // les titres de produits sont maintenant connus
    updateSteps();
  } catch (error) {
    $("productStatus").textContent = "Impossible de lister les produits.";
    showError(error);
  }
}

const BDTOPO_HINTS = ["bdtopo", "bd topo", "bd_topo"];
const FILTER_THRESHOLD = 12; // en dessous, la liste tient à l'écran : pas de champ de filtre
function renderProducts() {
  $("productFilterGroup").hidden = state.processes.length <= FILTER_THRESHOLD;
  const filter = $("productFilter").value.trim().toLowerCase();
  const list = $("productList");
  list.replaceChildren();
  const sorted = [...state.processes].sort((a, b) => {
    const rank = (p) => (BDTOPO_HINTS.some((h) => p.title.toLowerCase().includes(h)) ? 0 : 1);
    return rank(a) - rank(b) || a.title.localeCompare(b.title);
  });
  for (const process of sorted) {
    if (filter && !`${process.title} ${process.id} ${process.description}`.toLowerCase().includes(filter)) continue;
    const checked = state.selection.has(process.id) || state.pending.has(process.id);
    const { wrap, input, label } = dsfrChoice("radio", { name: "product", text: process.title, checked, small: false });
    input.value = process.id;
    label.title = process.description;
    list.append(wrap);
  }
}
$("productFilter").addEventListener("input", renderProducts);
$("productList").addEventListener("change", (event) => {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.checked) selectProduct(input.value, input);
});

// Un job d'extraction ne concerne qu'un produit (POST /processes/{id}/execution) et le service
// refuse un second job tant que le premier tourne (HTTP 429) : on ne choisit donc qu'un produit.
async function selectProduct(id, input) {
  state.selection.clear();
  state.pending.clear();
  state.pending.add(id);
  renderSelection();
  $("productStatus").textContent = "Chargement du produit…";
  try {
    const process = await api.getProcess(id);
    let storedData = null;
    if (process.describedByUrl) {
      try {
        storedData = await api.getStoredData(process.describedByUrl);
      } catch (error) {
        console.warn(error);
        $("productStatus").textContent = "Description de la donnée stockée indisponible : liste des tables vide (utilisez le mode JSON avancé).";
      }
    }
    // Le titre de la liste fait foi (celui que l'utilisateur a choisi, et sur lequel repose
    // l'avertissement de couverture DOM), comme dans le plugin.
    const summary = state.processes.find((p) => p.id === id);
    if (summary && summary.title) process.title = summary.title;
    if (!state.pending.has(id)) return; // un autre produit a été choisi pendant le chargement
    state.selection.set(id, { process, storedData, checkedTables: new Set(), values: {}, controls: {}, tableFilter: "", jsonEdit: false, body: null, ui: {} });
    if ($("productStatus").textContent === "Chargement du produit…") $("productStatus").textContent = "";
    renderSelection();
  } catch (error) {
    if (input) input.checked = false;
    $("productStatus").textContent = "Impossible de charger ce produit.";
    showError(error);
  } finally {
    if (state.pending.has(id) && !state.selection.has(id)) state.pending.delete(id);
  }
}

function renderSelection() {
  renderParams();
  renderRequestBlocks();
  refreshRequest();
}

// ------------------------------------------------------------------ 4. Paramètres
const FIELD_LABELS = { append: "Fusionner toutes les tables en un seul fichier" };
const COMMON_SRS = ["EPSG:4326", "EPSG:2154", "EPSG:3857", "EPSG:4171"];

// Prédicats (cases à cocher combinées en OU ; au moins un reste toujours coché), communs à tous les produits.
function renderPredicates() {
  const predicates = $("predicates");
  predicates.replaceChildren();
  const boxes = new Map();
  for (const name of Object.keys(PREDICATE_SQL)) {
    const { wrap, input } = dsfrChoice("checkbox", { text: name, checked: state.predicates.has(name) });
    boxes.set(name, input);
    input.addEventListener("change", () => {
      if (input.checked) state.predicates.add(name);
      else state.predicates.delete(name);
      if (!state.predicates.size) {
        state.predicates.add(DEFAULT_PREDICATES[0]);
        for (const [other, box] of boxes) box.checked = other === DEFAULT_PREDICATES[0];
      }
      refreshRequest();
    });
    predicates.append(wrap);
  }
}

function renderParams() {
  const box = $("paramsList");
  box.replaceChildren();
  for (const entry of state.selection.values()) box.append(productParams(entry));
}

function productParams(entry) {
  const { process } = entry;
  entry.controls = {};
  const block = el("section", { className: "product-block" }, el("h3", { className: "fr-h6", textContent: process.title }));
  if (process.inputs.some((f) => f.id === "relations")) block.append(tablesBlock(entry));
  const fields = el("div", { className: "fr-mt-3w" });
  for (const field of process.inputs) {
    if (field.id === "relations") continue;
    const node = buildField(entry, field);
    if (node) fields.append(node);
  }
  block.append(fields);
  syncAppendWithFormat(entry, true);
  return block;
}

function buildField(entry, field) {
  const text = (FIELD_LABELS[field.id.toLowerCase()] || field.title || field.id) + (field.required ? " *" : "");
  const e = fieldEnum(field);
  const type = fieldType(field);
  const id = nextId("field");
  // Groupe DSFR : <div class="fr-input-group|fr-select-group"><label class="fr-label"><input|select></div>
  const group = (kind, control, hint = "") => {
    const label = el("label", { className: "fr-label", htmlFor: id, title: field.description || "" }, text);
    if (hint) label.append(el("span", { className: "fr-hint-text", textContent: hint }));
    return el("div", { className: `fr-${kind}-group fr-mb-2w` }, label, control);
  };
  let input;
  let wrap;

  if (field.id.toLowerCase() === "srs") {
    const native = entry.storedData && entry.storedData.srs;
    const options = [...new Set([native, ...COMMON_SRS].filter(Boolean))];
    input = el("input", { type: "text", id, className: "fr-input", value: native || "" });
    const listId = nextId("srsOptions");
    input.setAttribute("list", listId); // `list` est en lecture seule côté DOM : attribut obligatoire
    const list = el("datalist", { id: listId });
    for (const code of options) list.append(el("option", { value: code, label: code === native ? "natif de la donnée" : "" }));
    wrap = group("input", input, "Projection de sortie du résultat (indépendante du filtre spatial).");
    wrap.append(list);
    input.addEventListener("input", () => { entry.values.srs = input.value.trim() || undefined; refreshRequest(); });
    entry.values.srs = native || undefined;
  } else if (e) {
    input = el("select", { id, className: "fr-select" });
    if (!field.required) input.append(el("option", { value: "", textContent: "(non spécifié)" }));
    for (const value of e) input.append(el("option", { value: String(value), textContent: String(value) }));
    const initial = field.required ? preferredEnumValue(e) : initialValue(field);
    input.value = initial === undefined ? "" : String(initial);
    entry.values[field.id] = input.value || undefined;
    input.addEventListener("change", () => {
      entry.values[field.id] = input.value || undefined;
      if (field.id === "format") syncAppendWithFormat(entry);
      refreshRequest();
    });
    wrap = group("select", input);
  } else if (type === "boolean") {
    const choice = dsfrChoice("checkbox", { text, checked: Boolean(initialValue(field)) });
    input = choice.input;
    choice.label.title = field.description || "";
    entry.values[field.id] = input.checked;
    input.addEventListener("change", () => { entry.values[field.id] = input.checked; refreshRequest(); });
    wrap = choice.wrap;
    wrap.classList.add("fr-mb-2w");
  } else if (type === "integer" || type === "number") {
    input = el("input", { type: "number", id, className: "fr-input", step: type === "integer" ? "1" : "any" });
    if (field.id === "lifetime") {
      input.min = "0";
      input.max = "336";
      input.placeholder = "défaut serveur (168 h)";
    }
    const def = initialValue(field);
    if (def !== undefined) input.value = def;
    const read = () => {
      const n = parseFloat(input.value);
      // Champ optionnel laissé vide ou à 0 : omis, pour ne pas écraser le défaut du serveur.
      entry.values[field.id] = Number.isNaN(n) || (n === 0 && !field.required) ? undefined : n;
    };
    read();
    input.addEventListener("input", () => { read(); refreshRequest(); });
    wrap = group("input", input);
  } else if (type === "" || type === "string") {
    input = el("input", { type: "text", id, className: "fr-input" });
    if (typeof initialValue(field) === "string") input.value = initialValue(field);
    entry.values[field.id] = input.value.trim() || undefined;
    input.addEventListener("input", () => { entry.values[field.id] = input.value.trim() || undefined; refreshRequest(); });
    wrap = group("input", input);
  } else {
    return null; // array / object : le mode JSON avancé reste le moyen de le renseigner
  }
  entry.controls[field.id] = input;
  return wrap;
}

// `append` n'a de sens que pour les formats multi-couches (GPKG, PGDUMP) ; coché par
// défaut pour eux (un seul fichier résultat), décoché et inactif sinon.
function syncAppendWithFormat(entry, initial = false) {
  const { append, format } = entry.controls;
  if (!append || !format) return;
  const ok = isMultilayerFormat(format.value);
  const wasEnabled = !append.disabled;
  append.disabled = !ok;
  if (!ok) append.checked = false;
  else if (initial || !wasEnabled) append.checked = true; // repasse à un format multi-couches : recoché
  entry.values.append = append.checked;
}

// Tables d'un produit (input `relations`) : filtre, tout cocher / décocher, grille de cases.
function tablesBlock(entry) {
  const filterId = nextId("tableFilter");
  const filter = el("input", { type: "search", id: filterId, className: "fr-input", placeholder: "Filtrer les tables…", autocomplete: "off" });
  const all = el("button", { type: "button", className: "fr-btn fr-btn--secondary", textContent: "Tout cocher" });
  const none = el("button", { type: "button", className: "fr-btn fr-btn--secondary", textContent: "Tout décocher" });
  const grid = el("div", { className: "tables" });
  const count = el("p", { className: "fr-hint-text" });
  entry.ui.tableGrid = grid;
  entry.ui.tableCount = count;
  filter.addEventListener("input", () => { entry.tableFilter = filter.value.trim().toLowerCase(); renderTables(entry); });
  const setAll = (checked) => {
    for (const table of visibleTables(entry)) {
      if (checked) entry.checkedTables.add(table.name);
      else entry.checkedTables.delete(table.name);
    }
    renderTables(entry);
    refreshRequest();
  };
  all.addEventListener("click", () => setAll(true));
  none.addEventListener("click", () => setAll(false));
  const wrap = el("div", {},
    el("h4", { className: "fr-text--bold fr-text--md fr-mb-1w", textContent: "Tables à extraire" }),
    el("div", { className: "fr-grid-row fr-grid-row--gutters fr-grid-row--middle" },
      el("div", { className: "fr-col-12 fr-col-md-6" },
        el("div", { className: "fr-input-group" }, el("label", { className: "fr-label sr-only", htmlFor: filterId, textContent: `Filtrer les tables de ${entry.process.title}` }), filter)),
      el("div", { className: "fr-col-12 fr-col-md-6" },
        el("ul", { className: "fr-btns-group fr-btns-group--sm fr-btns-group--inline-md" }, el("li", {}, all), el("li", {}, none)))),
    grid, count);
  renderTables(entry);
  return wrap;
}

const entryTables = (entry) => (entry.storedData && entry.storedData.tables) || [];
const visibleTables = (entry) => entryTables(entry).filter((t) => !entry.tableFilter || t.name.toLowerCase().includes(entry.tableFilter));

function renderTables(entry) {
  const grid = entry.ui.tableGrid;
  grid.replaceChildren();
  for (const table of visibleTables(entry)) {
    const { wrap, input } = dsfrChoice("checkbox", {
      text: table.name + (table.geometryAttribute ? "" : " — sans géométrie"), checked: entry.checkedTables.has(table.name),
    });
    input.addEventListener("change", () => {
      if (input.checked) entry.checkedTables.add(table.name);
      else entry.checkedTables.delete(table.name);
      refreshRequest();
    });
    grid.append(wrap);
  }
  if (!entryTables(entry).length) grid.append(el("span", { className: "fr-hint-text", textContent: "Aucune table décrite pour ce produit." }));
  updateTableCount(entry);
}

function updateTableCount(entry) {
  if (entry.ui.tableCount) entry.ui.tableCount.textContent = `${entry.checkedTables.size}/${entryTables(entry).length} table(s) sélectionnée(s)`;
}

// ------------------------------------------------------------------ 5. Requête et lancement
// Emprise exprimée dans la SRID *native de la donnée stockée*, pas dans la projection de
// sortie choisie (cf. builder.js). `supported` faux si la projection native n'est pas gérée.
function extentForFilter(entry) {
  if (!state.extent) return { extent: null, supported: true };
  const nativeCrs = (entry.storedData && entry.storedData.srs) || "EPSG:4326";
  const transform = makeTransformFrom4326(proj4, nativeCrs);
  if (!transform) return { extent: null, supported: false, nativeCrs };
  const { bbox, precise } = state.extent;
  const extent = { srid: srid(nativeCrs) };
  const fit = precise ? fitFor(entry) : null;
  if (fit && fit.geometry) {
    extent.geometry = reprojectGeometry(fit.geometry, transform);
    extent.bbox = geometryBounds(extent.geometry);
  } else {
    extent.bbox = transformBbox(bbox, transform);
  }
  return { extent, supported: true, nativeCrs, fit };
}

// Contour réellement envoyé : il est recopié dans le filtre de chaque table (et chaque
// prédicat), donc son budget de sommets dépend du nombre de tables cochées. Mémoïsé par budget.
function fitFor(entry) {
  const tables = entryTables(entry).filter((t) => entry.checkedTables.has(t.name) && t.geometryAttribute);
  const maxVertices = vertexBudget({ tables: tables.length, predicates: state.predicates.size, maxBytes: FILTER_BUDGET_BYTES });
  const key = `${state.fitMode}|${maxVertices}`;
  const { fits, geometry } = state.extent;
  if (!fits.has(key)) fits.set(key, fitExtent(geometry, { mode: state.fitMode, maxVertices }));
  return fits.get(key);
}

// Un bloc par produit : résumé, et le corps JSON (modifiable, copiable) dans un accordéon.
function renderRequestBlocks() {
  const box = $("requestList");
  box.replaceChildren();
  for (const entry of state.selection.values()) box.append(requestBlock(entry));
}

function requestBlock(entry) {
  const { title } = entry.process;
  const bodyId = nextId("requestBody");
  const textarea = el("textarea", { className: "fr-input mono", readOnly: true, rows: 14, spellcheck: false });
  const textareaId = nextId("requestJson");
  textarea.id = textareaId;
  const size = el("p", { className: "fr-hint-text" });
  const edit = dsfrChoice("checkbox", { text: "Modifier le JSON à la main (mode avancé)" });
  edit.input.addEventListener("change", () => {
    entry.jsonEdit = edit.input.checked;
    textarea.readOnly = !entry.jsonEdit;
    refreshRequest();
  });
  const copyJson = el("button", { type: "button", className: "fr-btn fr-btn--secondary fr-btn--sm", textContent: "Copier le JSON" });
  copyJson.addEventListener("click", (event) => copyText(textarea.value, event.currentTarget));
  const copyCurl = el("button", { type: "button", className: "fr-btn fr-btn--secondary fr-btn--sm", textContent: "Copier en curl" });
  copyCurl.addEventListener("click", (event) => {
    try {
      copyText(curlCommand(`${API_BASE}/processes/${entry.process.id}/execution`, currentBody(entry)), event.currentTarget);
    } catch (error) {
      showError(error);
    }
  });
  entry.ui.json = textarea;
  entry.ui.size = size;
  entry.ui.summary = el("p", { className: "fr-text--sm fr-mb-1w" });

  const toggle = el("button", { type: "button", className: "fr-accordion__btn", textContent: "Voir ou modifier la requête JSON" });
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", bodyId);
  const accordion = el("section", { className: "fr-accordion" },
    el("h4", { className: "fr-accordion__title" }, toggle),
    el("div", { className: "fr-collapse", id: bodyId },
      edit.wrap,
      el("div", { className: "fr-input-group" }, el("label", { className: "fr-label sr-only", htmlFor: textareaId, textContent: `Corps de la requête — ${title}` }), textarea),
      size,
      el("ul", { className: "fr-btns-group fr-btns-group--sm fr-btns-group--inline-md" }, el("li", {}, copyJson), el("li", {}, copyCurl))));
  return el("div", { className: "request-block" }, el("h3", { className: "fr-h6 fr-mb-1w", textContent: title }), entry.ui.summary, accordion);
}

function refreshRequest() {
  const entries = [...state.selection.values()];

  const warnings = entries.map(({ process }) => domCoverageWarning(process.title, state.adminResult)).filter(Boolean);
  $("domWarningText").textContent = warnings.join(" ");
  $("domWarning").hidden = !warnings.length;

  for (const entry of entries) {
    const { extent, fit } = extentForFilter(entry);
    const tables = entryTables(entry).filter((t) => entry.checkedTables.has(t.name));
    const relations = buildRelations(tables, extent, [...state.predicates]);
    entry.body = buildBody(entry.process, entry.values, relations, state.extent ? state.extent.bbox : null);
    if (!entry.jsonEdit && entry.ui.json) entry.ui.json.value = JSON.stringify(entry.body, null, 2);
    const kb = new Blob([JSON.stringify(entry.body)]).size / 1024;
    const size = `${kb.toFixed(kb < 10 ? 1 : 0)} Ko`;
    if (entry.ui.size) entry.ui.size.textContent = `Corps de requête : ${size}.`;
    if (entry.ui.summary) {
      const format = entry.values.format ? ` · ${entry.values.format}` : "";
      const srs = entry.values.srs ? ` · ${entry.values.srs}` : "";
      const filter = fit ? ` · filtre : ${describeFit(fit)}` : "";
      entry.ui.summary.textContent = `${entry.checkedTables.size} table(s)${format}${srs} · requête de ${size}${filter}`;
    }
    updateTableCount(entry);
  }

  const [entry] = entries;
  state.missing = missingForLaunch({
    authenticated: auth.authenticated,
    hasProcess: Boolean(entry),
    extent: state.extent,
    tablesCount: entry ? entry.checkedTables.size : 0,
    hasRelationsField: entry ? entry.process.inputs.some((f) => f.id === "relations") : false,
    srsSupported: entry ? extentForFilter(entry).supported : true,
  });
  $("missing").replaceChildren(...state.missing.map((m) => el("li", { textContent: m })));
  // Mode JSON avancé : on laisse l'utilisateur lancer ce qu'il a écrit (seuls le jeton et le produit restent exigés).
  $("launch").disabled = !entry || (entry.jsonEdit ? !auth.authenticated : state.missing.length > 0) || launching;
  updateSteps();
}

function currentBody(entry) {
  if (!entry.jsonEdit) return entry.body;
  try {
    return JSON.parse(entry.ui.json.value);
  } catch (error) {
    throw new Error(`Le JSON saisi pour « ${entry.process.title} » est invalide : ${error.message}`);
  }
}

let launching = false;

function trackLaunched(entry, body, job) {
  const tables = Object.keys((body.inputs && body.inputs.relations) || {}).length;
  state.jobs.unshift({
    jobId: job.jobId, processId: entry.process.id, title: entry.process.title, status: job.status, message: job.message,
    created: new Date().toISOString(), tables, comment: "",
  });
  tracked.page = 1;
  saveJobs();
  renderJobs();
}

$("launch").addEventListener("click", async () => {
  const [entry] = state.selection.values();
  if (!entry || launching) return;
  let body;
  try {
    body = currentBody(entry);
  } catch (error) {
    showError(error);
    return;
  }
  launching = true;
  refreshRequest();
  try {
    const job = await api.execute(entry.process.id, body);
    trackLaunched(entry, body, job);
    setStepOpen("stepJobsBody", true);
    scrollToStep("stepJobs");
  } catch (error) {
    showError(error, { merge: Boolean(body.inputs && body.inputs.append === true), tables: Object.keys((body.inputs && body.inputs.relations) || {}).length });
  } finally {
    launching = false;
    refreshRequest();
  }
});

// ------------------------------------------------------------------ 6. Jobs
const saveJobs = () => store.set("gpf_web_jobs", state.jobs);
try { localStorage.removeItem("gpf_web_ignored_jobs"); } catch { /* ancienne clé de l'import en bloc, devenue inutile */ }

const STATUS_LABEL = { successful: "terminé", running: "en cours", accepted: "en attente", failed: "échec", dismissed: "annulé" };

function jobHeader(title, status) {
  const badge = isSuccessful(status) ? "success" : isFailed(status) ? "error" : "info";
  return el("header", {}, el("strong", { textContent: title }),
    el("span", { className: `fr-badge fr-badge--sm fr-badge--${badge}`, textContent: STATUS_LABEL[status] || status || "inconnu" }));
}

function jobActions() {
  const actions = el("ul", { className: "fr-btns-group fr-btns-group--sm fr-btns-group--inline-md" });
  const button = (text, handler, secondary = true) => {
    const b = el("button", { type: "button", textContent: text, className: `fr-btn${secondary ? " fr-btn--secondary" : ""}` });
    b.addEventListener("click", handler);
    actions.append(el("li", {}, b));
  };
  return { actions, button };
}

// Pagination au format DSFR (fr-pagination) ; un lien désactivé n'a ni href ni clic.
function renderPager(nav, view, goTo, focus) {
  nav.replaceChildren();
  nav.hidden = view.pages <= 1;
  if (view.pages <= 1) return;
  const item = (label, page, extraClass = "", title = label) => {
    const link = el("a", { className: `fr-pagination__link ${extraClass}`.trim(), textContent: label });
    if (page === null) {
      link.setAttribute("aria-disabled", "true");
      link.setAttribute("role", "link");
    } else {
      link.href = `#${nav.id}`;
      link.title = title;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        goTo(page);
      });
    }
    return { li: el("li", {}, link), link };
  };
  const list = el("ul", { className: "fr-pagination__list" });
  const { page, pages } = view;
  list.append(item("Première page", page > 1 ? 1 : null, "fr-pagination__link--first").li);
  list.append(item("Page précédente", page > 1 ? page - 1 : null, "fr-pagination__link--prev fr-pagination__link--lg-label").li);
  for (const entry of pageWindow(page, pages)) {
    if (entry === "…") {
      list.append(item("…", null).li);
      continue;
    }
    const hideOnMobile = Math.abs(entry - page) > 1 && entry !== 1 && entry !== pages;
    const { li, link } = item(String(entry), entry, hideOnMobile ? "fr-displayed-lg" : "", `Page ${entry}`);
    if (entry === page) link.setAttribute("aria-current", "page");
    list.append(li);
  }
  list.append(item("Page suivante", page < pages ? page + 1 : null, "fr-pagination__link--next fr-pagination__link--lg-label").li);
  list.append(item("Dernière page", page < pages ? pages : null, "fr-pagination__link--last").li);
  nav.append(list);
  if (focus) {
    const current = nav.querySelector('[aria-current="page"]');
    if (current) current.focus();
  }
}

// ---- Jobs suivis dans ce navigateur (paginés, du plus récent au plus ancien)
const TRACKED_PAGE_SIZE = 5;
const tracked = { page: 1 };

function trackedJobCard(job) {
  const status = String(job.status || "").toLowerCase();
  const meta = el("p", { className: "fr-text--sm fr-mb-1w", textContent: `${job.jobId} · ${new Date(job.created).toLocaleString("fr-FR")}${job.tables ? ` · ${job.tables} table(s)` : ""}${job.message ? ` · ${job.message}` : ""}` });
  const { actions, button } = jobActions();
  button("Rafraîchir", () => refreshJob(job.jobId, true));
  if (isRunning(status)) button("Annuler", () => cancelJob(job));
  if (isSuccessful(status)) button("Résultats", () => showResults(job), false);
  button("Oublier", () => forgetJob(job.jobId));
  const card = el("div", { className: "job" }, jobHeader(job.title || job.processId, status), meta, actions);
  const result = state.results.get(job.jobId);
  if (result) card.append(renderResult(result));
  return card;
}

function renderJobs({ focusPager = false } = {}) {
  const box = $("jobList");
  box.replaceChildren();
  const view = paginateJobs(state.jobs, { page: tracked.page, pageSize: TRACKED_PAGE_SIZE });
  tracked.page = view.page;
  $("jobCount").textContent = view.count ? `Jobs ${view.from} à ${view.to} sur ${view.count}.` : "Aucun job suivi dans ce navigateur.";
  for (const job of view.items) box.append(trackedJobCard(job));
  renderPager($("jobPager"), view, (page) => { tracked.page = page; renderJobs({ focusPager: true }); }, focusPager);
  updateSteps();
}

$("jobsClear").addEventListener("click", () => {
  const finished = state.jobs.filter((j) => isSuccessful(j.status) || isFailed(j.status));
  if (!finished.length) return;
  if (!window.confirm(`Oublier ${finished.length} job(s) terminé(s) ou en échec de cette liste ? Ils restent sur le serveur (liste « Jobs du serveur »).`)) return;
  for (const job of finished) state.results.delete(job.jobId);
  state.jobs = state.jobs.filter((j) => !finished.includes(j));
  saveJobs();
  renderJobs();
  renderServerJobs();
});

function renderResult(result) {
  const wrap = el("div");
  const list = el("ul", { className: "files" });
  for (const file of result.files) {
    const link = el("a", { href: file.href, textContent: file.filename, rel: "noopener", target: "_blank" });
    link.setAttribute("download", file.filename);
    link.className = "fr-link fr-icon-download-line fr-link--icon-left";
    list.append(el("li", {}, link, el("span", { className: "fr-hint-text", textContent: file.size ? ` — ${formatSize(file.size)}` : "" })));
  }
  wrap.append(list);
  if (result.summary) wrap.append(el("p", { className: "fr-text--sm", textContent: result.summary }));
  for (const warning of result.warnings) {
    wrap.append(el("div", { className: "fr-alert fr-alert--warning fr-alert--sm fr-mb-1w" }, el("p", { textContent: warning })));
  }
  return wrap;
}

const formatSize = (bytes) =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} Go` : bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} Mo` : `${Math.max(1, Math.round(bytes / 1e3))} Ko`;

async function refreshJob(jobId, interactive = false) {
  const job = state.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  try {
    const fresh = await api.getJob(jobId);
    job.status = fresh.status;
    job.message = fresh.message;
    saveJobs();
    renderJobs();
  } catch (error) {
    if (interactive || (error instanceof ApiError && error.status === 401)) showError(error);
  }
}

async function cancelJob(job) {
  try {
    await api.deleteJob(job.jobId);
    forgetJob(job.jobId);
  } catch (error) {
    showError(error);
  }
}

function forgetJob(jobId) {
  state.jobs = state.jobs.filter((j) => j.jobId !== jobId);
  state.results.delete(jobId);
  saveJobs();
  renderJobs();
  renderServerJobs();
}

async function showResults(job) {
  try {
    const results = await api.getJobResults(job.jobId);
    if (!results.extractDataHref) throw new Error("Le service n'a renvoyé aucun fichier de résultat pour ce job.");
    const entries = await api.resolveDownloadFiles(results.extractDataHref);
    const files = await Promise.all(entries.map(async (entry) => ({ ...entry, size: await api.fileSize(entry.href) })));
    const meta = files.find((f) => f.isMetadata);
    const info = meta ? await api.fetchJson(meta.href) : null;
    const warnings = [];
    let summary = "";
    if (info && Array.isArray(info.relations)) {
      const ok = info.relations.filter((r) => Object.values(r)[0] === "SUCCESS").length;
      const seconds = info.begin_timestamp && info.end_timestamp ? (Date.parse(info.end_timestamp) - Date.parse(info.begin_timestamp)) / 1000 : null;
      summary = `${ok}/${info.relations.length} table(s) en succès côté serveur${seconds !== null ? `, traitées en ${seconds.toFixed(0)} s` : ""}.`;
      // Heuristiques (pas des certitudes) : cas observé d'un GeoPackage valide mais sans aucune couche
      // alors que le service annonçait un succès en quelques secondes pour 10 tables.
      if (seconds !== null && seconds < 5 && info.relations.length >= 5) {
        warnings.push(`Terminé en ${seconds.toFixed(0)} s pour ${info.relations.length} tables : très rapide pour un vrai traitement, le résultat pourrait être vide.`);
      }
      const data = files.find((f) => !f.isMetadata && f.size);
      if (data && info.relations.length >= 3 && data.size < 400 * 1024) {
        warnings.push(`Fichier très petit (${formatSize(data.size)}) pour ${info.relations.length} tables : un GeoPackage vide en fait ~100 Ko. Ouvrez-le pour vérifier avant de conclure.`);
      }
    }
    state.results.set(job.jobId, { files, summary, warnings });
    renderJobs();
    renderServerJobs();
  } catch (error) {
    showError(error);
  }
}

$("jobsRefresh").addEventListener("click", () => pollJobs(true));

async function pollJobs(interactive = false) {
  if (!auth.authenticated) return;
  for (const job of [...state.jobs]) {
    if (isRunning(job.status) || !job.status) await refreshJob(job.jobId, interactive);
  }
}
setInterval(() => pollJobs(false), POLL_INTERVAL_MS);

// ---- Jobs du serveur : liste complète chargée une fois, paginée côté navigateur (sans appel réseau).
const SERVER_PAGE_SIZE = 5;
const server = { jobs: [], loaded: false, filter: "all", page: 1 };

for (const [key, { label }] of Object.entries(JOB_FILTERS)) $("serverFilter").append(el("option", { value: key, textContent: label }));
$("serverFilter").addEventListener("change", () => {
  server.filter = $("serverFilter").value;
  server.page = 1;
  renderServerJobs();
});
$("serverLoad").addEventListener("click", () => loadServerJobs(true));

const processTitle = (processId) => (state.processes.find((p) => p.id === processId) || {}).title || processId;

async function loadServerJobs(interactive = false) {
  if (!auth.authenticated) return;
  $("serverStatus").textContent = "Chargement des jobs du serveur…";
  try {
    server.jobs = await api.listAllJobs();
    server.loaded = true;
    server.page = 1;
    renderServerJobs();
  } catch (error) {
    $("serverStatus").textContent = "Impossible de lister les jobs du serveur.";
    if (interactive) showError(error);
  }
}

function resetServerJobs() {
  server.jobs = [];
  server.loaded = false;
  $("serverStatus").textContent = "Connectez-vous pour lister les jobs du serveur.";
  renderServerJobs();
}

function followJob(job) {
  if (state.jobs.some((j) => j.jobId === job.jobId)) return;
  state.jobs.push({
    jobId: job.jobId, processId: job.processId, title: processTitle(job.processId), status: job.status,
    message: job.message, created: job.created || new Date().toISOString(), tables: 0, comment: "Suivi depuis la liste du serveur",
  });
  state.jobs = sortNewestFirst(state.jobs);
  saveJobs();
  renderJobs();
  renderServerJobs();
}

function serverJobCard(job) {
  const status = String(job.status || "").toLowerCase();
  const date = job.created ? new Date(job.created).toLocaleString("fr-FR") : "date inconnue";
  const meta = el("p", { className: "fr-text--sm fr-mb-1w", textContent: `${job.jobId} · ${date}${job.message ? ` · ${job.message}` : ""}` });
  const { actions, button } = jobActions();
  if (isSuccessful(status)) button("Résultats", () => showResults(job), false);
  if (!state.jobs.some((j) => j.jobId === job.jobId)) button("Suivre", () => followJob(job));
  const card = el("div", { className: "job" }, jobHeader(processTitle(job.processId), status), meta);
  if (actions.children.length) card.append(actions);
  const result = state.results.get(job.jobId);
  if (result) card.append(renderResult(result));
  return card;
}

function renderServerJobs({ focusPager = false } = {}) {
  const box = $("serverJobs");
  box.replaceChildren();
  if (!server.loaded) {
    $("serverPager").hidden = true;
    return;
  }
  const view = paginateJobs(server.jobs, { filter: server.filter, page: server.page, pageSize: SERVER_PAGE_SIZE });
  server.page = view.page;
  $("serverStatus").textContent = !view.count
    ? (view.total ? "Aucun job ne correspond à ce statut." : "Aucun job sur le serveur.")
    : `Jobs ${view.from} à ${view.to} sur ${view.count}${view.count !== view.total ? ` (${view.total} au total)` : ""}.`;
  for (const job of view.items) box.append(serverJobCard(job));
  renderPager($("serverPager"), view, (page) => { server.page = page; renderServerJobs({ focusPager: true }); }, focusPager);
}

// ------------------------------------------------------------------ Étapes repliables
// Chaque étape est un accordéon DSFR avec un badge d'état. « Continuer » referme l'étape et ouvre la
// suivante ; une étape sans objet est désactivée (bouton `disabled`, donc aussi hors clavier).
function collapseOf(bodyId) {
  try {
    return window.dsfr && $(bodyId) ? window.dsfr($(bodyId)).collapse : null;
  } catch {
    return null;
  }
}

// Le JavaScript du DSFR démarre après le chargement (il pose alors data-fr-js sur <html>) et
// réinitialise l'état des accordéons : on attend ce signal, en réessayant brièvement.
const dsfrStarted = () => document.documentElement.getAttribute("data-fr-js") === "true";
// Une demande faite pendant la transition d'un panneau (≈ 1 s) peut être ignorée : on revérifie une fois
// après coup, sauf si une demande plus récente est arrivée entre-temps pour la même étape.
const wanted = new Map();
function setStepOpen(bodyId, open, tries = 80, verify = true) {
  if (verify) wanted.set(bodyId, open);
  else if (wanted.get(bodyId) !== open) return; // vérification périmée
  const collapse = dsfrStarted() ? collapseOf(bodyId) : null;
  if (!collapse) {
    if (tries > 0) setTimeout(() => setStepOpen(bodyId, open, tries - 1, verify), 100);
    return;
  }
  if (open && !collapse.isDisclosed) collapse.disclose();
  if (!open && collapse.isDisclosed) collapse.conceal();
  if (verify) setTimeout(() => setStepOpen(bodyId, open, 0, false), 1200);
}

function scrollToStep(stepId) {
  setTimeout(() => $(stepId).scrollIntoView({ behavior: "smooth", block: "start" }), 250);
}

function advanceFrom(bodyId, nextBodyId) {
  setStepOpen(bodyId, false);
  setStepOpen(nextBodyId, true);
  scrollToStep(nextBodyId.replace(/Body$/, ""));
}
for (const button of document.querySelectorAll("button[data-next]")) {
  button.addEventListener("click", () => advanceFrom(button.closest(".fr-collapse").id, button.dataset.next));
}

function setStep(name, { tone, text, enabled = true }) {
  const badge = $(`${name}Badge`);
  badge.className = `fr-badge fr-badge--sm fr-badge--no-icon fr-badge--${tone} step-badge`;
  badge.textContent = text;
  const button = $(`${name}Btn`);
  button.disabled = !enabled;
  if (!enabled) setStepOpen(`${name}Body`, false);
}

const shorten = (text, max = 40) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

function updateSteps() {
  const entries = [...state.selection.values()];
  const missingForParams = entries.some((e) => e.process.inputs.some((f) => f.id === "relations") && e.checkedTables.size === 0);

  if (!auth.token) setStep("stepAuth", { tone: "warning", text: "À faire" });
  else if (auth.isExpired) setStep("stepAuth", { tone: "error", text: "Jeton expiré" });
  else setStep("stepAuth", { tone: "success", text: "Connecté" });

  setStep("stepExtent", state.extent
    ? { tone: "success", text: shorten(state.extent.label.replace(" (préréglage)", "")) }
    : { tone: "warning", text: "À choisir" });

  if (entries.length) setStep("stepProduct", { tone: "success", text: shorten(entries[0].process.title.replace(/^Extraction Vecteur depuis /, ""), 36) });
  else setStep("stepProduct", auth.authenticated ? { tone: "warning", text: "À choisir" } : { tone: "info", text: "Connexion requise" });

  if (!entries.length) {
    setStep("stepParams", { tone: "info", text: "Choisissez un produit", enabled: false });
    setStep("stepRequest", { tone: "info", text: "Choisissez un produit", enabled: false });
  } else {
    const tables = entries.reduce((n, e) => n + e.checkedTables.size, 0);
    setStep("stepParams", missingForParams
      ? { tone: "warning", text: "À compléter" }
      : { tone: "success", text: tables ? `${tables} table(s)` : "Prêt" });
    setStep("stepRequest", state.missing.length
      ? { tone: "warning", text: "Incomplet" }
      : { tone: "success", text: "Prête" });
  }

  const running = state.jobs.filter((j) => isRunning(j.status)).length;
  setStep("stepJobs", running
    ? { tone: "info", text: `${running} en cours` }
    : { tone: "info", text: state.jobs.length ? `${state.jobs.length} suivi(s)` : "Aucun" });

  $("authNext").disabled = !auth.authenticated;
  $("extentNext").disabled = !state.extent;
  $("productNext").disabled = !entries.length;
}

// ------------------------------------------------------------------ Démarrage
$("webVersion").textContent = `v${WEB_VERSION}`;
$("repoLink").href = REPO_URL;
if (location.hostname === "localhost" || location.hostname === "127.0.0.1") {
  window.__gpf = { state, auth, api, refreshRequest }; // aide au débogage local uniquement
}

(async () => {
  try {
    const token = await handleRedirect();
    if (token) auth.setToken(token, true);
  } catch (error) {
    showError(error);
  }
  renderPredicates();
  refreshAuthUI();
  renderJobs();
  renderServerJobs();
  setStepOpen(auth.authenticated ? "stepExtentBody" : "stepAuthBody", true);
  if (auth.authenticated) {
    loadProducts();
    loadServerJobs();
  }
})();
