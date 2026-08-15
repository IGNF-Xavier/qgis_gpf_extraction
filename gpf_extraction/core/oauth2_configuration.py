"""Représentation d'une configuration OAuth2 QGIS pour la Géoplateforme.

Repris des principes mis en oeuvre par le plugin officiel QGIS Géoplateforme
(`geoplateforme/datamodels/oauth2_configuration.py`) : QGIS attend, pour une
`QgsAuthMethodConfig` de méthode "OAuth2", un `configMap` contenant une seule
clé `oauth2config` dont la valeur est la représentation "façon JSON" (avec des
guillemets doubles) d'un dictionnaire de configuration.

Contrairement au plugin officiel, aucun secret client n'est nécessaire ici :
le client OAuth2 utilisé (`gpf-swagger`, cf. `core.constants`) est un client
public, le même que celui utilisé par le Swagger officiel du service
d'extraction.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from .constants import (
    DEFAULT_OAUTH_CLIENT_ID,
    OAUTH_AUTHORIZE_URL,
    OAUTH_REDIRECT_URL,
    OAUTH_TOKEN_URL,
)
from .exceptions import AuthenticationError

#: Champs requis par le gestionnaire d'authentification de QGIS pour une
#: configuration OAuth2.
QGS_REQUIRED_FIELDS = [
    "accessMethod",
    "clientId",
    "clientSecret",
    "configType",
    "grantFlow",
    "persistToken",
    "redirectPort",
    "redirectUrl",
    "requestTimeout",
    "requestUrl",
    "scope",
    "tokenUrl",
    "version",
]


@dataclass
class OAuth2Configuration:
    """Configuration OAuth2 pour la connexion au service d'extraction."""

    accessMethod: int = 0  # 0 = Header ("Authorization: Bearer ...")
    clientId: str = DEFAULT_OAUTH_CLIENT_ID
    clientSecret: str = ""
    configType: int = 1  # 1 = OAuth2 configuration "manuelle"
    description: str = "Authentification Géoplateforme (GPF Extraction)."
    grantFlow: int = 0  # 0 = Authorization Code
    name: str = "gpf_extraction_cfg"
    persistToken: bool = True
    queryPairs: dict = field(default_factory=dict)
    redirectPort: int = 7070
    redirectUrl: str = OAUTH_REDIRECT_URL
    requestTimeout: int = 30
    requestUrl: str = OAUTH_AUTHORIZE_URL
    scope: str = ""
    tokenUrl: str = OAUTH_TOKEN_URL
    version: int = 1

    def as_qgis_str_config_map(self) -> str:
        """Sérialise la configuration au format attendu par QGIS.

        :return: représentation "JSON" (guillemets doubles) du dictionnaire
            de configuration, restreint aux champs requis par QGIS.
        :rtype: str
        """
        config_dict = asdict(self)
        config_dict = {k: v for k, v in config_dict.items() if k in QGS_REQUIRED_FIELDS}

        config_str = str(config_dict).replace("'", '"')
        config_str = config_str.replace("False", "false").replace("True", "true")
        return config_str

    @classmethod
    def from_config_map(cls, qgis_config_map: dict) -> "OAuth2Configuration":
        """Reconstruit une configuration depuis le `configMap` QGIS.

        :param qgis_config_map: `configMap` d'une `QgsAuthMethodConfig`.
        :type qgis_config_map: dict

        :raises AuthenticationError: si le contenu n'est pas exploitable.

        :return: configuration reconstruite.
        :rtype: OAuth2Configuration
        """
        raw = qgis_config_map.get("oauth2config")
        if not raw:
            raise AuthenticationError(
                "La configuration d'authentification ne contient pas de clé "
                "'oauth2config'."
            )
        try:
            cfg_map = (
                raw.replace("False", "false")
                .replace("True", "true")
                .replace("'", '"')
                .replace("None", "null")
            )
            cfg_json = json.loads(cfg_map)
        except json.JSONDecodeError as err:
            raise AuthenticationError(
                f"Configuration d'authentification illisible : {err}"
            ) from err

        known_fields = {f for f in cls.__dataclass_fields__}
        cfg_json = {k: v for k, v in cfg_json.items() if k in known_fields}
        return cls(**cfg_json)


def build_default_config(redirect_port: Optional[int] = None) -> OAuth2Configuration:
    """Construit la configuration OAuth2 par défaut du plugin.

    :param redirect_port: port de callback à utiliser, defaults to None
        (utilise le port par défaut de `OAuth2Configuration`).
    :type redirect_port: Optional[int], optional

    :return: configuration par défaut.
    :rtype: OAuth2Configuration
    """
    cfg = OAuth2Configuration()
    if redirect_port is not None:
        cfg.redirectPort = redirect_port
    return cfg
