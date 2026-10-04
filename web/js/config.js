// Configuration de l'interface web. Aucun secret ici : ce fichier est publié tel quel.

export const WEB_VERSION = "0.6.0";
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

// Poids visé pour les filtres spatiaux d'une requête (le contour est recopié dans chaque table).
// Mesuré (une table, filtre « rembourré » sur une petite emprise) : corps de 228 000, 250 500 et 256 500 octets
// acceptés, 262 000 / 465 495 / 600 000 refusés (HTTP 500 à la création) : la limite porte sur la taille de
// toute la requête, entre 256 500 et 262 000 octets. 200 Ko garde une marge d'au moins 22 %.
export const FILTER_BUDGET_BYTES = 200_000;

// Encodage du contour dans le filtre : « twkb » (hexadécimal, ~4 à 5 fois plus léger que le WKT, exécuté
// par le service : vérifié en conditions réelles) ou « wkt ». Octets par sommet estimés, prudemment.
export const GEOMETRY_ENCODING = "twkb";
// Plancher du budget d'un filtre (octets) : en deçà, plus aucun contour utile ne tient.
export const MIN_FILTER_BYTES = 1500;
// Enveloppe du filtre hors contour : « ST_Intersects(geom, ST_SetSRID(ST_GeomFromTWKB(decode('…','hex')), srid)) ».
export const FILTER_WRAPPER_BYTES = 80;
export const BYTES_PER_VERTEX = { twkb: 9, wkt: 22 };

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
