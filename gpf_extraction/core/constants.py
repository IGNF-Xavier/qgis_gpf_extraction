"""Constantes partagées par l'ensemble du plugin.

Centraliser ces valeurs ici évite qu'elles ne soient recopiées (et
désynchronisées) dans chaque module.
"""

from __future__ import annotations

PLUGIN_NAMESPACE = "gpf_extraction"

#: URL de base du service d'extraction de la Géoplateforme (API OGC API -
#: Processes). Référence : https://data.geopf.fr/extraction/swagger-ui/index.html
DEFAULT_API_BASE = "https://data.geopf.fr/extraction"

#: URLs du royaume Keycloak "geoplateforme", identiques à celles utilisées par
#: le plugin officiel QGIS Géoplateforme (sso.geopf.fr) et par le service
#: d'extraction lui-même (cf. son OpenAPI, schéma de sécurité
#: "Keycloak-Authentication").
OAUTH_AUTHORIZE_URL = (
    "https://sso.geopf.fr/realms/geoplateforme/protocol/openid-connect/auth"
)
OAUTH_TOKEN_URL = (
    "https://sso.geopf.fr/realms/geoplateforme/protocol/openid-connect/token"
)

#: Client OAuth2 public (sans secret) utilisé par le Swagger officiel du
#: service d'extraction (cf. https://data.geopf.fr/extraction/swagger-ui/
#: swagger-initializer.js : `ui.initOAuth({"clientId":"gpf-swagger"})`).
#: Réutilisé ici pour permettre une connexion autonome sans dépendre d'un
#: identifiant applicatif dédié.
DEFAULT_OAUTH_CLIENT_ID = "gpf-swagger"

#: Ports locaux essayés pour le callback OAuth2, dans l'ordre de préférence.
#: 7070 est le port déclaré par le plugin officiel QGIS Géoplateforme ; il est
#: essayé en premier par cohérence, avec repli sur 7071 en cas de conflit.
OAUTH_DECLARED_REDIRECT_PORTS: list[int] = [7070, 7071]
OAUTH_REDIRECT_URL = "callback"

#: API publique (non authentifiée) "Découpage administratif" utilisée pour la
#: recherche d'emprise administrative par nom (commune / département / région).
ADMIN_BOUNDARY_API_BASE = "https://geo.api.gouv.fr"

#: Intervalle par défaut (secondes) entre deux vérifications de statut d'un job.
DEFAULT_STATUS_CHECK_SLEEP = 15

#: Clés utilisées pour la persistance QgsSettings (préfixées par le namespace).
SETTINGS_KEY_API_BASE = f"{PLUGIN_NAMESPACE}/api_base"
SETTINGS_KEY_QGIS_AUTH_ID = f"{PLUGIN_NAMESPACE}/qgis_auth_id"
SETTINGS_KEY_STATUS_CHECK_SLEEP = f"{PLUGIN_NAMESPACE}/status_check_sleep"
SETTINGS_KEY_LAST_OUTPUT_DIR = f"{PLUGIN_NAMESPACE}/last_output_dir"

#: CRS de travail par défaut pour les emprises (BBox dessinée ou recherche
#: administrative), en l'absence d'indication contraire d'un processus.
DEFAULT_WORKING_CRS = "EPSG:4326"
