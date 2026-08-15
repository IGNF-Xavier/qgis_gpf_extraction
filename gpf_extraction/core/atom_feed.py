"""Parsing du flux Atom (INSPIRE Download Service) renvoyé par le lien
`extractData` d'un job terminé.

Constaté en conditions réelles : `extractData.href` ne pointe **pas**
directement vers le fichier de résultat, mais vers un flux Atom qui liste
les fichiers réellement téléchargeables (ex. un `extraction.json` de
métadonnées, et l'archive de données elle-même) — cohérent avec le schéma
déclaré par le processus pour cette sortie
(`"contentMediaType": "application/atom+xml"`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "gpf_dl": "https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd",
}


@dataclass
class DownloadEntry:
    href: str
    mime_type: str = ""

    @property
    def filename(self) -> str:
        return Path(urlparse(self.href).path).name or "fichier"

    @property
    def is_metadata(self) -> bool:
        """Fichier accessoire (ex. résumé JSON de l'extraction), à ne pas
        essayer de charger comme couche vecteur."""
        return self.mime_type == "application/json" or self.filename.lower().endswith(".json")


def looks_like_atom_feed(content_type: str, body: bytes) -> bool:
    """Détecte si une réponse HTTP est un flux Atom plutôt qu'un fichier
    binaire direct (repli défensif : le contrat exact n'étant pas garanti
    pour tous les processus, on ne suppose pas systématiquement un flux)."""
    if "atom+xml" in (content_type or "").lower():
        return True
    return b"<feed" in body[:500]


def parse_download_entries(xml_body: bytes) -> list[DownloadEntry]:
    """Extrait les fichiers téléchargeables listés dans un flux Atom.

    :param xml_body: contenu du flux Atom.
    :type xml_body: bytes

    :return: fichiers téléchargeables (peut être vide si le flux est
        illisible ou ne contient aucune entrée).
    :rtype: list[DownloadEntry]
    """
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return []

    entries: list[DownloadEntry] = []
    for entry in root.iterfind("atom:entry", _NS):
        link = entry.find("atom:link", _NS)
        if link is None:
            continue
        href = link.get("href", "")
        if not href:
            continue
        mime_type = entry.findtext("gpf_dl:mime_type", default="", namespaces=_NS) or link.get(
            "type", ""
        )
        entries.append(DownloadEntry(href=href, mime_type=mime_type))
    return entries
