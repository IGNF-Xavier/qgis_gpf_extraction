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

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMapLayer,
    QgsProject,
    QgsProviderRegistry,
    QgsProviderSublayerDetails,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QWidget

from gpf_extraction.core.csw_client import CswClient
from gpf_extraction.core.style_bundle import fetch_style_files, match_candidates_for_table
from gpf_extraction.gui.dlg_style_choice import StyleChoiceDialog

LogFn = Callable[[str], None]

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _noop(_message: str) -> None:
    pass


def _tr(message: str) -> str:
    return QCoreApplication.translate("JobResultLoader", message)


def _sanitize_filename(name: str) -> str:
    """Nettoie un nom fourni par l'utilisateur pour en faire un nom de
    fichier valide (retire une extension éventuelle et les caractères
    interdits sous Windows)."""
    name = Path(name.strip()).stem if name.strip() else ""
    return _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")


def _table_name_from_filename(path: Path) -> str:
    """Déduit un nom de table du nom de fichier renvoyé par le serveur (ex.
    `schema_xxx.departement.gpkg` -> `departement`), pour construire un nom
    de fichier lisible quand plusieurs GeoPackages doivent être renommés."""
    stem = path.stem
    return stem.rsplit(".", 1)[-1] if "." in stem else stem


def apply_gpkg_name(paths: list[Path], gpkg_name: str, log: LogFn = _noop) -> list[Path]:
    """Renomme le(s) fichier(s) `.gpkg` d'un résultat téléchargé d'après le
    nom choisi par l'utilisateur, plutôt que de garder celui donné par le
    serveur (ex. `data.gpkg`).

    Un seul fichier `.gpkg` reçu : renommé tel quel (`{gpkg_name}.gpkg`).
    Plusieurs (un par table, comportement observé du service même avec
    `append` activé) : chacun reçoit `{gpkg_name}_{table}.gpkg` — pas de
    fusion en un seul fichier (voir la note dans `load_results` sur ce
    choix). Les fichiers non-`.gpkg` (ex. `extraction.json`) ne sont pas
    concernés.

    :param paths: fichiers téléchargés pour ce job.
    :type paths: list[Path]
    :param gpkg_name: nom souhaité (sans extension) ; aucun effet si vide.
    :type gpkg_name: str

    :return: les chemins mis à jour (renommage best-effort : en cas d'échec
        d'un renommage, le chemin d'origine est conservé pour ce fichier).
    :rtype: list[Path]
    """
    sanitized = _sanitize_filename(gpkg_name)
    if not sanitized:
        return paths

    gpkg_paths = [p for p in paths if p.suffix.lower() == ".gpkg"]
    if not gpkg_paths:
        return paths

    renamed: dict[Path, Path] = {}
    multiple = len(gpkg_paths) > 1
    for src in gpkg_paths:
        filename = f"{sanitized}_{_table_name_from_filename(src)}.gpkg" if multiple else f"{sanitized}.gpkg"
        dest = src.parent / filename
        if dest == src:
            continue
        try:
            if dest.exists():
                dest.unlink()
            renamed[src] = src.rename(dest)
        except OSError as exc:
            log(_tr("Impossible de renommer « {} » en « {} » : {}").format(src.name, dest.name, exc))

    if renamed:
        log(
            _tr("GeoPackage renommé : {}").format(", ".join(p.name for p in renamed.values()))
            if len(renamed) == 1
            else _tr("GeoPackages renommés : {}").format(", ".join(p.name for p in renamed.values()))
        )

    return [renamed.get(p, p) for p in paths]


def _build_clip_overlay(wkt: str, source_crs: str, target_crs: QgsCoordinateReferenceSystem) -> Optional[QgsVectorLayer]:
    """Construit une couche mémoire à une entité portant la géométrie
    d'emprise, reprojetée dans `target_crs` (celui de la couche à découper) —
    plutôt que de compter sur une éventuelle reprojection interne de
    l'algorithme de découpage entre deux CRS différents."""
    geometry = QgsGeometry.fromWkt(wkt)
    if geometry.isNull() or geometry.isEmpty():
        return None

    crs_from = QgsCoordinateReferenceSystem(source_crs)
    if crs_from.isValid() and target_crs.isValid() and crs_from != target_crs:
        transform = QgsCoordinateTransform(crs_from, target_crs, QgsProject.instance())
        geometry.transform(transform)

    overlay = QgsVectorLayer(f"Polygon?crs={target_crs.authid()}", "emprise_decoupage", "memory")
    feature = QgsFeature(overlay.fields())
    feature.setGeometry(geometry)
    overlay.dataProvider().addFeature(feature)
    overlay.updateExtents()
    return overlay


def _clip_layer(layer: QgsMapLayer, wkt: str, crs: str, log: LogFn = _noop) -> QgsMapLayer:
    """Découpe une couche vecteur à la géométrie d'emprise (`native:clip`),
    et renvoie le résultat — best-effort : la couche d'origine (non
    découpée) est renvoyée telle quelle si le découpage échoue ou ne
    s'applique pas (couche non vectorielle, sans géométrie)."""
    if not isinstance(layer, QgsVectorLayer) or layer.geometryType() not in (
        QgsWkbTypes.GeometryType.PointGeometry,
        QgsWkbTypes.GeometryType.LineGeometry,
        QgsWkbTypes.GeometryType.PolygonGeometry,
    ):
        return layer

    try:
        import processing
    except ImportError:
        log(_tr("Découpage à l'emprise indisponible (module 'processing' introuvable)."))
        return layer

    overlay = _build_clip_overlay(wkt, crs, layer.crs())
    if overlay is None:
        return layer

    try:
        result = processing.run(
            "native:clip",
            {"INPUT": layer, "OVERLAY": overlay, "OUTPUT": "memory:"},
        )
        clipped = result["OUTPUT"]
        clipped.setName(layer.name())
    except Exception as exc:  # noqa: BLE001 - découpage best-effort, jamais bloquant
        log(_tr("Découpage de « {} » à l'emprise échoué : {} — couche non découpée conservée.").format(
            layer.name(), exc
        ))
        return layer

    log(_tr("« {} » découpée à l'emprise ({} entité(s)).").format(layer.name(), clipped.featureCount()))
    return clipped


def add_result_to_project(
    path: Path,
    project: QgsProject,
    log: LogFn = _noop,
    clip_wkt: str = "",
    clip_crs: str = "",
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

    :param clip_wkt: si fourni, chaque couche vecteur ajoutée est découpée
        (algorithme QGIS natif `native:clip`) à cette géométrie avant d'être
        ajoutée au projet — best-effort : en cas d'échec du découpage, la
        couche non découpée est ajoutée quand même plutôt que rien du tout.
        Aucun mécanisme serveur équivalent n'existe (vérifié : l'API refuse
        une expression de découpage dans `attributes`), c'est donc la seule
        façon d'obtenir des géométries coupées à l'emprise.
    :type clip_wkt: str, optional
    :param clip_crs: CRS (ex. `EPSG:4326`) de `clip_wkt`.
    :type clip_crs: str, optional

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
            if clip_wkt:
                layer = _clip_layer(layer, clip_wkt, clip_crs, log)
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
    gpkg_name: str = "",
    clip_wkt: str = "",
    clip_crs: str = "",
) -> list[QgsMapLayer]:
    """Ajoute au projet tous les fichiers de résultat d'un job téléchargés
    en une fois (un par fichier, sans fusion), puis applique les styles
    trouvés au catalogue CSW **une seule fois** pour l'ensemble des couches
    obtenues (plutôt qu'une recherche CSW répétée par fichier).

    Volontairement pas de fusion automatique en un seul GeoPackage côté
    client, même quand le service produit un fichier par table : cela
    masquerait le comportement réel de l'API (input `merge_into_one_file`,
    anciennement `append`) le temps de vérifier s'il est bien honoré côté
    serveur. Voir `core/gpkg_merge.py` si une fusion explicite est
    nécessaire malgré tout.

    :param paths: fichiers téléchargés pour ce job (les métadonnées
        `.json` sont ignorées).
    :type paths: list[Path]
    :param gpkg_name: nom souhaité pour le(s) fichier(s) `.gpkg` (voir
        `apply_gpkg_name`) ; aucun effet si vide (nom du serveur conservé).
    :type gpkg_name: str, optional
    :param clip_wkt: géométrie d'emprise (WKT) à laquelle découper chaque
        couche après ajout ; aucun effet si vide.
    :type clip_wkt: str, optional
    :param clip_crs: CRS de `clip_wkt`.
    :type clip_crs: str, optional

    :return: les couches effectivement ajoutées au projet.
    :rtype: list[QgsMapLayer]
    """
    data_paths = [p for p in paths if p.suffix.lower() != ".json"]
    if gpkg_name:
        data_paths = apply_gpkg_name(data_paths, gpkg_name, log)

    layers: list[QgsMapLayer] = []
    for data_path in data_paths:
        layers.extend(add_result_to_project(data_path, project, log, clip_wkt=clip_wkt, clip_crs=clip_crs))

    if layers:
        apply_styles(layers, product_name, log, parent)
    return layers
