// Contrôleur de l'interface web : relie les modules purs (API, géométrie, construction de
// requête) au DOM. Tout texte venant de l'API est inséré via `textContent` (jamais en HTML).

import { ExtractionApi, ApiError, describeApiError } from "./api.js";
import { AuthState, handleRedirect, oidcConfigured, startLogin } from "./auth.js";
import {
  DEFAULT_PREDICATES, PREDICATE_SQL, buildBody, buildRelations, curlCommand, initialValue,
  isMultilayerFormat, missingForLaunch, preferredEnumValue,
} from "./builder.js";
import { API_BASE, POLL_INTERVAL_MS, REPO_URL, WEB_VERSION, WMTS_BASE } from "./config.js";
import {
  bboxToPolygon, domCoverageWarning, geometryBounds, loadPresets, makeTransformFrom4326,
  reprojectGeometry, searchAdmin, srid, transformBbox,
} from "./geo.js";
import { fieldEnum, fieldType, isFailed, isRunning, isSuccessful } from "./models.js";

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) node.append(child);
  return node;
};
const store = {
  get: (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set: (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota ou stockage indisponible */ } },
};

const auth = new AuthState();
const api = new ExtractionApi({ getToken: () => auth.token });

const state = {
  processes: [], process: null, storedData: null,
  extent: null,           // { label, geometry (EPSG:4326), bbox, code, precise }
  checkedTables: new Set(), predicates: new Set(DEFAULT_PREDICATES),
  values: {}, body: null,
  jobs: store.get("gpf_web_jobs", []), ignored: new Set(store.get("gpf_web_ignored_jobs", [])),
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
  $("errorDialog").showModal();
}
$("errorCopy").addEventListener("click", (e) => copyText($("errorReport").value, e.currentTarget));

// ------------------------------------------------------------------ 1. Connexion
function refreshAuthUI() {
  const status = $("authStatus");
  status.className = "status";
  if (!auth.token) {
    status.textContent = "Non connecté : sans jeton, la recherche d'emprise et la construction de la requête fonctionnent, mais pas la liste des produits ni le lancement.";
  } else if (auth.isExpired) {
    status.textContent = "Jeton expiré : collez-en un nouveau.";
    status.classList.add("bad");
  } else {
    const left = auth.secondsLeft;
    status.textContent = left === null ? "Jeton en place (expiration inconnue)." : `Jeton valide encore ${Math.max(1, Math.round(left / 60))} min.`;
    status.classList.add("ok");
  }
  $("oidcLogin").hidden = !oidcConfigured();
  refreshRequest();
}
auth.onChange = () => {
  refreshAuthUI();
  if (auth.authenticated) loadProducts();
};
$("tokenUse").addEventListener("click", () => {
  auth.setToken($("tokenInput").value, $("tokenRemember").checked);
  $("tokenInput").value = "";
});
$("tokenClear").addEventListener("click", () => {
  auth.clear();
  state.processes = [];
  renderProducts();
});
$("oidcLogin").addEventListener("click", () => startLogin());
setInterval(refreshAuthUI, 30000);

// ------------------------------------------------------------------ 2. Emprise
const map = L.map("map").setView([46.6, 2.5], 5);
const tile = (layer, format) =>
  `${WMTS_BASE}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=normal&FORMAT=${format}` +
  "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}";
const planIgn = L.tileLayer(tile("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png"), { maxZoom: 19, attribution: "© IGN / Géoplateforme" }).addTo(map);
const ortho = L.tileLayer(tile("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"), { maxZoom: 19, attribution: "© IGN / Géoplateforme" });
L.control.layers({ "Plan IGN": planIgn, "Photographies aériennes": ortho }).addTo(map);
let extentLayer = null;

function setExtent({ label, geometry, code = "", precise }) {
  const bbox = geometryBounds(geometry);
  state.extent = { label, geometry, bbox, code, precise };
  const [x0, y0, x1, y1] = bbox;
  // Le résumé est toujours la bounding box ; le contour précis (s'il existe) est ce qui
  // part réellement dans le filtre — d'où la précision ci-dessous.
  $("extentLabel").textContent =
    `Emprise « ${label} » (EPSG:4326) : ${x0.toFixed(4)}, ${y0.toFixed(4)} → ${x1.toFixed(4)}, ${y1.toFixed(4)}` +
    (precise ? " (rectangle englobant affiché à titre indicatif ; le contour précis est utilisé pour le filtre envoyé au serveur)" : "");
  if (extentLayer) extentLayer.remove();
  extentLayer = L.geoJSON(geometry, { style: { color: "#000091", weight: 2, fillOpacity: 0.12 } }).addTo(map);
  map.fitBounds([[y0, x0], [y1, x1]], { padding: [24, 24] });
  refreshRequest();
}

function selectAdmin(result) {
  state.adminResult = result;
  setExtent({ label: result.label, geometry: result.geometry, code: result.code, precise: true });
}

function setTab(name) {
  const search = name === "search";
  $("tabSearch").setAttribute("aria-selected", String(search));
  $("tabBbox").setAttribute("aria-selected", String(!search));
  $("paneSearch").hidden = !search;
  $("paneBbox").hidden = search;
}
$("tabSearch").addEventListener("click", () => setTab("search"));
$("tabBbox").addEventListener("click", () => setTab("bbox"));

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
      if (!results.length) list.append(el("li", { className: "muted", textContent: "Aucun résultat." }));
      for (const result of results) {
        const button = el("button", { type: "button", textContent: result.label });
        button.addEventListener("click", () => {
          for (const b of list.querySelectorAll("button")) b.removeAttribute("aria-selected");
          button.setAttribute("aria-selected", "true");
          selectAdmin(result);
        });
        list.append(el("li", {}, button));
      }
    } catch (error) {
      list.append(el("li", { className: "muted", textContent: `Recherche indisponible (${error.message}).` }));
    }
  }, 350);
});

loadPresets().then((presets) => {
  for (const preset of presets) {
    const button = el("button", { type: "button", textContent: preset.label.replace(" (préréglage)", ""), title: "Préréglage" });
    button.addEventListener("click", () => selectAdmin(preset));
    $("presets").append(button);
  }
});

// Rectangle dessiné à la souris (ou saisi à la main) : le rectangle EST l'emprise utilisée.
let drawing = false;
let drawStart = null;
let drawRect = null;
$("drawBbox").addEventListener("click", () => {
  drawing = true;
  map.dragging.disable();
  map.getContainer().style.cursor = "crosshair";
  $("drawBbox").textContent = "Cliquez-glissez sur la carte…";
});
map.on("mousedown", (e) => {
  if (!drawing) return;
  drawStart = e.latlng;
  drawRect = L.rectangle([drawStart, drawStart], { color: "#ce0500", weight: 2 }).addTo(map);
});
map.on("mousemove", (e) => { if (drawing && drawStart) drawRect.setBounds([drawStart, e.latlng]); });
map.on("mouseup", (e) => {
  if (!drawing || !drawStart) return;
  const b = L.latLngBounds(drawStart, e.latlng);
  drawing = false;
  drawStart = null;
  drawRect.remove();
  drawRect = null;
  map.dragging.enable();
  map.getContainer().style.cursor = "";
  $("drawBbox").textContent = "Dessiner un rectangle sur la carte";
  if (b.getWest() === b.getEast() || b.getSouth() === b.getNorth()) return;
  applyBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
});
function applyBbox(bbox) {
  [$("bboxXmin").value, $("bboxYmin").value, $("bboxXmax").value, $("bboxYmax").value] = bbox.map((n) => +n.toFixed(6));
  state.adminResult = null;
  setExtent({ label: "BBox", geometry: bboxToPolygon(bbox), precise: false });
}
$("bboxApply").addEventListener("click", () => {
  const [x0, y0, x1, y1] = ["bboxXmin", "bboxYmin", "bboxXmax", "bboxYmax"].map((id) => parseFloat($(id).value));
  if ([x0, y0, x1, y1].some(Number.isNaN) || x0 >= x1 || y0 >= y1) {
    $("extentLabel").textContent = "Rectangle invalide : renseignez ouest < est et sud < nord.";
    return;
  }
  applyBbox([x0, y0, x1, y1]);
});

// ------------------------------------------------------------------ 3. Produit
async function loadProducts() {
  if (!auth.authenticated) return;
  $("productStatus").textContent = "Chargement des produits…";
  try {
    state.processes = await api.listProcesses();
    $("productStatus").textContent = `${state.processes.length} produit(s) disponible(s).`;
    renderProducts();
  } catch (error) {
    $("productStatus").textContent = "Impossible de lister les produits.";
    showError(error);
  }
}

const BDTOPO_HINTS = ["bdtopo", "bd topo", "bd_topo"];
function renderProducts() {
  const filter = $("productFilter").value.trim().toLowerCase();
  const select = $("productList");
  select.replaceChildren();
  const sorted = [...state.processes].sort((a, b) => {
    const rank = (p) => (BDTOPO_HINTS.some((h) => p.title.toLowerCase().includes(h)) ? 0 : 1);
    return rank(a) - rank(b) || a.title.localeCompare(b.title);
  });
  for (const process of sorted) {
    if (filter && !`${process.title} ${process.id} ${process.description}`.toLowerCase().includes(filter)) continue;
    const option = el("option", { value: process.id, textContent: process.title, title: process.description });
    option.selected = state.process && state.process.id === process.id;
    select.append(option);
  }
}
$("productFilter").addEventListener("input", renderProducts);
$("productList").addEventListener("change", () => selectProduct($("productList").value));

async function selectProduct(id) {
  $("productStatus").textContent = "Chargement du produit…";
  try {
    const process = await api.getProcess(id);
    let storedData = null;
    if (process.describedByUrl) {
      try {
        storedData = await api.getStoredData(process.describedByUrl);
      } catch (error) {
        $("productStatus").textContent = "Description de la donnée stockée indisponible : liste des tables vide (utilisez le mode JSON avancé).";
        console.warn(error);
      }
    }
    // Le titre de la liste fait foi (celui que l'utilisateur a cliqué, et sur lequel repose
    // l'avertissement de couverture DOM), comme dans le plugin.
    const summary = state.processes.find((p) => p.id === id);
    if (summary && summary.title) process.title = summary.title;
    state.process = process;
    state.storedData = storedData;
    state.checkedTables = new Set();
    state.values = {};
    $("productStatus").textContent = "";
    $("productDescription").textContent = process.description;
    buildParams();
    refreshRequest();
  } catch (error) {
    $("productStatus").textContent = "Impossible de charger ce produit.";
    showError(error);
  }
}

// ------------------------------------------------------------------ 4. Paramètres
const FIELD_LABELS = { append: "Fusionner toutes les tables en un seul fichier" };
const COMMON_SRS = ["EPSG:4326", "EPSG:2154", "EPSG:3857", "EPSG:4171"];
const controls = {}; // id -> élément de saisie

function buildParams() {
  const process = state.process;
  $("params").hidden = false;
  $("request").hidden = false;

  // Prédicats (cases à cocher combinées en OU ; au moins un reste toujours coché).
  const predicates = $("predicates");
  predicates.replaceChildren();
  for (const name of Object.keys(PREDICATE_SQL)) {
    const box = el("input", { type: "checkbox", checked: state.predicates.has(name) });
    box.addEventListener("change", () => {
      if (box.checked) state.predicates.add(name);
      else state.predicates.delete(name);
      if (!state.predicates.size) {
        state.predicates.add(DEFAULT_PREDICATES[0]);
        for (const other of predicates.querySelectorAll("input")) other.checked = other.parentElement.textContent.trim() === DEFAULT_PREDICATES[0];
      }
      refreshRequest();
    });
    predicates.append(el("label", {}, box, name));
  }

  // Tables (input `relations`).
  const hasRelations = process.inputs.some((f) => f.id === "relations");
  $("relationsBox").hidden = !hasRelations;
  $("tableFilter").value = "";
  renderTables();

  // Champs génériques.
  const fields = $("genericFields");
  fields.replaceChildren();
  for (const key of Object.keys(controls)) delete controls[key];
  for (const field of process.inputs) {
    if (field.id === "relations") continue;
    const node = buildField(field);
    if (node) fields.append(node);
  }
  syncAppendWithFormat(true);
}

function buildField(field) {
  const label = FIELD_LABELS[field.id.toLowerCase()] || field.title || field.id;
  const wrap = el("label", { title: field.description }, label + (field.required ? " *" : ""));
  let input;
  const e = fieldEnum(field);
  const type = fieldType(field);

  if (field.id.toLowerCase() === "srs") {
    const native = state.storedData && state.storedData.srs;
    const options = [...new Set([native, ...COMMON_SRS].filter(Boolean))];
    input = el("input", { type: "text", value: native || "" });
    input.setAttribute("list", "srsOptions"); // `list` est en lecture seule côté DOM : attribut obligatoire
    const list = el("datalist", { id: "srsOptions" });
    for (const code of options) list.append(el("option", { value: code, label: code === native ? "natif de la donnée" : "" }));
    wrap.append(input, list);
    wrap.append(el("small", { className: "muted", textContent: "Projection de sortie du résultat (indépendante du filtre spatial)." }));
    input.addEventListener("input", () => { state.values.srs = input.value.trim() || undefined; refreshRequest(); });
    state.values.srs = native || undefined;
  } else if (e) {
    input = el("select");
    if (!field.required) input.append(el("option", { value: "", textContent: "(non spécifié)" }));
    for (const value of e) input.append(el("option", { value: String(value), textContent: String(value) }));
    const initial = field.required ? preferredEnumValue(e) : initialValue(field);
    input.value = initial === undefined ? "" : String(initial);
    state.values[field.id] = input.value || undefined;
    input.addEventListener("change", () => {
      state.values[field.id] = input.value || undefined;
      if (field.id === "format") syncAppendWithFormat();
      refreshRequest();
    });
    wrap.append(input);
  } else if (type === "boolean") {
    input = el("input", { type: "checkbox", checked: Boolean(initialValue(field)) });
    state.values[field.id] = input.checked;
    input.addEventListener("change", () => { state.values[field.id] = input.checked; refreshRequest(); });
    wrap.className = "inline";
    wrap.prepend(input);
  } else if (type === "integer" || type === "number") {
    input = el("input", { type: "number", step: type === "integer" ? "1" : "any" });
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
      state.values[field.id] = Number.isNaN(n) || (n === 0 && !field.required) ? undefined : n;
    };
    read();
    input.addEventListener("input", () => { read(); refreshRequest(); });
    wrap.append(input);
  } else if (type === "" || type === "string") {
    input = el("input", { type: "text" });
    if (typeof initialValue(field) === "string") input.value = initialValue(field);
    state.values[field.id] = input.value.trim() || undefined;
    input.addEventListener("input", () => { state.values[field.id] = input.value.trim() || undefined; refreshRequest(); });
    wrap.append(input);
  } else {
    return null; // array / object : le mode JSON avancé reste le moyen de le renseigner
  }
  controls[field.id] = input;
  return wrap;
}

// `append` n'a de sens que pour les formats multi-couches (GPKG, PGDUMP) ; coché par
// défaut pour eux (un seul fichier résultat), décoché et inactif sinon.
function syncAppendWithFormat(initial = false) {
  const append = controls.append;
  const format = controls.format;
  if (!append || !format) return;
  const ok = isMultilayerFormat(format.value);
  const wasEnabled = !append.disabled;
  append.disabled = !ok;
  if (!ok) append.checked = false;
  else if (initial || !wasEnabled) append.checked = true; // repasse à un format multi-couches : recoché
  state.values.append = append.checked;
}

function renderTables() {
  const box = $("tableList");
  box.replaceChildren();
  const tables = (state.storedData && state.storedData.tables) || [];
  const filter = $("tableFilter").value.trim().toLowerCase();
  for (const table of tables) {
    if (filter && !table.name.toLowerCase().includes(filter)) continue;
    const checkbox = el("input", { type: "checkbox", checked: state.checkedTables.has(table.name) });
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.checkedTables.add(table.name);
      else state.checkedTables.delete(table.name);
      refreshRequest();
    });
    box.append(el("label", {}, checkbox, table.name + (table.geometryAttribute ? "" : " — sans géométrie")));
  }
  if (!tables.length) box.append(el("span", { className: "muted", textContent: "Aucune table décrite pour ce produit." }));
  updateTableCount();
}
function updateTableCount() {
  const total = (state.storedData && state.storedData.tables.length) || 0;
  $("tableCount").textContent = `${state.checkedTables.size}/${total} table(s) sélectionnée(s)`;
}
$("tableFilter").addEventListener("input", renderTables);
const setAllTables = (checked) => {
  const tables = (state.storedData && state.storedData.tables) || [];
  const filter = $("tableFilter").value.trim().toLowerCase();
  for (const table of tables) {
    if (filter && !table.name.toLowerCase().includes(filter)) continue;
    if (checked) state.checkedTables.add(table.name);
    else state.checkedTables.delete(table.name);
  }
  renderTables();
  refreshRequest();
};
$("tablesAll").addEventListener("click", () => setAllTables(true));
$("tablesNone").addEventListener("click", () => setAllTables(false));

// ------------------------------------------------------------------ 5. Requête et lancement
// Emprise exprimée dans la SRID *native de la donnée stockée*, pas dans la projection de
// sortie choisie (cf. builder.js). `null` si la projection native n'est pas gérée.
function extentForFilter() {
  if (!state.extent) return { extent: null, supported: true };
  const nativeCrs = (state.storedData && state.storedData.srs) || "EPSG:4326";
  const transform = makeTransformFrom4326(window.proj4, nativeCrs);
  if (!transform) return { extent: null, supported: false, nativeCrs };
  const { geometry, bbox, precise } = state.extent;
  const extent = { srid: srid(nativeCrs) };
  if (precise) {
    extent.geometry = reprojectGeometry(geometry, transform);
    extent.bbox = geometryBounds(extent.geometry);
  } else {
    extent.bbox = transformBbox(bbox, transform);
  }
  return { extent, supported: true, nativeCrs };
}

function refreshRequest() {
  const title = state.process ? state.process.title : "";
  const warning = domCoverageWarning(title, state.adminResult);
  $("domWarning").textContent = warning ? `⚠ ${warning}` : "";
  $("domWarning").hidden = !warning;
  updateTableCount();

  const process = state.process;
  const missing = missingForLaunch({
    authenticated: auth.authenticated,
    hasProcess: Boolean(process),
    extent: state.extent,
    tablesCount: state.checkedTables.size,
    hasRelationsField: process ? process.inputs.some((f) => f.id === "relations") : false,
    srsSupported: process ? extentForFilter().supported : true,
  });
  $("missing").replaceChildren(...missing.map((m) => el("li", { textContent: m })));
  $("launch").disabled = missing.length > 0 && !$("jsonEdit").checked ? true : !auth.authenticated || !process;
  if (!process) return;

  const { extent } = extentForFilter();
  const tables = ((state.storedData && state.storedData.tables) || []).filter((t) => state.checkedTables.has(t.name));
  const relations = buildRelations(tables, extent, [...state.predicates]);
  state.body = buildBody(process, state.values, relations, state.extent ? state.extent.bbox : null);
  if (!$("jsonEdit").checked) $("requestJson").value = JSON.stringify(state.body, null, 2);
  const kb = new Blob([JSON.stringify(state.body)]).size / 1024;
  $("requestSize").textContent = `Corps de requête : ${kb.toFixed(kb < 10 ? 1 : 0)} Ko.`;
}

$("jsonEdit").addEventListener("change", () => {
  $("requestJson").readOnly = !$("jsonEdit").checked;
  refreshRequest();
});

function currentBody() {
  if (!$("jsonEdit").checked) return state.body;
  try {
    return JSON.parse($("requestJson").value);
  } catch (error) {
    throw new Error(`Le JSON saisi est invalide : ${error.message}`);
  }
}

$("copyJson").addEventListener("click", (e) => copyText($("requestJson").value, e.currentTarget));
$("copyCurl").addEventListener("click", (e) => {
  try {
    copyText(curlCommand(`${API_BASE}/processes/${state.process.id}/execution`, currentBody()), e.currentTarget);
  } catch (error) {
    showError(error);
  }
});

$("launch").addEventListener("click", async () => {
  let body;
  try {
    body = currentBody();
  } catch (error) {
    showError(error);
    return;
  }
  $("launch").disabled = true;
  try {
    const job = await api.execute(state.process.id, body);
    const tablesCount = Object.keys((body.inputs && body.inputs.relations) || {}).length;
    state.jobs.unshift({
      jobId: job.jobId, processId: state.process.id, title: state.process.title,
      status: job.status, message: job.message, created: new Date().toISOString(),
      tables: tablesCount, comment: "",
    });
    saveJobs();
    renderJobs();
    document.getElementById("jobs").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    showError(error, { merge: Boolean(body.inputs && body.inputs.append === true), tables: Object.keys((body.inputs && body.inputs.relations) || {}).length });
  } finally {
    refreshRequest();
  }
});

// ------------------------------------------------------------------ 6. Jobs
const saveJobs = () => {
  store.set("gpf_web_jobs", state.jobs);
  store.set("gpf_web_ignored_jobs", [...state.ignored].slice(-500));
};

const STATUS_LABEL = { successful: "terminé", running: "en cours", accepted: "en attente", failed: "échec", dismissed: "annulé" };

function renderJobs() {
  const box = $("jobList");
  box.replaceChildren();
  if (!state.jobs.length) box.append(el("p", { className: "muted", textContent: "Aucun job suivi dans ce navigateur." }));
  for (const job of state.jobs) {
    const status = String(job.status || "").toLowerCase();
    const pillClass = isSuccessful(status) ? "ok" : isFailed(status) ? "bad" : "running";
    const head = el("header", {}, el("strong", { textContent: job.title || job.processId }),
      el("span", { className: `pill ${pillClass}`, textContent: STATUS_LABEL[status] || status || "inconnu" }));
    const meta = el("p", { className: "muted", textContent: `${job.jobId} · ${new Date(job.created).toLocaleString("fr-FR")}${job.tables ? ` · ${job.tables} table(s)` : ""}${job.message ? ` · ${job.message}` : ""}` });
    const actions = el("div", { className: "row" });
    const button = (text, handler, secondary = true) => {
      const b = el("button", { type: "button", textContent: text, className: secondary ? "secondary" : "" });
      b.addEventListener("click", handler);
      actions.append(b);
    };
    button("Rafraîchir", () => refreshJob(job.jobId, true));
    if (isRunning(status)) button("Annuler", () => cancelJob(job));
    if (isSuccessful(status)) button("Résultats", () => showResults(job), false);
    button("Oublier", () => forgetJob(job.jobId));
    const card = el("div", { className: "job" }, head, meta, actions);
    const result = state.results.get(job.jobId);
    if (result) card.append(renderResult(result));
    box.append(card);
  }
}

function renderResult(result) {
  const wrap = el("div");
  const list = el("ul", { className: "files" });
  for (const file of result.files) {
    const link = el("a", { href: file.href, textContent: file.filename, rel: "noopener", target: "_blank" });
    link.setAttribute("download", file.filename);
    list.append(el("li", {}, link, el("span", { className: "muted", textContent: file.size ? ` — ${formatSize(file.size)}` : "" })));
  }
  wrap.append(list);
  if (result.summary) wrap.append(el("p", { className: "muted", textContent: result.summary }));
  for (const warning of result.warnings) wrap.append(el("p", { className: "alert warn", textContent: `⚠ ${warning}` }));
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
  state.ignored.add(jobId); // sinon « Importer » le ferait réapparaître aussitôt
  state.results.delete(jobId);
  saveJobs();
  renderJobs();
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
  } catch (error) {
    showError(error);
  }
}

$("jobsRefresh").addEventListener("click", () => pollJobs(true));
$("jobsImport").addEventListener("click", async () => {
  try {
    const known = new Set(state.jobs.map((j) => j.jobId));
    const titles = new Map(state.processes.map((p) => [p.id, p.title]));
    for (const job of await api.listJobs()) {
      if (!job.jobId || known.has(job.jobId) || state.ignored.has(job.jobId)) continue;
      state.jobs.push({
        jobId: job.jobId, processId: job.processId, title: titles.get(job.processId) || job.processId,
        status: job.status, message: job.message, created: job.created || new Date().toISOString(), tables: 0,
        comment: "Importé depuis le serveur",
      });
    }
    state.jobs.sort((a, b) => String(b.created).localeCompare(String(a.created)));
    saveJobs();
    renderJobs();
  } catch (error) {
    showError(error);
  }
});

async function pollJobs(interactive = false) {
  if (!auth.authenticated) return;
  for (const job of [...state.jobs]) {
    if (isRunning(job.status) || !job.status) await refreshJob(job.jobId, interactive);
  }
}
setInterval(() => pollJobs(false), POLL_INTERVAL_MS);

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
  refreshAuthUI();
  renderJobs();
  if (auth.authenticated) loadProducts();
})();
