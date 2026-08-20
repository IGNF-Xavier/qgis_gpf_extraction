#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit des styles (SLD/QML/JSON Mapbox/...) disponibles sur le catalogue CSW de la
Géoplateforme, mis en correspondance avec les couches WFS et les tuiles vectorielles
TMS (.pbf) réellement servies.

Script de développement autonome (aucune dépendance à `gpf_extraction` ni à QGIS) :
sert à objectiver, sur l'ensemble du catalogue (pas seulement la BD TOPO), la
limitation documentée dans gpf_extraction/README_fr.md ("Limitations connues" :
découverte de styles via le CSW = contournement coûteux et heuristique).

Trois axes croisés :
  - métadonnée -> styles : quels fichiers de style (SLD, QML, JSON Mapbox, ...) une
    fiche CSW référence, y compris dézippés d'une archive ;
  - métadonnée <-> WFS/TMS : quelles couches WFS et quelles tuiles TMS .pbf sont
    liées à quelle fiche (via le lien retour MetadataURL déclaré par le service
    lui-même, pas par déduction de nom) ;
  - services -> métadonnée (sens inverse) : quels FeatureType WFS et quelles tuiles
    TMS .pbf n'ont AUCUNE fiche de métadonnées associée, et pour les TMS qui en ont
    une, est-ce que leurs propres styles vectoriels sont référencés dans cette fiche.

Sortie : un classeur Excel (.xlsx) avec un unique tableau (colonne `type_ligne` pour
distinguer les natures de ligne), un bloc résumé à base de formules, et un
commentaire par ligne expliquant le diagnostic.

Usage :
    python tools/audit_csw_styles.py [--output FICHIER.xlsx] [--limit N] [--record-id ID]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

# ---------------------------------------------------------------------------
# Constantes / configuration
# ---------------------------------------------------------------------------

CSW_BASE_URL = "https://data.geopf.fr/csw"
WFS_CAPABILITIES_URL = (
    "https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities"
)
TMS_ROOT_URL = "https://data.geopf.fr/tms/1.0.0"

NS = {
    "csw": "http://www.opengis.net/cat/csw/2.0.2",
    "dc": "http://purl.org/dc/elements/1.1/",
    "gmd": "http://www.isotc211.org/2005/gmd",
    "gco": "http://www.isotc211.org/2005/gco",
    "wfs": "http://www.opengis.net/wfs/2.0",
    "xlink": "http://www.w3.org/1999/xlink",
}

REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (audit_csw_styles.py)"

#: Mots-clés (en minuscules) évoquant un style, cherchés dans la description ou
#: l'URL d'une ressource CSW — même principe que `_STYLE_HINTS` dans
#: gpf_extraction/core/csw_client.py, étendu à quelques synonymes.
STYLE_HINTS = ("style", "sld", "légende", "legende", "legend", "mapbox", "mbstyle", "qml")

#: Extensions considérées comme un fichier de style à part entière, qu'il y ait ou
#: non un mot-clé dans la description de la ressource qui le référence.
DIRECT_STYLE_EXTENSIONS = {".sld", ".qml"}

#: Extensions retenues lors du dézippage d'une archive candidate (le reste —
#: documentation, xsd, images... — est ignoré).
ZIP_STYLE_EXTENSIONS = {".sld", ".qml", ".json", ".lyr", ".qlr", ".se", ".xml"}

FORMAT_LABELS = {
    ".sld": "SLD",
    ".qml": "QML",
    ".lyr": "Autre (.lyr)",
    ".qlr": "Autre (.qlr)",
    ".se": "Autre (.se)",
}

#: Cache disque pour les archives de style téléchargées (évite de re-télécharger la
#: même archive à chaque relance du script), par hash de l'URL.
CACHE_ROOT = Path(tempfile.gettempdir()) / "gpf_csw_audit_cache"

#: Préfixe de produit versionné toléré en tête d'un nom de fichier de style, avant
#: comparaison au nom nu d'une couche (ex. "bdtopo_v3_batiment" -> "batiment").
_VERSIONED_PREFIX_RE = re.compile(r"^[a-z]+_v\d+_")

#: Articles/prépositions français ignorés des deux côtés lors de la comparaison
#: (l'IGN est incohérent sur leur présence d'un fichier à l'autre).
_IGNORED_TOKENS = {"de", "du", "des", "d", "la", "le", "les", "l"}

#: Coquille connue dans le paquet de styles Géoserver de la BD TOPO (portée depuis
#: gpf_extraction/core/style_bundle.py) : le style existe bien pour la table visée,
#: mais son nom de fichier contient une faute de frappe qu'aucune règle générique ne
#: peut deviner.
_KNOWN_TYPOS = {
    "bdtopo_v3_surface_hydrograpgique": "bdtopo_v3_surface_hydrographique",
}


def log(message: str) -> None:
    print(message, flush=True)


def _get(url: str, timeout: int = REQUEST_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _normalize_for_matching(text: str, *, strip_versioned_prefix: bool = False) -> str:
    text = text.lower()
    if strip_versioned_prefix:
        text = _VERSIONED_PREFIX_RE.sub("", text, count=1)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _IGNORED_TOKENS]
    return "".join(tokens)


def _extract_metadata_id(href: str) -> Optional[str]:
    """Extrait l'identifiant `ID` d'un lien `MetadataURL`/`Metadata` de type CSW
    (ex. `https://data.geopf.fr/csw?...&ID=IGNF_BD-TOPO`), ou None si ce lien ne
    pointe pas vers le catalogue CSW (ex. lien html cartes.gouv.fr, à ignorer)."""
    if not href or "data.geopf.fr/csw" not in href:
        return None
    query = parse_qs(urlparse(href).query)
    for key, values in query.items():
        if key.upper() == "ID" and values:
            return values[0]
    return None


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------


@dataclass
class FeatureTypeInfo:
    qualified_name: str
    bare_name: str
    metadata_id: Optional[str]


@dataclass
class TmsEntry:
    name: str
    href: str
    metadata_id: Optional[str] = None
    style_urls: list[str] = field(default_factory=list)


@dataclass
class StyleFile:
    resource_title: str
    resource_url: str
    filename: str
    format_label: str


@dataclass
class Row:
    type_ligne: str
    id_metadonnee: str = ""
    titre_metadonnee: str = ""
    lien_metadonnee: str = ""
    couche_qualifiee: str = ""
    couche: str = ""
    tms_nom: str = ""
    ressource_titre: str = ""
    ressource_url: str = ""
    fichier: str = ""
    format: str = ""
    diagnostic: str = ""


# ---------------------------------------------------------------------------
# Phase 1 : préchargements globaux (WFS, TMS)
# ---------------------------------------------------------------------------


def load_wfs_feature_types() -> list[FeatureTypeInfo]:
    log("Chargement du GetCapabilities WFS global...")
    t0 = time.time()
    body = _get(WFS_CAPABILITIES_URL, timeout=60)
    root = ET.fromstring(body)
    infos: list[FeatureTypeInfo] = []
    for ft in root.iterfind(".//wfs:FeatureType", NS):
        name = ft.findtext("wfs:Name", default="", namespaces=NS).strip()
        if not name:
            continue
        bare = name.split(":", 1)[1] if ":" in name else name
        metadata_id = None
        for murl in ft.iterfind("wfs:MetadataURL", NS):
            href = murl.get(f"{{{NS['xlink']}}}href", "")
            metadata_id = _extract_metadata_id(href)
            if metadata_id:
                break
        infos.append(FeatureTypeInfo(qualified_name=name, bare_name=bare, metadata_id=metadata_id))
    log(f"  -> {len(infos)} FeatureType ({time.time() - t0:.1f}s)")
    return infos


def load_tms_pbf_entries() -> list[TmsEntry]:
    log("Chargement du root TMS global...")
    t0 = time.time()
    body = _get(TMS_ROOT_URL, timeout=60)
    root = ET.fromstring(body)
    entries: list[TmsEntry] = []
    for tm in root.findall(".//TileMap"):
        if tm.get("extension", "").lower() != "pbf":
            continue
        href = tm.get("href", "")
        name = href.rstrip("/").rsplit("/", 1)[-1] if href else tm.get("title", "")
        if name:
            entries.append(TmsEntry(name=name, href=href))
    log(f"  -> {len(entries)} TileMap .pbf ({time.time() - t0:.1f}s)")
    return entries


def load_tms_details(entries: list[TmsEntry]) -> None:
    """Complète chaque `TmsEntry` (en place) avec son `metadata_id` et ses
    `style_urls`, en interrogeant son document `TileMap` individuel."""
    log(f"Chargement du détail de {len(entries)} TileMap .pbf...")
    for i, entry in enumerate(entries, start=1):
        if i == 1 or i % 10 == 0 or i == len(entries):
            log(f"  [{i}/{len(entries)}] {entry.name}")
        try:
            body = _get(entry.href)
            root = ET.fromstring(body)
        except Exception as exc:  # noqa: BLE001 - catalogue public hétérogène, une entrée récalcitrante ne doit jamais interrompre le run
            print(f"    ! échec {entry.name} : {exc}", file=sys.stderr)
            continue
        for meta in root.findall(".//Metadata"):
            href = meta.get("href", "")
            mime = meta.get("mime-type", "")
            meta_type = meta.get("type", "")
            if meta_type == "ISO19115:2003":
                entry.metadata_id = _extract_metadata_id(href)
            elif meta_type == "Other" and mime == "application/json":
                entry.style_urls.append(href)


# ---------------------------------------------------------------------------
# Phase 2 : listing des fiches CSW (brèves)
# ---------------------------------------------------------------------------


def load_brief_records() -> list[tuple[str, str]]:
    log("Listage des fiches CSW (GetRecords, pages de 100)...")
    page_size = 100
    start_position = 1
    records: list[tuple[str, str]] = []
    for _ in range(30):  # garde-fou
        url = (
            f"{CSW_BASE_URL}?service=CSW&version=2.0.2&request=GetRecords"
            "&typeNames=csw:Record&resultType=results&elementSetName=brief"
            f"&maxRecords={page_size}&startPosition={start_position}"
        )
        body = _get(url, timeout=60)
        root = ET.fromstring(body)
        for brief in root.iterfind(".//csw:BriefRecord", NS):
            identifier = brief.findtext("dc:identifier", default="", namespaces=NS).strip()
            title = brief.findtext("dc:title", default="", namespaces=NS).strip()
            if identifier and title:
                records.append((identifier, title))
        search_results = root.find(".//csw:SearchResults", NS)
        next_record = int(search_results.get("nextRecord", "0")) if search_results is not None else 0
        if next_record <= 0:
            break
        start_position = next_record
    log(f"  -> {len(records)} fiches")
    return records


# ---------------------------------------------------------------------------
# Phase 3 : styles d'une fiche (téléchargement, dézippage, classification)
# ---------------------------------------------------------------------------


def _sniff_format(path: Path) -> str:
    """Classification fine par contenu, pour les extensions ambiguës."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            return "JSON (autre)"
        if isinstance(data, dict) and "version" in data and ("layers" in data or "sources" in data):
            return "JSON (style Mapbox)"
        return "JSON (autre)"
    if suffix == ".xml":
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return None  # noqa: RET501 - pas un fichier de style exploitable
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "StyledLayerDescriptor":
            return "SLD"
        return None
    return FORMAT_LABELS.get(suffix, f"Autre ({suffix})")


def fetch_style_resources(record_root: ET.Element) -> list[tuple[str, str]]:
    """Ressources de style candidates d'une fiche complète : (titre, url)."""
    candidates: list[tuple[str, str]] = []
    for online in record_root.iterfind(".//gmd:CI_OnlineResource", NS):
        url = online.findtext("gmd:linkage/gmd:URL", default="", namespaces=NS).strip()
        desc = online.findtext("gmd:description/gco:CharacterString", default="", namespaces=NS).strip()
        if not url:
            continue
        suffix = Path(urlparse(url).path).suffix.lower()
        haystack = f"{desc} {url}".lower()
        is_hinted = any(hint in haystack for hint in STYLE_HINTS)
        if suffix in DIRECT_STYLE_EXTENSIONS or (is_hinted and suffix == ".zip"):
            candidates.append((desc or url, url))
    return candidates


def resolve_style_files(resource_title: str, resource_url: str) -> list[StyleFile]:
    """Télécharge (avec cache) une ressource de style et renvoie les fichiers de
    style qu'elle contient (elle-même si fichier direct, son contenu si archive)."""
    suffix = Path(urlparse(resource_url).path).suffix.lower()
    digest = hashlib.sha1(resource_url.encode("utf-8")).hexdigest()[:16]
    target_dir = CACHE_ROOT / digest
    results: list[StyleFile] = []

    try:
        if suffix in DIRECT_STYLE_EXTENSIONS:
            dest = target_dir / ("style" + suffix)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(_get(resource_url))
            fmt = FORMAT_LABELS.get(suffix, f"Autre ({suffix})")
            results.append(StyleFile(resource_title, resource_url, dest.name, fmt))
        elif suffix == ".zip":
            marker = target_dir / ".extracted"
            if not marker.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                zip_path = target_dir / "bundle.zip"
                zip_path.write_bytes(_get(resource_url))
                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(target_dir)
                marker.touch()
            for member in sorted(target_dir.rglob("*")):
                if not member.is_file() or member.suffix.lower() not in ZIP_STYLE_EXTENSIONS:
                    continue
                fmt = _sniff_format(member) if member.suffix.lower() in (".json", ".xml") else FORMAT_LABELS.get(
                    member.suffix.lower(), f"Autre ({member.suffix.lower()})"
                )
                if fmt is None:
                    continue  # .xml qui n'est pas un SLD : pas un fichier de style
                results.append(StyleFile(resource_title, resource_url, member.name, fmt))
    except Exception as exc:  # noqa: BLE001 - catalogue public hétérogène, une ressource récalcitrante ne doit jamais interrompre le run
        print(f"    ! échec téléchargement/dézippage {resource_url} : {exc}", file=sys.stderr)

    return results


def match_style_to_layers(style_filename: str, layers_bare_names: list[str]) -> Optional[str]:
    """Retrouve, parmi les noms nus de couches d'une fiche, celui que ce fichier de
    style vise (retrait du préfixe versionné + articles français, correspondance
    exacte) — heuristique portée de gpf_extraction/core/style_bundle.py."""
    stem = Path(style_filename).stem.lower()
    stem = _KNOWN_TYPOS.get(stem, stem)
    normalized_stem = _normalize_for_matching(stem, strip_versioned_prefix=True)
    for bare in layers_bare_names:
        if _normalize_for_matching(bare) == normalized_stem:
            return bare
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_rows(
    limit: Optional[int],
    only_record_id: Optional[str],
) -> tuple[list[Row], dict]:
    wfs_types = load_wfs_feature_types()
    tms_entries = load_tms_pbf_entries()
    load_tms_details(tms_entries)

    wfs_by_record: dict[str, list[FeatureTypeInfo]] = {}
    for ft in wfs_types:
        if ft.metadata_id:
            wfs_by_record.setdefault(ft.metadata_id, []).append(ft)

    tms_by_record: dict[str, list[TmsEntry]] = {}
    for tms in tms_entries:
        if tms.metadata_id:
            tms_by_record.setdefault(tms.metadata_id, []).append(tms)

    brief_records = load_brief_records()
    if only_record_id:
        brief_records = [(rid, title) for rid, title in brief_records if rid == only_record_id]
    elif limit:
        brief_records = brief_records[:limit]

    rows: list[Row] = []
    retained = 0

    log(f"Traitement de {len(brief_records)} fiches CSW...")
    for i, (record_id, title) in enumerate(brief_records, start=1):
        if i == 1 or i % 20 == 0 or i == len(brief_records):
            log(f"  [{i}/{len(brief_records)}] {record_id}")

        record_layers = wfs_by_record.get(record_id, [])
        record_tms = tms_by_record.get(record_id, [])

        # Certaines fiches ont un dc:identifier non conforme (ex. le titre en clair,
        # avec espaces/accents, au lieu d'un slug) — quote() est indispensable pour
        # ne pas planter la construction de la requête HTTP (constaté en conditions
        # réelles : http.client.InvalidURL sur un identifiant contenant des espaces).
        record_id_quoted = quote(record_id, safe="")

        try:
            record_url = (
                f"{CSW_BASE_URL}?service=CSW&version=2.0.2&request=GetRecordById"
                f"&id={record_id_quoted}&elementSetName=full"
                "&outputSchema=http://www.isotc211.org/2005/gmd"
            )
            record_body = _get(record_url)
            record_root = ET.fromstring(record_body)
        except Exception as exc:  # noqa: BLE001 - catalogue public hétérogène, une fiche récalcitrante ne doit jamais interrompre le run
            print(f"    ! échec fiche {record_id} : {exc}", file=sys.stderr)
            continue

        style_candidates = fetch_style_resources(record_root)
        style_files: list[StyleFile] = []
        for res_title, res_url in style_candidates:
            style_files.extend(resolve_style_files(res_title, res_url))

        if not record_layers and not record_tms and not style_files:
            continue  # rien d'intéressant sur cette fiche pour cet audit
        retained += 1

        lien_metadonnee = (
            f"{CSW_BASE_URL}?service=CSW&version=2.0.2&request=GetRecordById"
            f"&id={record_id_quoted}&elementSetName=full"
        )

        bare_names = [ft.bare_name for ft in record_layers]
        matched_bare_names: set[str] = set()

        # -- lignes "couche_wfs" : une par couche WFS liée à cette fiche
        for ft in record_layers:
            matching_style = None
            for sf in style_files:
                if match_style_to_layers(sf.filename, [ft.bare_name]):
                    matching_style = sf
                    matched_bare_names.add(ft.bare_name)
                    break
            row = Row(
                type_ligne="couche_wfs",
                id_metadonnee=record_id,
                titre_metadonnee=title,
                lien_metadonnee=lien_metadonnee,
                couche_qualifiee=ft.qualified_name,
                couche=ft.bare_name,
            )
            if matching_style:
                row.ressource_titre = matching_style.resource_title
                row.ressource_url = matching_style.resource_url
                row.fichier = matching_style.filename
                row.format = matching_style.format_label
                row.diagnostic = "Style trouvé"
            else:
                row.diagnostic = "Aucun style trouvé pour cette couche"
            rows.append(row)

        # -- lignes "style_geoserver" : styles qui ne correspondent à AUCUNE couche
        #    de cette fiche (orphelins relatifs à cette fiche, y compris quand la
        #    fiche n'a aucune couche WFS du tout).
        for sf in style_files:
            target = match_style_to_layers(sf.filename, bare_names)
            if target:
                continue  # déjà rattaché à une ligne couche_wfs ci-dessus
            rows.append(
                Row(
                    type_ligne="style_geoserver",
                    id_metadonnee=record_id,
                    titre_metadonnee=title,
                    lien_metadonnee=lien_metadonnee,
                    ressource_titre=sf.resource_title,
                    ressource_url=sf.resource_url,
                    fichier=sf.filename,
                    format=sf.format_label,
                    diagnostic=(
                        "Style orphelin (aucune couche WFS dans cette fiche)"
                        if not record_layers
                        else "Style orphelin (ne correspond à aucune couche de cette fiche)"
                    ),
                )
            )

        # -- lignes "tms_style" : styles vectoriels déclarés par un TMS lié à cette fiche
        style_resource_urls = {sf.resource_url for sf in style_files}
        style_resource_names = {Path(urlparse(sf.resource_url).path).name for sf in style_files}
        for tms in record_tms:
            for style_url in tms.style_urls:
                style_name = Path(urlparse(style_url).path).name
                present = style_url in style_resource_urls or style_name in style_resource_names
                rows.append(
                    Row(
                        type_ligne="tms_style",
                        id_metadonnee=record_id,
                        titre_metadonnee=title,
                        lien_metadonnee=lien_metadonnee,
                        tms_nom=tms.name,
                        ressource_titre=style_name,
                        ressource_url=style_url,
                        fichier=style_name,
                        format="JSON (style Mapbox, TMS)",
                        diagnostic=(
                            "Style TMS présent dans la métadonnée"
                            if present
                            else "Style TMS absent de la métadonnée"
                        ),
                    )
                )

    # -- Phase 4 : écarts en sens inverse (services -> métadonnée)
    for ft in wfs_types:
        if ft.metadata_id is None:
            rows.append(
                Row(
                    type_ligne="wfs_orphelin",
                    couche_qualifiee=ft.qualified_name,
                    couche=ft.bare_name,
                    diagnostic="FeatureType WFS sans métadonnée liée (aucun MetadataURL CSW)",
                )
            )
    for tms in tms_entries:
        if tms.metadata_id is None:
            rows.append(
                Row(
                    type_ligne="tms_orphelin",
                    tms_nom=tms.name,
                    ressource_url=tms.href,
                    diagnostic="TMS .pbf sans métadonnée liée (aucun Metadata ISO19115:2003)",
                )
            )

    stats = {
        "fiches_scannees": len(brief_records),
        "fiches_retenues": retained,
        "wfs_total": len(wfs_types),
        "wfs_sans_metadonnee": sum(1 for ft in wfs_types if ft.metadata_id is None),
        "tms_pbf_total": len(tms_entries),
        "tms_pbf_sans_metadonnee": sum(1 for t in tms_entries if t.metadata_id is None),
    }
    return rows, stats


# ---------------------------------------------------------------------------
# Sortie Excel
# ---------------------------------------------------------------------------

HEADERS = [
    "type_ligne",
    "id_metadonnee",
    "titre_metadonnee",
    "lien_metadonnee",
    "couche_qualifiee",
    "couche",
    "tms_nom",
    "ressource_titre",
    "ressource_url",
    "fichier",
    "format",
    "diagnostic",
]

ROW_FILL_COLOR = {
    "couche_wfs": "D9EAD3",  # vert : couche WFS (avec ou sans style)
    "style_geoserver": "F9CB9C",  # orange : style orphelin (aucune couche correspondante)
    "tms_style": "FFE599",  # jaune : style déclaré par un TMS
    "wfs_orphelin": "EFEFEF",  # gris : service sans métadonnée
    "tms_orphelin": "EFEFEF",
}


def write_excel(rows: list[Row], stats: dict, out_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Audit styles CSW"

    font_name = "Arial"
    title_font = Font(name=font_name, size=14, bold=True)
    subtitle_font = Font(name=font_name, size=9, italic=True, color="666666")
    label_font = Font(name=font_name, size=10)
    value_font = Font(name=font_name, size=10, bold=True)
    header_font = Font(name=font_name, size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    cell_font = Font(name=font_name, size=10)
    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = "Audit des styles du catalogue CSW (Géoplateforme) — parallèle WFS / TMS .pbf"
    ws["A1"].font = title_font
    ws.merge_cells("A1:D1")
    ws["A2"] = "Généré par tools/audit_csw_styles.py — voir gpf_extraction/README_fr.md (Limitations connues)"
    ws["A2"].font = subtitle_font
    ws.merge_cells("A2:D2")

    # Nombre de lignes du bloc résumé ci-dessous : fixé ici (plutôt que déduit de
    # `len(summary)`) pour pouvoir calculer `data_first_row` — dont les formules du
    # résumé ont elles-mêmes besoin — AVANT de construire la liste `summary`. Une
    # incohérence entre ce nombre et le contenu réel de `summary` fait planter
    # l'assertion juste après la liste plutôt que de silencieusement faire chevaucher
    # le résumé et l'en-tête du tableau (bug constaté en conditions réelles : 3
    # lignes de résumé écrasées par l'en-tête/les premières lignes de données).
    SUMMARY_ROW_COUNT = 10
    data_first_row = 4 + SUMMARY_ROW_COUNT + 1  # +1 = ligne vide de séparation
    data_last_row = data_first_row + len(rows) - 1
    type_col = "A"
    type_range = f"{type_col}{data_first_row}:{type_col}{data_last_row}"

    summary = [
        ("Fiches CSW scannées", stats["fiches_scannees"]),
        ("Fiches retenues (au moins couche/TMS/style)", stats["fiches_retenues"]),
        ("Couches WFS totales liées à une fiche", f'=COUNTIF({type_range},"couche_wfs")'),
        (
            "  dont sans style trouvé",
            f'=COUNTIFS({type_range},"couche_wfs",{get_column_letter(HEADERS.index("diagnostic") + 1)}'
            f'{data_first_row}:{get_column_letter(HEADERS.index("diagnostic") + 1)}{data_last_row},'
            '"Aucun style trouvé pour cette couche")',
        ),
        ("Styles orphelins (aucune couche correspondante)", f'=COUNTIF({type_range},"style_geoserver")'),
        ("Styles déclarés par un TMS .pbf", f'=COUNTIF({type_range},"tms_style")'),
        ("FeatureType WFS total", stats["wfs_total"]),
        ("  dont SANS métadonnée liée", stats["wfs_sans_metadonnee"]),
        ("TMS .pbf total", stats["tms_pbf_total"]),
        ("  dont SANS métadonnée liée", stats["tms_pbf_sans_metadonnee"]),
    ]
    assert len(summary) == SUMMARY_ROW_COUNT, (
        f"SUMMARY_ROW_COUNT ({SUMMARY_ROW_COUNT}) doit rester égal au nombre de lignes "
        f"de `summary` ({len(summary)}), sous peine de chevaucher l'en-tête du tableau."
    )
    r = 4
    for label, value in summary:
        ws.cell(row=r, column=1, value=label).font = label_font
        v = ws.cell(row=r, column=2, value=value)
        v.font = value_font
        v.alignment = Alignment(horizontal="center")
        r += 1

    header_row = data_first_row - 1
    for col, header in enumerate(HEADERS, start=1):
        c = ws.cell(row=header_row, column=col, value=header)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        c.border = border

    for i, row in enumerate(rows):
        r = data_first_row + i
        values = [getattr(row, h) for h in HEADERS]
        fill = PatternFill("solid", fgColor=ROW_FILL_COLOR.get(row.type_ligne, "FFFFFF"))
        for col, value in enumerate(values, start=1):
            c = ws.cell(row=r, column=col, value=value)
            c.font = cell_font
            c.fill = fill
            c.border = border
            c.alignment = Alignment(vertical="center", wrap_text=(col == len(HEADERS)))
        diag_cell = ws.cell(row=r, column=HEADERS.index("diagnostic") + 1)
        if row.diagnostic:
            diag_cell.comment = Comment(row.diagnostic, "audit_csw_styles.py")

    widths = {
        "A": 16,
        "B": 20,
        "C": 34,
        "D": 46,
        "E": 26,
        "F": 20,
        "G": 16,
        "H": 30,
        "I": 46,
        "J": 30,
        "K": 20,
        "L": 40,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="csw_styles_audit.xlsx", help="Fichier Excel de sortie")
    parser.add_argument("--limit", type=int, default=None, help="Limite le nombre de fiches CSW traitées")
    parser.add_argument("--record-id", default=None, help="N'auditer qu'une fiche précise (déboguage)")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except AttributeError:
        pass

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl est requis : pip install openpyxl", file=sys.stderr)
        raise SystemExit(1)

    t0 = time.time()
    rows, stats = build_rows(limit=args.limit, only_record_id=args.record_id)
    log(f"{len(rows)} lignes générées ({time.time() - t0:.1f}s au total)")

    out_path = Path(args.output)
    write_excel(rows, stats, out_path)
    log(f"Écrit : {out_path.resolve()}")


if __name__ == "__main__":
    main()
