
# GPF Extraction - QGIS Plugin

> ⚠️ **Plugin expérimental — ne pas utiliser en production.**
> Fork réécrit de l'ancien plugin *BD TOPO® Extractor*, renommé **GPF
> Extraction**. Fonctionnel et testé en conditions réelles sur plusieurs
> produits, mais pas passé par un vrai processus de publication (pas de
> revue de code externe, pas de suite de tests automatisés complète) :
> attendez-vous à des aspérités, et signalez tout comportement inattendu
> via une [issue](https://github.com/IGNF-Xavier/qgis_gpf_extraction/issues).

## À quoi sert ce plugin

Il permet d'extraire la BD TOPO® et tout autre produit de la Géoplateforme
auquel votre compte cartes.gouv.fr a accès, via le
[service d'extraction](https://cartes.gouv.fr/actualites/services-validation-et-extraction)
authentifié de la Géoplateforme (une API OGC API - Processes, extraction
asynchrone par job côté serveur) — plutôt que l'ancien flux WFS anonyme et
non authentifié de l'ancien plugin.

## Périmètre fonctionnel actuel

- **Connexion** à la Géoplateforme via une configuration d'authentification
  QGIS existante (OAuth2). (celle du plugin Geoplateforme pour QGIS fonctionne)
- **Choix de l'emprise** : BBox dessinée sur la carte, emprise
  administrative (commune, département, région, recherchée par nom), ou une
  couche de polygones du projet (toutes ses entités, ou seulement celles
  sélectionnées).
- **Choix du produit** parmi les processus d'extraction auxquels le compte
  connecté a accès.
- **Sélecteur de tables** (pour les processus « ARCHIVE depuis
  VECTOR-DB », type BD TOPO) avec filtre spatial automatique par table,
  combinant un ou plusieurs prédicats géométriques au choix (`Intersects`,
  `Contains`, `Within`, `Disjoint`, `Touches`, `Crosses`, `Overlaps`,
  `Equals`).
- **Projection de sortie** au choix (liste de projections courantes,
  éditable pour tout code EPSG), **nom du GeoPackage** personnalisable, et
  **découpage optionnel** des entités téléchargées à l'emprise exacte.
- **Suivi des jobs** non bloquant et persistant entre sessions QGIS
  (menu « Jobs en cours ») : un job continue de tourner côté serveur même
  si QGIS est fermé, et reste retrouvable ensuite.
- **Application automatique de styles** trouvés dans le catalogue de
  métadonnées (CSW) de la Géoplateforme pour les couches extraites, quand
  ils existent.
- **Édition avancée du corps de requête (JSON)** en secours pour tout
  processus ou paramètre non couvert par le formulaire générique.

## Limites connues, au stade actuel

- Le bouton de connexion autonome intégré est désactivé (aucun client
  OAuth2 public utilisable) : il faut réutiliser une configuration
  d'authentification QGIS existante.
- L'application automatique de style dépend d'une recherche heuristique
  dans le catalogue CSW (pas d'API dédiée côté service) : incomplète et
  coûteuse la première fois dans une session.
- Le service d'extraction évolue sans documentation de ses changements
  (ex. un `HTTP 500` sur 59 tables fusionnées le 2026-09-01, disparu le
  2026-09-25 ; une nouvelle sortie `jobName` refusée si demandée vide) : en
  cas de refus, le plugin affiche la requête et la réponse, copiables.

Distributed under the terms of the [`GNU General Public License v2.0` license](LICENSE).
