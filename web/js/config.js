// Configuration de l'interface web. Aucun secret ici : ce fichier est publié tel quel.

export const WEB_VERSION = "0.2.0";
export const REPO_URL = "https://github.com/IGNF-Xavier/qgis_gpf_extraction";

// Services de la Géoplateforme (tous en CORS ouvert, vérifié en conditions réelles).
export const API_BASE = "https://data.geopf.fr/extraction";
export const GEOCODING_SEARCH = "https://data.geopf.fr/geocodage/search";
export const WFS_BASE = "https://data.geopf.fr/wfs/ows";
export const WFS_ADMIN_LAYER_PREFIX = "LIMITES_ADMINISTRATIVES_EXPRESS.LATEST";

// Fonds de carte : couches et contrôles de geopf-extensions-openlayers, qui lisent la
// configuration Géoplateforme de cette clé (lot « essentiels » : Plan IGN, photographies
// aériennes, limites administratives).
export const CONFIG_KEY = "essentiels";

// Projection de travail des emprises (GeoJSON, géocodage, carte).
export const WORKING_CRS = "EPSG:4326";

// Connexion OAuth2 (Authorization Code + PKCE) — INACTIVE tant que `clientId` est nul.
//
// Constaté en conditions réelles : le client public `gpf-swagger` refuse une
// redirection vers une autre origine (HTTP 400) et le flux « device » y est
// désactivé. Une connexion automatique n'est donc possible qu'avec un client
// OAuth2 dédié, enregistré côté Géoplateforme avec cette page pour URI de
// redirection. En attendant, l'interface accepte un jeton Bearer collé à la main.
export const OIDC = {
  clientId: null,
  authorizeUrl: "https://sso.geopf.fr/realms/geoplateforme/protocol/openid-connect/auth",
  tokenUrl: "https://sso.geopf.fr/realms/geoplateforme/protocol/openid-connect/token",
  scope: "openid",
};

// Intervalle de suivi des jobs (millisecondes).
export const POLL_INTERVAL_MS = 15000;
