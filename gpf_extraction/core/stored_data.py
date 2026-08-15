"""Client pour la description des données stockées (API "entrepôt").

Le lien `describedby` renvoyé par `GET /processes/{id}` (service
d'extraction) pointe vers `https://data.geopf.fr/api/users/me/stored_data/{id}`
(API "entrepôt" de la Géoplateforme, distincte de l'API d'extraction), qui
détaille — pour une donnée stockée de type VECTOR-DB — la liste des tables
exploitables par l'input `relations` d'un processus d'extraction
"ARCHIVE depuis VECTOR-DB" (nom de table, attributs, colonne géométrique).
"""

from __future__ import annotations

import json

from ..network.http_client import NetworkClient
from .exceptions import ApiRequestError
from .models import StoredDataDescription


class StoredDataClient:
    """Enveloppe l'accès en lecture à la description d'une donnée stockée."""

    def __init__(self, authcfg: str):
        self._network = NetworkClient(authcfg=authcfg)

    def get(self, url: str) -> StoredDataDescription:
        """Récupère la description d'une donnée stockée.

        :param url: URL absolue de la donnée stockée (lien `describedby`).
        :type url: str

        :return: description de la donnée stockée (avec ses tables).
        :rtype: StoredDataDescription
        """
        response = self._network.get(url)
        if not response.ok:
            raise ApiRequestError("GET", url, response.status_code, response.body)
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiRequestError("GET", url, response.status_code, response.body) from exc
        return StoredDataDescription.from_json(data)
