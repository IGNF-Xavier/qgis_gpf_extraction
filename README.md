# GPF Extraction - QGIS Plugin

> ⚠️ **Plugin expérimental — ne pas utiliser en production.**
> Ce dépôt est un fork expérimental de l'ancien plugin *BD TOPO® Extractor*
> (renommé **GPF Extraction**), réécrit pour utiliser le nouveau service
> d'extraction authentifié de la Géoplateforme
> (<https://cartes.gouv.fr/actualites/services-validation-et-extraction>,
> API OGC API - Processes) au lieu de l'ancien flux WFS anonyme. Il permet
> d'extraire la BD TOPO® ainsi que tout autre produit auquel le compte
> cartes.gouv.fr connecté a accès, avec suivi asynchrone des jobs
> (persistant entre sessions QGIS) et application automatique des styles
> référencés au catalogue de métadonnées (CSW) quand ils existent. Testé
> en conditions réelles (BD TOPO, GPU_EXTRACTION) mais pas passé par un
> vrai processus de publication : voir le
> [README du plugin](gpf_extraction/README_fr.md) pour le détail des
> limitations connues.



Distributed under the terms of the [`GNU General Public License v2.0` license](LICENSE).
