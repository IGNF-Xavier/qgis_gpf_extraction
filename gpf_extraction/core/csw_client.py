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


@dataclass
class StyleResource:
    title: str
    url: str


class CswClient:
    """Client pour la recherche de fiches de métadonnées et de leurs
    ressources de style associées."""

    def __init__(self):
        self._network = NetworkClient(authcfg="")
        self._records_cache: Optional[list[tuple[str, str]]] = None  # (id, title)

    def _load_brief_records(self) -> list[tuple[str, str]]:
        if self._records_cache is not None:
            return self._records_cache

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

        self._records_cache = records
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
