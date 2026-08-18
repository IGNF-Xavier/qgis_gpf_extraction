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
from .atom_feed import DownloadEntry, parse_download_entries
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
        #: Renseigné par `download_all_results` : noms des fichiers dont le
        #: téléchargement a échoué lors du dernier appel (liste vide sinon).
        self.last_download_failures: list[str] = []

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

    def list_jobs(self, limit: int = 50) -> list[JobStatus]:
        """Liste les jobs de l'utilisateur authentifié, tels que connus par
        le serveur.

        Utile pour retrouver un job non suivi localement (ex. lancé avant
        une mise à jour du plugin, ou depuis une autre installation) : le
        registre local (`core/job_registry.py`) ne mémorise que les jobs
        lancés depuis ce poste, alors qu'un job continue d'exister côté
        serveur indépendamment de ce suivi.

        :param limit: nombre maximum de jobs renvoyés, defaults to 50
        :type limit: int, optional

        :return: jobs connus du serveur, les plus récents en premier.
        :rtype: list[JobStatus]
        """
        url = f"{self._api_base}/jobs?limit={limit}"
        response = _ensure_ok(self._network.get(url), "GET", url)
        payload = _parse_json(response, url)
        raw_items = payload.get("jobs") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            return []
        return [JobStatus.from_json(item) for item in raw_items]

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

        Constaté en conditions réelles : cette ressource fait de la
        négociation de contenu, et renvoie une version JSON du même flux
        si l'en-tête `Accept: application/json` (envoyé par défaut par
        `NetworkClient` pour le reste de l'API REST) est présent — d'où la
        surcharge explicite ci-dessous pour forcer la forme Atom/XML, seule
        que le parseur (`core/atom_feed.py`) sait lire. Le cache HTTP de
        QGIS ne tenant par ailleurs pas compte de cette variation d'en-tête
        (pas de `Vary: Accept` renvoyé par le serveur), une requête déjà
        mise en cache avec un autre `Accept` doit être contournée
        explicitement (`bypass_cache`), sous peine de rejouer indéfiniment
        la première réponse obtenue pour cette URL.

        :param extract_data_href: valeur de `JobResult.extract_data_href`.
        :type extract_data_href: str

        :return: fichiers téléchargeables (au moins un, sauf échec réseau).
        :rtype: list[DownloadEntry]
        """
        response = _ensure_ok(
            self._network.get(
                extract_data_href,
                headers={"Accept": "application/atom+xml"},
                bypass_cache=True,
            ),
            "GET",
            extract_data_href,
        )
        content_type = response.headers.get("Content-Type", "")
        # Tente systématiquement le parsing Atom (peu coûteux, et plus fiable
        # qu'un pré-filtrage sur le Content-Type/les premiers octets) ; ne se
        # rabat sur "lien direct vers un fichier" que si ça ne donne rien.
        entries = parse_download_entries(response.body)
        if entries:
            return entries
        return [DownloadEntry(href=extract_data_href, mime_type=content_type)]

    def download_all_results(self, extract_data_href: str, dest_dir) -> list[Path]:
        """Résout puis télécharge tous les fichiers de résultat d'un job
        dans un dossier.

        Un résultat d'extraction peut compter une dizaine de fichiers
        (un GeoPackage par table). L'échec d'un seul d'entre eux (timeout,
        erreur réseau ponctuelle...) ne doit pas faire perdre les fichiers
        déjà téléchargés avec succès : constaté en conditions réelles, une
        exception levée au milieu de la boucle faisait perdre le suivi de
        tous les téléchargements précédents côté appelant (rien n'était
        alors ni ajouté au projet, ni enregistré comme téléchargé). Les
        échecs sont donc collectés plutôt que propagés immédiatement, et
        une erreur n'est levée qu'en tout dernier recours (aucun fichier
        récupéré).

        :param extract_data_href: valeur de `JobResult.extract_data_href`.
        :type extract_data_href: str
        :param dest_dir: dossier de destination (créé si besoin).
        :type dest_dir: Union[str, Path]

        :raises ApiRequestError: si aucun fichier n'a pu être téléchargé.

        :return: chemins des fichiers téléchargés (échecs partiels exclus).
        :rtype: list[Path]
        """
        entries = self.resolve_download_files(extract_data_href)
        downloaded: list[Path] = []
        failures: list[str] = []
        for entry in entries:
            dest_path = Path(dest_dir) / entry.filename
            try:
                self.download_result(entry.href, dest_path)
            except (ApiRequestError, ConnectionError) as exc:
                failures.append(f"{entry.filename} : {exc}")
                continue
            downloaded.append(dest_path)

        if failures and not downloaded:
            raise ApiRequestError(
                "GET",
                extract_data_href,
                0,
                ("; ".join(failures)).encode("utf-8"),
            )
        self.last_download_failures = failures
        return downloaded
