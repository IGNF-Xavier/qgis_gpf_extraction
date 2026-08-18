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
