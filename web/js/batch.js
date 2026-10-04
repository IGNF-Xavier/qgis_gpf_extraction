// Découpage d'une extraction en plusieurs jobs successifs (« lots » de tables) — équivalent de
// `gpf_extraction/core/job_batch.py`.
//
// Le contour est recopié dans le filtre de chaque table : plus on coche de tables, plus il faut le réduire
// pour que la requête reste légère (cf. extent-fit.js), jusqu'à retomber sur des rectangles ou la bbox.
// Plutôt que de dégrader l'emprise, on répartit les tables en plusieurs jobs : chacun garde un contour
// fidèle. Le service n'accepte qu'un job à la fois (HTTP 429) : les lots partent donc successivement, le
// suivant quand le précédent est terminé — tant que cette page reste ouverte.

/** Un contour est « fidèle » jusqu'à cette tolérance de simplification (mètres). */
export const FAITHFUL_MAX_TOLERANCE_M = 50;
/** Nombre maximal de lots proposés : chaque job dure de l'ordre de plusieurs minutes. */
export const MAX_BATCHES = 8;

export function isFaithful(fit) {
  if (!fit) return true; // pas de contour (rectangle) : rien à dégrader
  if (fit.kind === "precise") return true;
  return fit.kind === "simplified" && fit.toleranceM <= FAITHFUL_MAX_TOLERANCE_M;
}

/**
 * Nombre de lots à proposer (1 = pas de découpage).
 * @param {number} tableCount  nombre de tables à extraire (avec géométrie)
 * @param {(n: number) => object|null} fitFor  contour retenu si une requête porte sur n tables
 */
export function planBatches(tableCount, fitFor) {
  if (tableCount < 2 || isFaithful(fitFor(tableCount))) return 1;
  for (let batches = 2; batches <= Math.min(MAX_BATCHES, tableCount); batches++) {
    if (isFaithful(fitFor(Math.ceil(tableCount / batches)))) return batches;
  }
  return 1;
}

/** Répartit `items` en `batches` groupes consécutifs de tailles presque égales. */
export function splitEvenly(items, batches) {
  if (!items.length) return [[]];
  batches = Math.max(1, Math.min(batches, items.length));
  const base = Math.floor(items.length / batches);
  const extra = items.length % batches;
  const out = [];
  let start = 0;
  for (let i = 0; i < batches; i++) {
    const size = base + (i < extra ? 1 : 0);
    out.push(items.slice(start, start + size));
    start += size;
  }
  return out;
}
