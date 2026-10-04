// Prédicats géométriques du filtre spatial et leur réduction logique — équivalent de
// `gpf_extraction/core/predicates.py`.
//
// Le filtre de chaque table combine les prédicats cochés en OU, et le contour est recopié dans chacun :
// deux prédicats, c'est deux fois le poids. Or tous les prédicats « positifs » entraînent l'intersection :
//   Contains, Within, Touches, Crosses, Overlaps, Equals  ⇒  Intersects
// donc `Intersects OR Contains` renvoie exactement les mêmes lignes que `Intersects` seul. Seul `Disjoint`
// (le contraire de `Intersects`) échappe à la règle.

export const DEFAULT_PREDICATES = ["Intersects"];

/** Prédicats réellement envoyés : `Intersects` seul dès qu'il est coché, sauf avec `Disjoint`. */
export function effectivePredicates(predicates) {
  const unique = [...new Set(predicates || [])];
  if (!unique.length) return [...DEFAULT_PREDICATES];
  if (unique.includes("Intersects") && !unique.includes("Disjoint")) return ["Intersects"];
  return unique;
}

/** Phrase à afficher quand la réduction a retiré des prédicats, sinon une chaîne vide. */
export function reductionNote(predicates) {
  const chosen = [...new Set(predicates || [])];
  const effective = effectivePredicates(chosen);
  const removed = chosen.filter((p) => !effective.includes(p));
  return removed.length
    ? `${removed.join(", ")} déjà inclus dans ${effective.join(", ")} : un seul prédicat envoyé, même résultat`
    : "";
}
