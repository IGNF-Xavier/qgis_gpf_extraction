# GPF Extraction

> ⚠️ **Plugin expérimental — ne pas utiliser en production.**
> Fork de l'ancien plugin *BD TOPO® Extractor* de Jules Grillot, réécrit
> autour du nouveau service d'extraction authentifié de la Géoplateforme
> et renommé **GPF Extraction**. Testé en conditions réelles (processus
> BD TOPO et GPU_EXTRACTION), mais n'est pas passé par un vrai processus
> de publication — attendez-vous à des aspérités, et signalez tout
> comportement inattendu.

[English documentation](README.md)

## Description

### Pourquoi ?

Cet outil permet d'extraire la BD TOPO® et les autres produits de la
Géoplateforme auxquels votre compte cartes.gouv.fr a accès, via le nouveau
[service d'extraction](https://cartes.gouv.fr/actualites/services-validation-et-extraction)
de la Géoplateforme (une API OGC API - Processes, extraction asynchrone
par job) plutôt que l'ancien WFS anonyme.

### Comment l'utiliser

1. **Se connecter** à la Géoplateforme : réutilisez une configuration
   d'authentification QGIS existante — par exemple celle créée par le
   [plugin officiel QGIS Géoplateforme](https://github.com/Geoplateforme/plugin-qgis-geoplateforme).
   (Le bouton « Se connecter » autonome intégré est actuellement
   désactivé — voir *Limitations connues*.)
2. **Choisir une emprise** : une BBox dessinée sur la carte, ou une
   emprise administrative (commune, département, région — les homonymes
   sont désambiguïsés par le code département/région) recherchée par nom.
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
5. **Lancer l'extraction**. Cela **ne bloque pas QGIS** : le job tourne
   sur le serveur (généralement plusieurs minutes) et est suivi en
   arrière-plan. Vous pouvez continuer à travailler, fermer la fenêtre de
   progression, ou même fermer QGIS entièrement — voir ci-dessous.
6. Une fois téléchargé, les tables sans aucune entité dans l'emprise
   demandée sont retirées du GeoPackage, un petit rapport de génération
   (tables demandées vs couches livrées, couches vides retirées, éventuels
   échecs de téléchargement) est affiché et journalisé dans le panneau de
   messages QGIS, puis le résultat est ajouté à votre projet. Un éventuel
   style publié pour ce produit dans le catalogue de métadonnées (CSW) de
   la Géoplateforme est recherché et appliqué automatiquement par table —
   si plusieurs styles correspondent à une même table, on vous demande
   lequel utiliser. *(Voir Limitations connues : cette recherche de style
   peut prendre environ 35 secondes la première fois dans une session
   QGIS.)*

### Suivre les jobs — « Jobs en cours »

Un job continue de tourner sur le serveur de la Géoplateforme
indépendamment de QGIS. L'entrée **« Jobs en cours »** du menu du plugin
liste tous les jobs lancés depuis cette installation — leur statut (en
cours / prêt à télécharger / téléchargé, avec son dossier de destination),
un commentaire optionnel que vous pouvez renseigner au lancement pour les
distinguer, et des actions pour rafraîchir leur statut, télécharger leur
résultat, ouvrir leur dossier, ou les oublier.

Si vous fermez QGIS alors qu'un job est encore en cours, une confirmation
vous est demandée — il continue de toute façon sur le serveur, et reste
listé à la prochaine ouverture de QGIS. Si un job n'apparaît pas dans la
liste (ex. lancé avant une mise à jour du plugin, ou depuis une autre
installation), utilisez **« Importer les jobs du serveur »** dans ce même
dialogue pour le retrouver depuis la Géoplateforme.

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
- L'application automatique de style ne fonctionne que pour les produits
  réellement référencés avec une ressource de style dans le catalogue de
  métadonnées de la Géoplateforme (la BD TOPO en a un ; ce n'est pas le
  cas de tous les produits — GPU_EXTRACTION, actuellement, n'en a pas).
  Quand aucun n'est trouvé, le résultat est chargé avec le rendu par
  défaut de QGIS.
- Si le serveur renvoie le résultat sous forme d'archive compressée
  (paramètre `compression` explicitement mis à `7zip`), le plugin ne la
  décompresse pas — 7-Zip (ou équivalent) est nécessaire. Laisser
  `compression` non renseigné évite complètement ce cas.
- **La disponibilité d'un style (SLD) pour un produit n'est pas exposée
  par le service d'extraction lui-même.** Le plugin la déduit en
  interrogeant le catalogue général de métadonnées (CSW) de la
  Géoplateforme : il télécharge la liste de l'ensemble des fiches du
  catalogue (~300, par pages de 100) pour y retrouver, par
  correspondance de titre, celle du produit extrait, puis y cherche une
  ressource en ligne ressemblant à un style. C'est un contournement
  indirect, coûteux (mesuré : environ 35 secondes la première fois dans
  une session QGIS — mis en cache ensuite pour le reste de la session) et
  heuristique (dépendant de la façon dont chaque fiche décrit ses
  ressources). **Un service dédié, associé au service d'extraction, qui
  indiquerait directement — pour un produit ou une donnée stockée
  donnée — si un ou plusieurs styles SLD existent et où les récupérer,
  simplifierait et fiabiliserait considérablement cette fonctionnalité.**

Voir aussi le [CHANGELOG](../CHANGELOG.md) pour l'historique détaillé des
versions.

## Références

- Documentation du service d'extraction : <https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/>
- Swagger du service d'extraction : <https://data.geopf.fr/extraction/swagger-ui/index.html>
