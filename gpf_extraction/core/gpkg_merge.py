#! python3  # noqa: E265

"""Fusion de plusieurs GeoPackages mono-table en un seul GeoPackage multi-couches.

Constaté en conditions réelles : le service d'extraction peut produire un
fichier GeoPackage distinct par table plutôt qu'un unique fichier
multi-couches, même avec l'input `append` à `true` (censé, d'après la
documentation du processus, produire "un seul fichier en sortie pour
l'ensemble des relations"). Cette fusion côté client garantit à
l'utilisateur un fichier unique et nommé, indépendamment du comportement
réel du serveur.
"""

from __future__ import annotations

from pathlib import Path

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsProviderRegistry,
    QgsProviderSublayerDetails,
    QgsVectorFileWriter,
)


def merge_geopackages(paths: list[Path], dest_path: Path) -> tuple[Path, list[str]]:
    """Fusionne plusieurs fichiers GeoPackage en un seul fichier multi-couches.

    Chaque couche source est recopiée telle quelle (mêmes attributs, même
    géométrie), sous son nom de table d'origine (dédoublonné en cas de
    collision).

    :param paths: fichiers `.gpkg` sources (un ou plusieurs, une ou
        plusieurs couches chacun).
    :type paths: list[Path]
    :param dest_path: fichier GeoPackage de destination (écrasé si déjà présent).
    :type dest_path: Path

    :raises RuntimeError: si une couche source n'a pas pu être copiée.

    :return: le fichier fusionné et les noms des couches qu'il contient.
    :rtype: tuple[Path, list[str]]
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()

    context = QgsCoordinateTransformContext()
    added_layers: list[str] = []
    first = True

    for src_path in paths:
        sublayers = QgsProviderRegistry.instance().querySublayers(str(src_path))
        for sublayer in sublayers:
            layer = sublayer.toLayer(QgsProviderSublayerDetails.LayerOptions(context))
            if layer is None or not layer.isValid():
                continue

            layer_name = sublayer.name() or src_path.stem
            base_name = layer_name
            suffix = 2
            while layer_name in added_layers:
                layer_name = f"{base_name}_{suffix}"
                suffix += 1

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile
                if first
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )
            error, _new_filename, _new_layer, err_msg = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, str(dest_path), context, options
            )
            if error != QgsVectorFileWriter.NoError:
                raise RuntimeError(
                    f"Échec de la fusion de « {src_path.name} » (couche « {layer_name} ») "
                    f"dans « {dest_path.name} » : {err_msg}"
                )
            added_layers.append(layer_name)
            first = False

    return dest_path, added_layers


def build_generation_report(
    requested_tables: int,
    delivered: int,
    removed_layers: list[str],
    download_failures: list[str],
) -> tuple[list[str], bool]:
    """Construit les lignes du rapport de génération affiché après un
    téléchargement, et signale le cas où le résultat est **entièrement
    vide** malgré un job signalé réussi par le serveur.

    Ce dernier cas est distinct d'un simple écart partiel (une ou deux
    tables sans entité dans l'emprise est courant et normal) : quand
    *toutes* les couches livrées finissent vides, le GeoPackage résultant
    n'a plus aucune couche exploitable — constaté en conditions réelles
    avec une extraction multi-tables (hydrographie) sur une emprise à
    l'échelle de la France entière, avec fusion (`append`) activée : le
    serveur répond « SUCCESS » pour chaque table en quelques secondes à
    peine (bien trop rapide pour un vrai traitement à cette échelle), et le
    fichier livré est un GeoPackage valide mais sans aucune donnée. Ce cas
    mérite un avertissement qu'on ne peut pas manquer, pas seulement une
    ligne dans un rapport qu'on peut facilement ne pas lire.

    :return: (lignes du rapport, True si le résultat est entièrement vide).
    :rtype: tuple[list[str], bool]
    """
    report_lines: list[str] = []
    all_empty = False

    if requested_tables:
        report_lines.append(
            f"{requested_tables} table(s) demandée(s), {delivered} couche(s) livrée(s) par le serveur."
        )
        remaining = delivered - len(removed_layers)
        # `remaining <= 0` couvre aussi bien le cas où le serveur n'a livré
        # aucune couche du tout (`delivered == 0`, ex. GeoPackage sans une
        # seule entrée `gpkg_contents` — constaté en conditions réelles) que
        # celui où des couches ont été livrées mais toutes vidées ensuite par
        # `remove_empty_layers` : dans les deux cas, il ne reste absolument
        # rien d'exploitable malgré un job signalé réussi.
        if remaining <= 0:
            all_empty = True
        elif delivered != requested_tables:
            report_lines.append(
                "⚠ Écart entre le nombre de tables demandées et de couches livrées "
                "— vérifiez la sélection et les journaux ci-dessus."
            )

    if removed_layers:
        report_lines.append(
            f"{len(removed_layers)} couche(s) vide(s) (0 entité) retirée(s) : "
            + ", ".join(sorted(removed_layers))
        )

    if download_failures:
        report_lines.append(
            f"⚠ {len(download_failures)} fichier(s) n'ont pas pu être téléchargés : "
            + "; ".join(download_failures)
        )

    return report_lines, all_empty


def count_layers(paths: list[Path]) -> int:
    """Compte le nombre total de couches exploitables dans une liste de
    fichiers (somme sur chaque fichier), sans les charger entièrement.

    Utilisé pour comparer, dans le rapport de génération, le nombre de
    tables demandées à la soumission au nombre de couches effectivement
    livrées par le serveur — indépendamment d'une éventuelle fusion ou
    d'un ajout au projet.
    """
    registry = QgsProviderRegistry.instance()
    return sum(len(registry.querySublayers(str(p))) for p in paths)


def remove_empty_layers(paths: list[Path]) -> list[str]:
    """Retire des fichiers GeoPackage donnés toute couche ne contenant
    aucune entité.

    Une extraction par emprise produit souvent des tables vides pour les
    objets absents de la zone demandée (ex. `aerodrome` hors de toute
    emprise survolant un aérodrome) : l'utilisateur préfère un GeoPackage
    ne listant que les couches réellement peuplées plutôt que d'avoir à
    les repérer et les masquer lui-même dans le panneau des couches.

    Modifie les fichiers en place. Fonctionnalité best-effort : un fichier
    illisible par GDAL/OGR est simplement ignoré plutôt que de faire
    échouer tout le nettoyage.

    :param paths: fichiers à nettoyer (seuls les `.gpkg` sont traités).
    :type paths: list[Path]

    :return: noms des couches retirées (tous fichiers confondus).
    :rtype: list[str]
    """
    from osgeo import ogr

    removed: list[str] = []
    for path in paths:
        if path.suffix.lower() != ".gpkg":
            continue
        datasource = ogr.Open(str(path), update=1)
        if datasource is None:
            continue

        empty_layers = []
        for index in range(datasource.GetLayerCount()):
            layer = datasource.GetLayerByIndex(index)
            if layer is not None and layer.GetFeatureCount() == 0:
                empty_layers.append((index, layer.GetName()))

        # Supprime en partant de l'index le plus élevé : la suppression
        # d'une couche décale les index de celles qui suivent.
        for index, name in sorted(empty_layers, key=lambda item: item[0], reverse=True):
            if datasource.DeleteLayer(index) == 0:  # OGRERR_NONE
                removed.append(name)
        datasource = None

    return removed
