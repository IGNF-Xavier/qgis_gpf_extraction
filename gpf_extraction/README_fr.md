# GPF Extraction

> ⚠️ **Plugin expérimental — ne pas utiliser en production.**
> Fork de l'ancien plugin *BD TOPO® Extractor* de Jules Grillot, réécrit
> autour du nouveau service d'extraction authentifié de la Géoplateforme
> et renommé **GPF Extraction**. Le comportement face à l'API réelle est
> encore en cours de calibration.

[English documentation](README.md)

## Description

### Pourquoi ?

Cet outil permet d'extraire la BD TOPO® et les autres produits de la
Géoplateforme auxquels votre compte cartes.gouv.fr a accès, via le nouveau
[service d'extraction](https://cartes.gouv.fr/actualites/services-validation-et-extraction)
de la Géoplateforme (une API OGC API - Processes, extraction asynchrone
par job) plutôt que l'ancien WFS anonyme.

### Comment l'utiliser

1. **Se connecter** à la Géoplateforme : soit en réutilisant une
   configuration d'authentification QGIS existante (par exemple celle
   créée par le [plugin officiel QGIS Géoplateforme](https://github.com/Geoplateforme/plugin-qgis-geoplateforme)),
   soit via le bouton « Se connecter » intégré (actuellement désactivé,
   voir *Limitations connues* ci-dessous).
2. **Choisir une emprise** : une BBox dessinée sur la carte, ou une
   emprise administrative (commune, département, région) recherchée par
   nom.
3. **Choisir un produit** parmi les processus auxquels votre compte a
   accès (la BD TOPO® apparaît en premier dans la liste quand elle est
   disponible).
4. **Renseigner les paramètres**. Pour les processus d'extraction
   « ARCHIVE depuis VECTOR-DB » (BD TOPO, GPU_EXTRACTION, ...), un
   sélecteur de tables dédié permet de cocher les tables voulues et
   génère automatiquement le filtre spatial (`ST_Intersects`) de chacune
   à partir de l'emprise choisie. Un éditeur JSON brut avancé reste
   toujours disponible en secours pour ce que le formulaire générique ne
   couvre pas.
5. **Lancer l'extraction**, suivre sa progression, et laisser le plugin
   télécharger le résultat et l'ajouter au projet.

## Limitations connues (statut expérimental)

- Le corps de requête exact attendu par chaque processus est déduit à
  l'exécution de ce que renvoie l'API (`GET /processes/{id}`), car il
  n'est pas entièrement typé dans la description OpenAPI du service. Il a
  été validé en conditions réelles sur les processus « BD TOPO » et
  « GPU_EXTRACTION » ; d'autres processus pourraient nécessiter des
  ajustements via l'éditeur JSON avancé.
- Le bouton de connexion autonome « Se connecter » est désactivé : le
  client OAuth2 public utilisé par le Swagger officiel (`gpf-swagger`)
  n'accepte pas de redirection locale (callback). Un client OAuth2 dédié,
  enregistré auprès de la Géoplateforme, serait nécessaire pour le
  réactiver. En attendant, réutilisez une configuration d'authentification
  existante (par exemple celle du plugin officiel QGIS Géoplateforme).

## Références

- Documentation du service d'extraction : <https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/>
- Swagger du service d'extraction : <https://data.geopf.fr/extraction/swagger-ui/index.html>
