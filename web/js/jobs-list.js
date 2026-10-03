// Liste paginée des jobs du serveur : tri, filtre par statut et découpage en pages, côté
// navigateur. Le service renvoie les jobs du plus ancien au plus récent, sans total ni tri
// possible ; on charge donc la liste complète une fois, puis on navigue sans appel réseau.

import { isRunning, isSuccessful } from "./models.js";

const upper = (status) => String(status ?? "").toUpperCase();

export const JOB_FILTERS = {
  all: { label: "Tous les statuts", test: () => true },
  successful: { label: "Terminés", test: (job) => isSuccessful(job.status) },
  running: { label: "En cours ou en attente", test: (job) => isRunning(job.status) },
  failed: { label: "En échec", test: (job) => upper(job.status) === "FAILED" },
  dismissed: { label: "Annulés", test: (job) => upper(job.status) === "DISMISSED" },
};

// Du plus récent au plus ancien ; les jobs sans date en dernier.
export function sortNewestFirst(jobs) {
  return [...jobs].sort((a, b) => {
    if (!a.created && !b.created) return 0;
    if (!a.created) return 1;
    if (!b.created) return -1;
    return String(b.created).localeCompare(String(a.created));
  });
}

/**
 * @returns {{ items: object[], total: number, count: number, page: number, pages: number, from: number, to: number }}
 *   `count` : jobs après filtre ; `total` : jobs avant filtre ; `from`/`to` : bornes affichées (1-based, 0 si vide).
 */
export function paginateJobs(jobs, { filter = "all", page = 1, pageSize = 5 } = {}) {
  const test = (JOB_FILTERS[filter] || JOB_FILTERS.all).test;
  const filtered = sortNewestFirst(jobs).filter(test);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(Math.max(1, Math.trunc(page) || 1), pages);
  const start = (current - 1) * pageSize;
  const items = filtered.slice(start, start + pageSize);
  return {
    items, total: jobs.length, count: filtered.length, page: current, pages,
    from: items.length ? start + 1 : 0, to: start + items.length,
  };
}

// Numéros de pages à afficher : 1, la page courante et ses voisines, la dernière ; "…" pour
// chaque trou. Ex. (6, 20) -> [1, "…", 5, 6, 7, "…", 20].
export function pageWindow(page, pages) {
  const wanted = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const numbers = [...wanted].sort((a, b) => a - b);
  const out = [];
  for (const n of numbers) {
    if (out.length && n - out[out.length - 1] > 1) {
      out.push(n - out[out.length - 1] === 2 ? n - 1 : "…");
    }
    out.push(n);
  }
  return out;
}
