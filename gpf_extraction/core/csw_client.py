"""Client pour le catalogue de métadonnées CSW de la Géoplateforme.

Sert à retrouver, à partir du nom d'un produit (donnée stockée), la fiche
de métadonnées correspondante et les ressources qu'elle référence
évoquant un style (SLD), si elle en a. Catalogue public (ISO 19115/CSW
2.0.2), non authentifié : <https://data.geopf.fr/csw>.

Note : la recherche plein texte côté serveur (`GetRecords` avec une
contrainte CQL/OGC Filter sur `AnyText`) renvoie systématiquement une
erreur serveur (`UnknownFormatConversionException`) au moment de la
rédaction de ce module — contournée en récupérant la liste complète des
fiches (~300, un seul appel suffit) et en filtrant côté client.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsApplication, QgsTask

from ..network.http_client import NetworkClient
from .text_utils import normalize

CSW_BASE_URL = "https://data.geopf.fr/csw"

_NS = {
    "csw": "http://www.opengis.net/cat/csw/2.0.2",
    "dc": "http://purl.org/dc/elements/1.1/",
    "gmd": "http://www.isotc211.org/2005/gmd",
    "gco": "http://www.isotc211.org/2005/gco",
}

#: Fragments (en minuscules) recherchés dans la description ou l'URL d'une
#: ressource en ligne pour la considérer comme une ressource de style.
_STYLE_HINTS = ("style", "sld", "légende", "legende", "legend")

#: Cache des fiches CSW (brièves), partagé par toutes les instances de
#: `CswClient` le temps de la session QGIS. Une nouvelle instance est créée
#: à chaque extraction (`apply_styles`, dans `gui/job_result_loader.py`) ;
#: sans un cache au niveau du module, chacune re-parcourait tout le
#: catalogue (~300 fiches, ~3 pages) à chaque fois — mesuré en conditions
#: réelles à environ 35 secondes de blocage de l'interface, à chaque
#: extraction. Le catalogue ne changeant pas en cours de session, un seul
#: chargement suffit.
_module_records_cache: Optional[list[tuple[str, str]]] = None

#: Empêche de lancer plusieurs préchargements en parallèle (ex. si le
#: dialogue d'extraction est ouvert plusieurs fois dans la même session).
#: Remis à False si le préchargement échoue, pour permettre un nouvel
#: essai silencieux la prochaine fois.
_prefetch_started = False

#: Référence forte vers la tâche de préchargement en cours : sans ça, rien
#: n'empêche le ramasse-miettes Python de détruire l'objet `QgsTask` avant
#: la fin de son exécution côté C++ (piège classique documenté avec
#: `QgsTask.fromFunction`), ce qui interromprait silencieusement le
#: chargement.
_prefetch_task: Optional[QgsTask] = None


def prefetch_catalog_async() -> None:
    """Précharge en arrière-plan (`QgsTask`, sans bloquer l'interface) le
    catalogue de métadonnées CSW dans le cache partagé de la session.

    Sans effet si déjà en cache ou déjà en cours de chargement.

    Pensé pour être appelé dès l'ouverture du dialogue d'extraction : le
    chargement complet prend de l'ordre de 30 secondes (mesuré en
    conditions réelles, catalogue d'environ 300 fiches) ; le lancer
    pendant que l'utilisateur choisit son emprise, son produit et ses
    tables laisse largement le temps qu'il se termine avant que
    l'application d'un style ne soit effectivement tentée — ce qui
    n'arrive qu'après le téléchargement du résultat, généralement
    plusieurs minutes après le lancement de l'extraction.
    """
    global _prefetch_started, _prefetch_task
    if _prefetch_started or _module_records_cache is not None:
        return
    _prefetch_started = True

    def _run(_task: QgsTask) -> None:
        CswClient().warm_cache()

    def _on_finished(exception, _result=None) -> None:
        global _prefetch_task, _prefetch_started
        _prefetch_task = None
        if exception is not None:
            # Best-effort : un échec (ex. pas de réseau à ce moment-là)
            # n'est pas grave, la recherche de style au moment voulu
            # retentera normalement (bloquant, comme avant ce
            # préchargement) ; on autorise juste un nouvel essai silencieux
            # la prochaine fois que le dialogue s'ouvrira.
            _prefetch_started = False

    task = QgsTask.fromFunction(
        "GPF Extraction : préchargement du catalogue de styles (CSW)",
        _run,
        on_finished=_on_finished,
    )
    _prefetch_task = task
    QgsApplication.taskManager().addTask(task)


@dataclass
class StyleResource:
    title: str
    url: str


class CswClient:
    """Client pour la recherche de fiches de métadonnées et de leurs
    ressources de style associées."""

    def __init__(self):
        self._network = NetworkClient(authcfg="")

    def warm_cache(self) -> None:
        """Charge (et met en cache pour la session) la liste des fiches
        CSW, sans rien renvoyer. Utilisé pour le préchargement en
        arrière-plan (cf. `prefetch_catalog_async`)."""
        self._load_brief_records()

    def _load_brief_records(self) -> list[tuple[str, str]]:
        global _module_records_cache
        if _module_records_cache is not None:
            return _module_records_cache

        # Récupéré par pages de 100 : une seule requête avec un maxRecords
        # élevé (ex. 500) échoue systématiquement (la réponse, volumineuse
        # à cause des multiples bounding boxes par fiche, semble déclencher
        # un problème réseau côté QGIS - timeout ou coupure de connexion).
        page_size = 100
        start_position = 1
        records: list[tuple[str, str]] = []

        for _ in range(20):  # garde-fou : au plus 2000 fiches parcourues
            url = (
                f"{CSW_BASE_URL}?service=CSW&version=2.0.2&request=GetRecords"
                "&typeNames=csw:Record&resultType=results&elementSetName=brief"
                f"&maxRecords={page_size}&startPosition={start_position}"
            )
            response = self._network.get(url)
            if not response.ok:
                break

            try:
                root = ET.fromstring(response.body)
            except ET.ParseError:
                break

            for brief in root.iterfind(".//csw:BriefRecord", _NS):
                identifier = brief.findtext("dc:identifier", default="", namespaces=_NS)
                title = brief.findtext("dc:title", default="", namespaces=_NS)
                if identifier and title:
                    records.append((identifier.strip(), title.strip()))

            search_results = root.find(".//csw:SearchResults", _NS)
            next_record = int(search_results.get("nextRecord", "0")) if search_results is not None else 0
            if next_record <= 0:
                break
            start_position = next_record

        _module_records_cache = records
        return records

    def find_record_id(self, product_name: str) -> Optional[str]:
        """Cherche la fiche de métadonnées correspondant le mieux à un nom de
        produit (ex. le `name` d'une donnée stockée de l'API d'extraction).

        Heuristique : le titre normalisé d'une fiche doit être contenu dans
        le nom normalisé du produit ; en cas de plusieurs correspondances,
        la plus longue (donc la plus spécifique) est retenue.

        :param product_name: nom du produit à identifier.
        :type product_name: str

        :return: identifiant de la fiche CSW la plus probable, ou None.
        :rtype: Optional[str]
        """
        normalized_name = normalize(product_name)
        if not normalized_name:
            return None

        best: Optional[tuple[str, str]] = None
        for identifier, title in self._load_brief_records():
            normalized_title = normalize(title)
            if normalized_title and normalized_title in normalized_name:
                if best is None or len(normalized_title) > len(normalize(best[1])):
                    best = (identifier, title)
        return best[0] if best else None

    def get_style_resources(self, record_id: str) -> list[StyleResource]:
        """Récupère les ressources en ligne évoquant un style dans une fiche.

        :param record_id: identifiant de la fiche (cf. `find_record_id`).
        :type record_id: str

        :return: ressources de style trouvées (peut être vide).
        :rtype: list[StyleResource]
        """
        url = (
            f"{CSW_BASE_URL}?service=CSW&version=2.0.2&request=GetRecordById"
            f"&id={record_id}&elementSetName=full"
            "&outputSchema=http://www.isotc211.org/2005/gmd"
        )
        response = self._network.get(url)
        if not response.ok:
            return []

        try:
            root = ET.fromstring(response.body)
        except ET.ParseError:
            return []

        resources: list[StyleResource] = []
        for online in root.iterfind(".//gmd:CI_OnlineResource", _NS):
            resource_url = online.findtext("gmd:linkage/gmd:URL", default="", namespaces=_NS).strip()
            description = online.findtext(
                "gmd:description/gco:CharacterString", default="", namespaces=_NS
            ).strip()
            if not resource_url:
                continue
            haystack = f"{description} {resource_url}".lower()
            if any(hint in haystack for hint in _STYLE_HINTS):
                resources.append(StyleResource(title=description or resource_url, url=resource_url))
        return resources
