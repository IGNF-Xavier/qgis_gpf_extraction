#! python3  # noqa: E265

"""Chargement du résultat téléchargé d'un job dans le projet QGIS : ajout
des couches et application des styles trouvés au catalogue CSW, si trouvés.

Fonctions indépendantes de tout dialogue appelant : réutilisées aussi bien
par le suivi en direct d'un job (`dlg_job_monitor.py`) que par la reprise
différée d'un job déjà téléchargé (`dlg_jobs.py`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from qgis.core import QgsMapLayer, QgsProject, QgsProviderRegistry, QgsProviderSublayerDetails
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QWidget

from gpf_extraction.core.csw_client import CswClient
from gpf_extraction.core.gpkg_merge import merge_geopackages
from gpf_extraction.core.style_bundle import fetch_style_files, match_candidates_for_table
from gpf_extraction.gui.dlg_style_choice import StyleChoiceDialog

LogFn = Callable[[str], None]

#: Nom de fichier par défaut pour le GeoPackage fusionné, quand
#: l'utilisateur n'en a pas fourni (cf. `dlg_main.py`).
_DEFAULT_MERGED_GPKG_NAME = "extraction"

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _noop(_message: str) -> None:
    pass


def _tr(message: str) -> str:
    return QCoreApplication.translate("JobResultLoader", message)


def _sanitize_filename(name: str) -> str:
    """Nettoie un nom fourni par l'utilisateur pour en faire un nom de
    fichier Windows valide (retire l'extension éventuelle et les
    caractères interdits)."""
    name = Path(name.strip()).stem if name.strip() else ""
    name = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    return name


def add_result_to_project(
    path: Path, project: QgsProject, log: LogFn = _noop
) -> list[QgsMapLayer]:
    """Tente d'ajouter le fichier téléchargé au projet QGIS comme couche(s)
    vecteur.

    Le format exact renvoyé par le service n'étant pas garanti (archive
    zip, GeoPackage, ...), cette fonction reste best-effort : en cas
    d'échec, le fichier reste disponible sur disque et l'appelant en est
    informé via `log`.

    Utilise `QgsProviderRegistry.querySublayers` (API recommandée depuis
    QGIS 3.18) plutôt que l'ancien couple `dataProvider().subLayers()` +
    `QgsVectorLayer.sublayerSeparator()` — ce dernier a disparu de
    `QgsVectorLayer` dans les versions récentes de QGIS (constaté sur
    3.40 : `AttributeError`). `querySublayers` gère uniformément le cas
    d'une seule couche comme celui de plusieurs.

    :return: les couches effectivement ajoutées au projet (peut être vide).
    :rtype: list[QgsMapLayer]
    """
    added_layers: list[QgsMapLayer] = []

    # Résultat compressé en 7z (`compression=7zip` explicitement choisi par
    # l'utilisateur) : archive potentiellement fractionnée en plusieurs
    # volumes (ex. "export.7z.0001"), non exploitable directement par
    # QGIS/GDAL sans dépendance externe. On le signale clairement plutôt
    # que de tenter un chargement voué à l'échec.
    if ".7z" in path.name.lower():
        log(
            _tr(
                "Le résultat est une archive 7z ({}) : décompressez-la manuellement "
                "(7-Zip ou équivalent) puis chargez le fichier obtenu dans QGIS. Pour "
                "un fichier directement exploitable, ne renseignez pas le paramètre "
                "« compression » lors de l'extraction."
            ).format(path.name)
        )
        return added_layers

    candidate_path = str(path)
    if path.suffix.lower() == ".zip":
        candidate_path = f"/vsizip/{path}"

    sublayers = QgsProviderRegistry.instance().querySublayers(candidate_path)
    if not sublayers:
        log(
            _tr(
                "Le résultat n'a pas pu être chargé automatiquement comme couche "
                "vecteur. Fichier disponible ici : {}"
            ).format(path)
        )
        return added_layers

    options = QgsProviderSublayerDetails.LayerOptions(project.transformContext())
    for sublayer in sublayers:
        layer = sublayer.toLayer(options)
        if layer is not None and layer.isValid():
            project.addMapLayer(layer)
            added_layers.append(layer)

    if added_layers:
        log(_tr("Résultat ajouté au projet ({} couche(s)).").format(len(added_layers)))
    else:
        log(
            _tr(
                "Le résultat n'a pas pu être chargé automatiquement comme couche "
                "vecteur. Fichier disponible ici : {}"
            ).format(path)
        )
    return added_layers


def apply_styles(
    layers: list[QgsMapLayer],
    product_name: str,
    log: LogFn = _noop,
    parent: Optional[QWidget] = None,
) -> None:
    """Cherche, télécharge et applique les styles (SLD) référencés par le
    catalogue de métadonnées CSW pour le produit extrait, s'il y en a.

    Fonctionnalité entièrement best-effort : toute erreur (réseau, absence
    de fiche, absence de style...) est simplement journalisée via `log`,
    sans jamais lever d'exception vers l'appelant.
    """
    if not product_name or not layers:
        return

    try:
        csw_client = CswClient()
        record_id = csw_client.find_record_id(product_name)
        if not record_id:
            log(
                _tr(
                    "Aucune fiche de métadonnées trouvée pour « {} » : pas de style "
                    "appliqué automatiquement."
                ).format(product_name)
            )
            return

        resources = csw_client.get_style_resources(record_id)
        if not resources:
            log(_tr("Aucun style référencé pour « {} ».").format(product_name))
            return

        log(_tr("Styles trouvés dans le catalogue, téléchargement..."))
        candidates = fetch_style_files(resources)
    except Exception as exc:  # noqa: BLE001 - fonctionnalité best-effort
        log(_tr("Recherche/téléchargement des styles CSW échoué : {}").format(exc))
        return

    if not candidates:
        log(_tr("Aucun fichier de style exploitable n'a été trouvé."))
        return

    ambiguous: dict[str, list] = {}
    layers_by_name: dict[str, QgsMapLayer] = {}
    for layer in layers:
        layers_by_name[layer.name()] = layer
        matches = match_candidates_for_table(candidates, layer.name())
        if len(matches) == 1:
            _apply_sld(layer, matches[0].sld_path, log)
        elif len(matches) > 1:
            ambiguous[layer.name()] = matches

    if ambiguous:
        dlg = StyleChoiceDialog(ambiguous, parent=parent)
        if dlg.exec():
            for layer_name, choice in dlg.get_choices().items():
                if choice is not None:
                    _apply_sld(layers_by_name[layer_name], choice.sld_path, log)


def _apply_sld(layer: QgsMapLayer, sld_path: Path, log: LogFn = _noop) -> None:
    message, ok = layer.loadSldStyle(str(sld_path))
    if ok:
        layer.triggerRepaint()
        log(_tr("Style « {} » appliqué à « {} ».").format(sld_path.name, layer.name()))
    else:
        log(
            _tr("Échec de l'application du style « {} » à « {} » : {}").format(
                sld_path.name, layer.name(), message
            )
        )


def load_result(
    path: Path,
    project: QgsProject,
    product_name: str,
    log: LogFn = _noop,
    parent: Optional[QWidget] = None,
) -> list[QgsMapLayer]:
    """Ajoute le résultat téléchargé au projet et tente d'y appliquer les
    styles trouvés au catalogue CSW. Combine `add_result_to_project` et
    `apply_styles`."""
    layers = add_result_to_project(path, project, log)
    if layers:
        apply_styles(layers, product_name, log, parent)
    return layers


def load_results(
    paths: list[Path],
    project: QgsProject,
    product_name: str,
    log: LogFn = _noop,
    parent: Optional[QWidget] = None,
    merge_name: str = "",
) -> list[QgsMapLayer]:
    """Ajoute au projet tous les fichiers de résultat d'un job téléchargés
    en une fois, puis applique les styles trouvés au catalogue CSW **une
    seule fois** pour l'ensemble des couches obtenues (plutôt qu'une
    recherche CSW répétée par fichier).

    Constaté en conditions réelles : le service d'extraction peut produire
    un fichier GeoPackage distinct par table plutôt qu'un unique fichier
    multi-couches. Quand c'est le cas (plusieurs `.gpkg` reçus), ces
    fichiers sont d'abord fusionnés en un seul GeoPackage nommé (cf.
    `core/gpkg_merge.py`) avant ajout au projet — best-effort : en cas
    d'échec de la fusion, on retombe sur un ajout fichier par fichier.

    :param paths: fichiers téléchargés pour ce job (les métadonnées
        `.json` sont ignorées).
    :type paths: list[Path]
    :param merge_name: nom (sans extension) souhaité pour le GeoPackage
        fusionné ; nom par défaut si vide.
    :type merge_name: str, optional

    :return: les couches effectivement ajoutées au projet.
    :rtype: list[QgsMapLayer]
    """
    data_paths = [p for p in paths if p.suffix.lower() != ".json"]
    gpkg_paths = [p for p in data_paths if p.suffix.lower() == ".gpkg"]
    other_paths = [p for p in data_paths if p.suffix.lower() != ".gpkg"]

    layers: list[QgsMapLayer] = []

    if len(gpkg_paths) > 1:
        filename = _sanitize_filename(merge_name) or _DEFAULT_MERGED_GPKG_NAME
        dest_path = gpkg_paths[0].parent / f"{filename}.gpkg"
        try:
            merged_path, merged_layers = merge_geopackages(gpkg_paths, dest_path)
        except Exception as exc:  # noqa: BLE001 - best-effort, on retombe sur les fichiers séparés
            log(
                _tr(
                    "Échec de la fusion des {} GeoPackages en un seul fichier ({}) : "
                    "les fichiers séparés sont conservés."
                ).format(len(gpkg_paths), exc)
            )
            for gpkg_path in gpkg_paths:
                layers.extend(add_result_to_project(gpkg_path, project, log))
        else:
            log(
                _tr(
                    "{} GeoPackage(s) fusionné(s) en un seul fichier : {} ({} couche(s))."
                ).format(len(gpkg_paths), merged_path.name, len(merged_layers))
            )
            layers.extend(add_result_to_project(merged_path, project, log))
    elif len(gpkg_paths) == 1 and merge_name.strip():
        # Un seul GeoPackage reçu (le serveur a peut-être bien tout fusionné
        # lui-même) : la fusion n'a rien à faire, mais l'utilisateur a quand
        # même choisi un nom explicite pour ce fichier — un simple
        # renommage suffit (pas besoin de repasser par GDAL pour ça).
        filename = _sanitize_filename(merge_name) or _DEFAULT_MERGED_GPKG_NAME
        dest_path = gpkg_paths[0].parent / f"{filename}.gpkg"
        source_path = gpkg_paths[0]
        try:
            if dest_path != source_path:
                if dest_path.exists():
                    dest_path.unlink()
                source_path = source_path.rename(dest_path)
        except OSError as exc:
            log(
                _tr(
                    "Impossible de renommer le GeoPackage en « {} » ({}) : nom d'origine conservé."
                ).format(dest_path.name, exc)
            )
        layers.extend(add_result_to_project(source_path, project, log))
    else:
        for gpkg_path in gpkg_paths:
            layers.extend(add_result_to_project(gpkg_path, project, log))

    for other_path in other_paths:
        layers.extend(add_result_to_project(other_path, project, log))

    if layers:
        apply_styles(layers, product_name, log, parent)
    return layers
