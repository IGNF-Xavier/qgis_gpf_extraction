// Client de l'API d'extraction de la Géoplateforme (OGC API - Processes).

import { API_BASE } from "./config.js";
import { parseAtomEntries, parseJob, parseProcessDetails, parseProcessSummary, parseStoredData } from "./models.js";

// Erreur d'API, avec de quoi rejouer ou signaler la requête telle quelle (jamais le jeton).
export class ApiError extends Error {
  constructor(method, url, status, body, requestBody) {
    super(`${method} ${url} -> HTTP ${status}`);
    this.method = method;
    this.url = url;
    this.status = status;
    this.body = body;
    this.requestBody = requestBody;
  }

  // Texte copiable : requête envoyée + réponse reçue.
  report() {
    const pretty = (text) => {
      try {
        return JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        return text;
      }
    };
    const parts = [`### Requête\n${this.method} ${this.url}`];
    if (this.requestBody !== undefined) parts.push(JSON.stringify(this.requestBody, null, 2));
    parts.push(`\n### Réponse\nHTTP ${this.status}`);
    if (this.body) parts.push(pretty(this.body));
    return parts.join("\n");
  }
}

export class ExtractionApi {
  // `getToken` : fonction renvoyant le jeton Bearer courant ("" si absent).
  constructor({ base = API_BASE, getToken = () => "", fetchImpl = (...a) => fetch(...a) } = {}) {
    this.base = base.replace(/\/$/, "");
    this.getToken = getToken;
    this.fetch = fetchImpl;
  }

  async _request(method, url, { body, accept = "application/json", auth = true } = {}) {
    const headers = { Accept: accept };
    const token = this.getToken();
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await this.fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    } catch (cause) {
      const error = new ApiError(method, url, 0, `Requête impossible (réseau ou CORS) : ${cause.message}`, body);
      error.cause = cause;
      throw error;
    }
    if (!response.ok) throw new ApiError(method, url, response.status, await response.text(), body);
    return response;
  }

  async _json(method, url, options) {
    return (await this._request(method, url, options)).json();
  }

  async listProcesses(limit = 200) {
    const data = await this._json("GET", `${this.base}/processes?page=1&limit=${limit}`);
    const items = Array.isArray(data) ? data : data.processes;
    if (!Array.isArray(items)) throw new ApiError("GET", `${this.base}/processes`, 200, "Réponse inattendue");
    return items.map(parseProcessSummary);
  }

  async getProcess(id) {
    return parseProcessDetails(await this._json("GET", `${this.base}/processes/${id}`));
  }

  // Description de la donnée stockée sous-jacente (liste des tables) : lien `describedby`.
  async getStoredData(url) {
    return parseStoredData(await this._json("GET", url));
  }

  async execute(processId, body) {
    return parseJob(await this._json("POST", `${this.base}/processes/${processId}/execution`, { body }));
  }

  async getJob(jobId) {
    return parseJob(await this._json("GET", `${this.base}/jobs/${jobId}`));
  }

  async listJobs(limit = 50) {
    const data = await this._json("GET", `${this.base}/jobs?limit=${limit}`);
    const items = Array.isArray(data) ? data : data.jobs;
    return Array.isArray(items) ? items.map(parseJob) : [];
  }

  async getJobResults(jobId) {
    const data = await this._json("GET", `${this.base}/jobs/${jobId}/results`);
    const href = (data.extractData && data.extractData.href) || null;
    return { logs: String(data.logs || ""), extractDataHref: href, raw: data };
  }

  async deleteJob(jobId) {
    await this._request("DELETE", `${this.base}/jobs/${jobId}`);
  }

  // Le lien `extractData` renvoie un flux Atom listant les fichiers (sans authentification).
  async resolveDownloadFiles(extractDataHref) {
    const response = await this._request("GET", extractDataHref, { accept: "application/atom+xml", auth: false });
    return parseAtomEntries(await response.text());
  }

  // Taille d'un fichier de résultat, si le serveur l'expose (best-effort : null sinon).
  async fileSize(href) {
    try {
      const response = await this.fetch(href, { method: "HEAD" });
      const length = response.ok ? response.headers.get("content-length") : null;
      return length ? Number(length) : null;
    } catch {
      return null;
    }
  }

  // Petit fichier JSON de métadonnées (extraction.json) : null en cas d'échec.
  async fetchJson(href) {
    try {
      const response = await this.fetch(href);
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }
}

// Libellé lisible d'une erreur pour le bandeau/la boîte de dialogue, avec les pistes
// observées en conditions réelles.
export function describeApiError(error, context = {}) {
  if (!(error instanceof ApiError)) return String(error && error.message ? error.message : error);
  if (error.status === 401) return "Jeton refusé ou expiré : collez-en un nouveau (section Connexion).";
  if (error.status === 429) return "Un seul job simultané est autorisé par compte : attendez la fin du job en cours (ou annulez-le).";
  if (error.status === 0) return error.body;
  let hint = "";
  if (error.status === 500 && context.merge && context.tables > 1) {
    hint =
      " Piste : un HTTP 500 avait été constaté le 2026-09-01 avec la fusion en un seul fichier à 59 tables " +
      "(non reproduit depuis). Essayez sans fusion ou avec moins de tables.";
  }
  return `Le service a refusé la requête (HTTP ${error.status}).${hint}`;
}
