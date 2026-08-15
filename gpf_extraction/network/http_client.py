"""Client HTTP synchrone unique, partagé par tout le plugin.

Toute la logique d'accès réseau transite par cette classe : les modules
`core` ne connaissent que ce client, jamais `QNetworkAccessManager`
directement. Repris du pattern déjà utilisé dans le plugin `gpf_validation`
de l'auteur (`network/http_client.py`), lui-même inspiré des principes du
plugin officiel QGIS Géoplateforme (`geoplateforme/toolbelt/network_manager.py`) :
injection de l'authentification via `QgsApplication.authManager()`.

Notes d'implémentation :
- `QgsNetworkAccessManager.instance()` renvoie une instance par thread
  depuis QGIS >= 3.6 ; il est donc sûr d'appeler ce client aussi bien
  depuis le thread GUI que depuis une tâche d'arrière-plan (`QgsTask`).
- Les appels restent synchrones (boucle d'événements locale), ce qui est
  acceptable ici car ils sont systématiquement de courte durée (le
  téléchargement du résultat final, potentiellement long, passe par
  `download_to_file`, qui délègue à `QgsFileDownloader`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from qgis.core import QgsApplication, QgsFileDownloader, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest


@dataclass
class HttpResponse:
    status_code: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class NetworkClient:
    """Enveloppe fine autour de `QgsNetworkAccessManager` + `QgsAuthManager`."""

    def __init__(self, authcfg: str = ""):
        self._authcfg = authcfg or ""

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------
    def _inject_auth(self, request: QNetworkRequest) -> None:
        if self._authcfg:
            QgsApplication.authManager().updateNetworkRequest(request, self._authcfg)

    @staticmethod
    def _wait(reply: QNetworkReply) -> QNetworkReply:
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        loop.exec_()
        return reply

    @staticmethod
    def _to_response(reply: QNetworkReply) -> HttpResponse:
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll().data())
        headers = {}
        try:
            for key, value in reply.rawHeaderPairs():
                headers[bytes(key).decode("utf-8", "ignore")] = bytes(value).decode(
                    "utf-8", "ignore"
                )
        except Exception:
            pass
        reply.deleteLater()
        return HttpResponse(
            status_code=int(status) if status is not None else 0,
            body=body,
            headers=headers,
        )

    def _build_request(self, url: str, headers: Optional[dict] = None) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/json")
        self._inject_auth(request)
        for key, value in (headers or {}).items():
            request.setRawHeader(
                key if isinstance(key, bytes) else key.encode("utf-8"),
                value if isinstance(value, bytes) else str(value).encode("utf-8"),
            )
        return request

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------
    def get(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        request = self._build_request(url, headers)
        nam = QgsNetworkAccessManager.instance()
        reply = self._wait(nam.get(request))
        return self._to_response(reply)

    def delete(self, url: str) -> HttpResponse:
        request = self._build_request(url)
        nam = QgsNetworkAccessManager.instance()
        reply = self._wait(nam.sendCustomRequest(request, b"DELETE", QByteArray()))
        return self._to_response(reply)

    def request_json(self, method: str, url: str, payload: dict) -> HttpResponse:
        """Envoie une requête avec un corps JSON (POST / PUT / PATCH)."""
        request = self._build_request(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        body = QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        nam = QgsNetworkAccessManager.instance()
        method_up = method.upper()
        if method_up == "POST":
            reply = nam.post(request, body)
        elif method_up == "PUT":
            reply = nam.put(request, body)
        elif method_up == "PATCH":
            reply = nam.sendCustomRequest(request, b"PATCH", body)
        else:
            raise ValueError(f"Méthode HTTP JSON non supportée : {method}")
        return self._to_response(self._wait(reply))

    def download_to_file(
        self,
        url: str,
        dest_path: Union[str, Path],
        use_auth: bool = True,
    ) -> Path:
        """Télécharge une ressource (potentiellement volumineuse) vers un fichier.

        Délègue à `QgsFileDownloader`, qui gère le téléchargement en
        streaming (pas de chargement intégral en mémoire).

        :param url: URL à télécharger.
        :type url: str
        :param dest_path: chemin de destination.
        :type dest_path: Union[str, Path]
        :param use_auth: si True, la configuration d'authentification du
            client est appliquée à la requête ; à mettre à False pour les
            liens de stockage objet pré-signés (leur URL contient déjà tout
            ce qu'il faut, et un en-tête d'autorisation supplémentaire les
            ferait échouer), defaults to True.
        :type use_auth: bool, optional

        :raises ConnectionError: en cas d'échec du téléchargement.

        :return: chemin du fichier téléchargé.
        :rtype: Path
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        loop = QEventLoop()
        downloader = QgsFileDownloader(
            url=QUrl(url),
            outputFileName=str(dest_path),
            delayStart=True,
            authcfg=self._authcfg if use_auth else "",
        )
        downloader.downloadExited.connect(loop.quit)

        error_messages: list = []

        def _on_error(messages):
            error_messages.extend(messages)

        downloader.downloadError.connect(_on_error)

        downloader.startDownload()
        loop.exec()

        if error_messages:
            raise ConnectionError("; ".join(str(m) for m in error_messages))

        return dest_path
