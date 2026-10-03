# Interface web — GPF Extraction

Interface web **expérimentale et non officielle** pour le service d'extraction de la
Géoplateforme : même périmètre fonctionnel que le plugin QGIS, sans rien à installer.

Publiée par GitHub Pages : <https://ignf-xavier.github.io/qgis_gpf_extraction/>

## Ce qu'elle fait

- **Emprise** : recherche administrative (commune, département, région — API de géocodage de la
  Géoplateforme, contour précis), préréglages (France métropolitaine, chacun des 5 DOM avec son
  vrai contour), rectangle dessiné ou saisi, le tout visualisé sur le Plan IGN.
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

## Développement

Aucune étape de build : HTML, CSS et modules ES natifs. Leaflet et proj4 sont chargés depuis jsDelivr
avec empreintes SRI.

```bash
cd web
node --test tests/          # tests unitaires (modèles, géométrie, requête, auth, API)
npx http-server . -p 8080   # ou tout serveur statique, puis http://localhost:8080
```

Le déploiement est assuré par `.github/workflows/web-pages.yml` : les tests tournent à chaque
modification de `web/`, puis seul le site (`index.html`, `style.css`, `js/`) est publié.
