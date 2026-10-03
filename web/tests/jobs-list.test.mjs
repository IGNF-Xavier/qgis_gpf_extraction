import test from "node:test";
import assert from "node:assert/strict";
import { pageWindow, paginateJobs, sortNewestFirst } from "../js/jobs-list.js";

const job = (id, status, created) => ({ jobId: id, status, created });
const sample = [
  job("old", "dismissed", "2026-08-15T10:00:00Z"),
  job("nodate", "successful", null),
  job("new", "successful", "2026-10-03T08:49:15Z"),
  job("mid", "failed", "2026-09-01T10:00:00Z"),
  job("run", "running", "2026-10-03T09:00:00Z"),
];

test("tri : du plus récent au plus ancien, sans date en dernier, sans modifier l'entrée", () => {
  assert.deepEqual(sortNewestFirst(sample).map((j) => j.jobId), ["run", "new", "mid", "old", "nodate"]);
  assert.equal(sample[0].jobId, "old");
});

test("pagination : pages de la taille demandée, bornes et total", () => {
  const first = paginateJobs(sample, { pageSize: 2, page: 1 });
  assert.deepEqual(first.items.map((j) => j.jobId), ["run", "new"]);
  assert.deepEqual([first.pages, first.count, first.total, first.from, first.to], [3, 5, 5, 1, 2]);
  const last = paginateJobs(sample, { pageSize: 2, page: 3 });
  assert.deepEqual(last.items.map((j) => j.jobId), ["nodate"]);
  assert.deepEqual([last.from, last.to], [5, 5]);
});

test("pagination : page hors limite ramenée dans l'intervalle, liste vide gérée", () => {
  assert.equal(paginateJobs(sample, { pageSize: 2, page: 99 }).page, 3);
  assert.equal(paginateJobs(sample, { pageSize: 2, page: -4 }).page, 1);
  assert.equal(paginateJobs(sample, { pageSize: 2, page: "abc" }).page, 1);
  const empty = paginateJobs([], { pageSize: 5 });
  assert.deepEqual([empty.items.length, empty.pages, empty.page, empty.from, empty.to], [0, 1, 1, 0, 0]);
});

test("filtres par statut : le compte tient compte du filtre, le total non", () => {
  const ok = paginateJobs(sample, { filter: "successful", pageSize: 5 });
  assert.deepEqual(ok.items.map((j) => j.jobId), ["new", "nodate"]);
  assert.equal(ok.total, 5);
  assert.equal(paginateJobs(sample, { filter: "running" }).count, 1);
  assert.equal(paginateJobs(sample, { filter: "failed" }).count, 1);
  assert.equal(paginateJobs(sample, { filter: "dismissed" }).count, 1);
  assert.equal(paginateJobs(sample, { filter: "inconnu" }).count, 5);
});

test("fenêtre de pages : 1, voisines de la page courante, dernière, « … » pour les trous", () => {
  assert.deepEqual(pageWindow(1, 1), [1]);
  assert.deepEqual(pageWindow(2, 5), [1, 2, 3, 4, 5]);
  assert.deepEqual(pageWindow(6, 20), [1, "…", 5, 6, 7, "…", 20]);
  assert.deepEqual(pageWindow(1, 20), [1, 2, "…", 20]);
  assert.deepEqual(pageWindow(20, 20), [1, "…", 19, 20]);
  assert.deepEqual(pageWindow(4, 6), [1, 2, 3, 4, 5, 6]); // un trou d'une seule page : on affiche le numéro
});
