# Interface web — GPF Extraction

Interface web **expérimentale et non officielle** pour le service d'extraction de la
Géoplateforme : même périmètre fonctionnel que le plugin QGIS, sans rien à installer.

Publiée par GitHub Pages : <https://ignf-xavier.github.io/qgis_gpf_extraction/>

## Ce qu'elle fait

- **Emprise** : recherche administrative (commune, département, région — API de géocodage de la
  Géoplateforme, contour précis), préréglages (France métropolitaine, chacun des 5 DOM avec son
  vrai contour), rectangle dessiné ou saisi, le tout visualisé sur le Plan IGN (carte OpenLayers avec les
  extensions Géoplateforme : changement de couche, recherche d'adresse, coordonnées du curseur).
- **Produit et tables** : liste des produits du compte, sélecteur de tables, prédicats géométriques
  multiples combinés en OU, projection de sortie, format, fusion en un seul fichier, durée de rétention.
- **Requête** : le corps JSON est affiché (modifiable en mode avancé), copiable en JSON ou en `curl`.
  Le filtre spatial utilise le contour précis, exprimé dans la projection *native* de la donnée
  (indépendante de la projection de sortie choisie).
- **Jobs** : lancement, suivi, annulation, import des jobs du serveur, liens de téléchargement directs
  (aucun fichier ne transite par cette page), avertissements sur les résultats suspects.
- Les erreurs du service s'affichent avec la requête envoyée et la réponse reçue, copiables.

## Ce qu'elle ne fait pas (par rapport au plugin QGIS)

- Pas de découpage des couches à l'emprise, de renommage du GeoPackage, ni d'application automatique
  de styles : ce sont des opérations côté QGIS, après téléchargement.
- Pas de connexion automatique : voir ci-dessous.

## Connexion

Le service d'extraction exige un jeton OAuth2. Une page statique ne peut pas s'authentifier avec les
clients existants : le client public du Swagger refuse toute redirection vers une autre origine (HTTP 400)
et le flux « device » y est désactivé. L'interface accepte donc **un jeton Bearer collé à la main**
(temporaire, conservé en mémoire — ou en `sessionStorage` si on le demande, jamais en `localStorage` —
et envoyé uniquement à `data.geopf.fr`).

Le code d'une connexion OAuth2 *Authorization Code + PKCE* est déjà présent mais **inactif** : il
suffira de renseigner `OIDC.clientId` dans `js/config.js` une fois qu'un client dédié aura été
enregistré côté Géoplateforme avec l'URL de cette page comme URI de redirection.

Sans jeton, la recherche d'emprise, la carte et la construction de la requête fonctionnent déjà
(services publics) ; seuls la liste des produits et le lancement exigent d'être connecté.

## Technologies et licences

- **Mise en forme** : [système de design de l'État (DSFR)](https://www.systeme-de-design.gouv.fr/) 1.14.4,
  hébergé par le site lui-même (aucun CDN). Thème clair/sombre via « Paramètres d'affichage ».
- **Carte** : [OpenLayers](https://openlayers.org/) et
  [`geopf-extensions-openlayers`](https://github.com/IGNF/geopf-extensions-openlayers) (thème DSFR) :
  couches Plan IGN, photographies aériennes et limites administratives, sélecteur de couches,
  recherche, zoom, position de la souris. Au chargement, la configuration Géoplateforme (lot
  `essentiels`) est lue sur `raw.githubusercontent.com` ; si elle est indisponible, la carte affiche un
  message et le reste de la page continue de fonctionner.
- **À savoir** : le DSFR et la fonte Marianne sont réservés aux sites des services publics (voir leurs
  [conditions d'utilisation](https://github.com/GouvernementFR/dsfr/blob/main/doc/legal/cgu.md)) ; cette
  interface est **non officielle** et n'en reprend donc pas le bloc-marque (Marianne, « République
  Française »). `geopf-extensions-openlayers` est publiée sous licence AGPL-3.0 : le site publié l'embarque.

## Développement

Le site est construit avec [esbuild](https://esbuild.github.io/) (`build.mjs`) : `js/app.js`, OpenLayers et
les extensions Géoplateforme sont regroupés dans `dist/app.js` et `dist/app.css`, et le DSFR est copié depuis
`node_modules`. Les versions sont figées par `package-lock.json`.

```bash
cd web
npm ci                      # dépendances
npm test                    # tests unitaires (modèles, géométrie, requête, auth, API)
npm run build               # construit dist/
npx http-server dist -p 8080   # ou tout serveur statique, puis http://localhost:8080
```

Le déploiement est assuré par `.github/workflows/web-pages.yml` : les tests tournent à chaque
modification de `web/`, puis `npm run build` produit `web/dist`, seul dossier publié.
