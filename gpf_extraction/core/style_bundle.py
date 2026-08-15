"""Téléchargement, mise en cache et correspondance des styles (SLD)
référencés par le catalogue de métadonnées (`core/csw_client.py`).

Une ressource de style peut être soit un fichier `.sld` isolé, soit une
archive `.zip` en contenant plusieurs (cas de la BD TOPO® : un paquet
"Styles Géoserver" avec un `.sld` par table). Dans les deux cas, on finit
avec une liste de fichiers `.sld` candidats, à faire correspondre au nom de
chaque table extraite.
"""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..network.http_client import NetworkClient
from .csw_client import StyleResource
from .text_utils import normalize

#: Dossier de cache (persiste entre les lancements de QGIS, évite de
#: retélécharger les mêmes paquets de styles à chaque extraction).
CACHE_ROOT = Path(tempfile.gettempdir()) / "gpf_extraction_styles"


@dataclass
class StyleCandidate:
    bundle_title: str
    sld_path: Path

    @property
    def label(self) -> str:
        return f"{self.bundle_title} — {self.sld_path.name}"


def fetch_style_files(resources: list[StyleResource]) -> list[StyleCandidate]:
    """Télécharge (avec cache disque) chaque ressource de style et renvoie
    la liste des fichiers `.sld` disponibles.

    Les échecs de téléchargement individuels sont ignorés silencieusement
    (fonctionnalité best-effort : l'absence de style ne doit jamais faire
    échouer l'extraction elle-même).

    :param resources: ressources de style à récupérer.
    :type resources: list[StyleResource]

    :return: fichiers `.sld` disponibles, avec le libellé de leur paquet
        d'origine.
    :rtype: list[StyleCandidate]
    """
    network = NetworkClient(authcfg="")
    candidates: list[StyleCandidate] = []

    for resource in resources:
        digest = hashlib.sha1(resource.url.encode("utf-8")).hexdigest()[:16]
        target_dir = CACHE_ROOT / digest
        suffix = Path(urlparse(resource.url).path).suffix.lower()

        try:
            if suffix == ".sld":
                sld_path = target_dir / "style.sld"
                if not sld_path.exists():
                    network.download_to_file(resource.url, sld_path, use_auth=False)
                candidates.append(StyleCandidate(resource.title, sld_path))

            elif suffix == ".zip":
                marker = target_dir / ".extracted"
                if not marker.exists():
                    zip_path = target_dir / "bundle.zip"
                    network.download_to_file(resource.url, zip_path, use_auth=False)
                    with zipfile.ZipFile(zip_path) as archive:
                        archive.extractall(target_dir)
                    marker.touch()
                for sld_path in sorted(target_dir.rglob("*.sld")):
                    candidates.append(StyleCandidate(resource.title, sld_path))
        except (ConnectionError, OSError, zipfile.BadZipFile):
            continue

    return candidates


def match_candidates_for_table(
    candidates: list[StyleCandidate], table_name: str
) -> list[StyleCandidate]:
    """Filtre les styles dont le nom de fichier correspond à une table.

    Tolère un préfixe (ex. `bdtopo_v3_batiment.sld` pour la table
    `batiment`), mais pas une simple sous-chaîne (pour éviter les faux
    positifs entre tables au nom proche, ex. `reservoir` et
    `reservoir_hydrographique`).

    :param candidates: fichiers de style disponibles.
    :type candidates: list[StyleCandidate]
    :param table_name: nom de la table extraite à styliser.
    :type table_name: str

    :return: styles candidats pour cette table (peut être vide, un seul, ou
        plusieurs).
    :rtype: list[StyleCandidate]
    """
    normalized_table = normalize(table_name)
    if not normalized_table:
        return []
    matches = []
    for candidate in candidates:
        stem = normalize(candidate.sld_path.stem)
        if stem == normalized_table or stem.endswith(normalized_table):
            matches.append(candidate)
    return matches
