"""Client de haut niveau pour l'API d'extraction de la Géoplateforme.

Documentation de référence :
https://data.geopf.fr/extraction/swagger-ui/index.html

API de type OGC API - Processes (exécution asynchrone) : un produit
(BD TOPO, ou tout autre produit auquel l'utilisateur authentifié a droit)
correspond à un "processus". On déclenche une extraction en exécutant ce
processus (`POST /processes/{id}/execution`), ce qui crée un "job" que l'on
interroge (`GET /jobs/{id}`) jusqu'à ce qu'il soit terminé, puis dont on
récupère le résultat (`GET /jobs/{id}/results`).

Toute la logique d'accès réseau du plugin transite par cette classe.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..network.http_client import HttpResponse, NetworkClient
from .atom_feed import DownloadEntry, looks_like_atom_feed, parse_download_entries
from .constants import DEFAULT_API_BASE
from .exceptions import ApiRequestError, JobFailedError
from .models import JobResult, JobStatus, ProcessDetails, ProcessSummary


def _ensure_ok(response: HttpResponse, method: str, url: str) -> HttpResponse:
    if not response.ok:
        raise ApiRequestError(method, url, response.status_code, response.body)
    return response


def _parse_json(response: HttpResponse, context: str):
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiRequestError("GET", context, response.status_code, response.body) from exc


class ExtractionApiClient:
    """Enveloppe les opérations de l'API d'extraction pour un `authcfg` donné."""

    def __init__(self, authcfg: str, api_base: str = DEFAULT_API_BASE):
        self._api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self._authcfg = authcfg
        self._network = NetworkClient(authcfg=authcfg)

    @property
    def authcfg(self) -> str:
        """Identifiant de configuration d'authentification QGIS utilisé,
        réutilisable pour d'autres clients (ex. `StoredDataClient`)."""
        return self._authcfg

    # ------------------------------------------------------------------
    # Processus
    # ------------------------------------------------------------------
    def list_processes(self, page: int = 1, limit: int = 100) -> list[ProcessSummary]:
        """Liste les processus (produits) accessibles à l'utilisateur authentifié.

        :param page: numéro de page (commence à 1), defaults to 1
        :type page: int, optional
        :param limit: nombre maximum de résultats par page, defaults to 100
        :type limit: int, optional

        :return: liste des processus disponibles.
        :rtype: list[ProcessSummary]
        """
        url = f"{self._api_base}/processes?page={page}&limit={limit}"
        response = _ensure_ok(self._network.get(url), "GET", url)
        payload = _parse_json(response, url)
        raw_items = payload.get("processes") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise ApiRequestError("GET", url, response.status_code, b"reponse inattendue")
        return [ProcessSummary.from_json(item) for item in raw_items]

    def get_process(self, process_id: str) -> ProcessDetails:
        """Récupère la description détaillée d'un processus (dont ses entrées)."""
        url = f"{self._api_base}/processes/{process_id}"
        response = _ensure_ok(self._network.get(url), "GET", url)
        return ProcessDetails.from_json(_parse_json(response, url))

    # ------------------------------------------------------------------
    # Exécution / jobs
    # ------------------------------------------------------------------
    def execute(self, process_id: str, body: dict) -> JobStatus:
        """Déclenche l'exécution d'un processus.

        :param process_id: identifiant du processus à exécuter.
        :type process_id: str
        :param body: corps de la requête d'exécution (dépend du processus).
        :type body: dict

        :return: statut initial du job créé.
        :rtype: JobStatus
        """
        url = f"{self._api_base}/processes/{process_id}/execution"
        response = self._network.request_json("POST", url, body)
        if response.status_code == 429:
            raise ApiRequestError("POST", url, response.status_code, response.body)
        _ensure_ok(response, "POST", url)
        return JobStatus.from_json(_parse_json(response, url))

    def get_job(self, job_id: str) -> JobStatus:
        """Récupère le statut d'un job."""
        url = f"{self._api_base}/jobs/{job_id}"
        response = _ensure_ok(self._network.get(url), "GET", url)
        return JobStatus.from_json(_parse_json(response, url))

    def get_job_results(self, job_id: str) -> JobResult:
        """Récupère le résultat d'un job terminé avec succès.

        :raises JobFailedError: si le job n'est pas (encore) terminé avec succès.
        """
        url = f"{self._api_base}/jobs/{job_id}/results"
        response = self._network.get(url)
        if response.status_code in (404, 410, 500):
            raise JobFailedError(
                f"Résultat du job {job_id} indisponible (HTTP {response.status_code})."
            )
        _ensure_ok(response, "GET", url)
        return JobResult.from_json(_parse_json(response, url))

    def delete_job(self, job_id: str) -> None:
        """Annule un job en cours et/ou supprime ses résultats."""
        url = f"{self._api_base}/jobs/{job_id}"
        _ensure_ok(self._network.delete(url), "DELETE", url)

    def download_result(self, href: str, dest_path):
        """Télécharge un fichier vers un chemin donné.

        Le lien peut pointer soit vers l'API elle-même (auth nécessaire),
        soit vers une URL de stockage objet pré-signée (auth déjà incluse
        dans l'URL, un en-tête d'autorisation supplémentaire ferait échouer
        la requête). On essaie donc d'abord sans authentification si
        l'hôte diffère de celui de l'API, avec repli sur l'authentification
        sinon.
        """
        from urllib.parse import urlparse

        api_host = urlparse(self._api_base).netloc
        href_host = urlparse(href).netloc
        use_auth = href_host in ("", api_host)
        return self._network.download_to_file(href, dest_path, use_auth=use_auth)

    def resolve_download_files(self, extract_data_href: str) -> list[DownloadEntry]:
        """Résout le lien `extractData` vers la liste réelle des fichiers
        téléchargeables.

        Constaté en conditions réelles : ce lien ne pointe pas directement
        vers le fichier de résultat, mais vers un flux Atom (INSPIRE
        Download Service) qui liste les fichiers disponibles (données +
        métadonnées). Repli défensif si un processus renvoyait malgré tout
        un lien direct vers un fichier : le lien est alors utilisé tel quel.

        :param extract_data_href: valeur de `JobResult.extract_data_href`.
        :type extract_data_href: str

        :return: fichiers téléchargeables (au moins un, sauf échec réseau).
        :rtype: list[DownloadEntry]
        """
        response = _ensure_ok(self._network.get(extract_data_href), "GET", extract_data_href)
        content_type = response.headers.get("Content-Type", "")
        if looks_like_atom_feed(content_type, response.body):
            entries = parse_download_entries(response.body)
            if entries:
                return entries
        return [DownloadEntry(href=extract_data_href, mime_type=content_type)]

    def download_all_results(self, extract_data_href: str, dest_dir) -> list[Path]:
        """Résout puis télécharge tous les fichiers de résultat d'un job
        dans un dossier.

        :param extract_data_href: valeur de `JobResult.extract_data_href`.
        :type extract_data_href: str
        :param dest_dir: dossier de destination (créé si besoin).
        :type dest_dir: Union[str, Path]

        :return: chemins des fichiers téléchargés.
        :rtype: list[Path]
        """
        entries = self.resolve_download_files(extract_data_href)
        downloaded: list[Path] = []
        for entry in entries:
            dest_path = Path(dest_dir) / entry.filename
            self.download_result(entry.href, dest_path)
            downloaded.append(dest_path)
        return downloaded
