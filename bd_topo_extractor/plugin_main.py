#! python3  # noqa: E265

"""
    Main plugin module.
"""

# standard
import datetime
import json
import os.path
from functools import partial
from pathlib import Path

import processing

# PyQGIS
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsSettings,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QLocale,
    QObject,
    QTimer,
    QTranslator,
    QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtNetwork import (  # noqa: E501
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QWidget

# project
from bd_topo_extractor.__about__ import (
    DIR_PLUGIN_ROOT,
    __icon_path__,
    __plugin_name__,
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __wfs_crs__,
    __wfs_layer_order__,
    __wfs_style__,
    __wfs_uri__,
)
from bd_topo_extractor.gui.dlg_main import BdTopoExtractorDialog
from bd_topo_extractor.gui.dlg_settings import PlgOptionsFactory
from bd_topo_extractor.processing import BdTopoExtractorProvider, WfsRequest
from bd_topo_extractor.toolbelt import PlgLogger

# ############################################################################
# ########## Classes ###############
# ##################################


class BdTopoExtractorPlugin:
    def __init__(self, iface: QgisInterface):
        """Constructor.

        :param iface: An interface instance \
            that will be passed to this class which \
        provides the hook by which you can manipulate \
            the QGIS application at run time.
        :type iface: QgsInterface
        """
        self.iface = iface
        self.project = QgsProject.instance()
        self.manager = QNetworkAccessManager()
        self.log = PlgLogger().log
        self.provider = None
        self.pluginIsActive = False
        self.url = __wfs_uri__
        self.action_launch = None

        # translation
        # initialize the locale
        self.locale: str = QgsSettings().value(
            "locale/userLocale", QLocale().name()
        )[  # noqa: E501
            0:2
        ]
        locale_path: Path = (
            DIR_PLUGIN_ROOT
            / f"resources/i18n/{__title__.lower()}_{self.locale}.qm"  # noqa: E501
        )
        self.log(
            message=f"Translation: {self.locale}, {locale_path}", log_level=4
        )  # noqa: E501
        if locale_path.exists():
            self.translator = QTranslator()
            self.translator.load(str(locale_path.resolve()))
            QCoreApplication.installTranslator(self.translator)

    def initGui(self):
        """Set up plugin UI elements."""

        # settings page within the QGIS preferences menu
        self.options_factory = PlgOptionsFactory()
        self.iface.registerOptionsWidgetFactory(self.options_factory)

        # -- Actions
        self.action_launch = QAction(
            QIcon(str(__icon_path__)),
            f"{__plugin_name__}",
            self.iface.mainWindow(),
        )
        self.iface.addToolBarIcon(self.action_launch)
        self.action_launch.triggered.connect(lambda: self.run())
        self.action_help = QAction(
            QgsApplication.getThemeIcon("mActionHelpContents.svg"),
            self.tr("Help"),
            self.iface.mainWindow(),
        )
        self.action_help.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.action_settings = QAction(
            QgsApplication.getThemeIcon("console/iconSettingsConsole.svg"),
            self.tr("Settings"),
            self.iface.mainWindow(),
        )
        self.action_settings.triggered.connect(
            lambda: self.iface.showOptionsDialog(
                currentPage=f"mOptionsPage{__title__}"
            )  # noqa: E501
        )

        # -- Menu
        self.iface.addPluginToMenu(
            f"{__plugin_name__}", self.action_launch
        )  # noqa: E501
        self.iface.addPluginToMenu(
            f"{__plugin_name__}", self.action_settings
        )  # noqa: E501
        self.iface.addPluginToMenu(f"{__plugin_name__}", self.action_help)  # noqa: E501

        # -- Processing
        self.initProcessing()

        # -- Help menu

        # documentation
        self.iface.pluginHelpMenu().addSeparator()
        self.action_help_plugin_menu_documentation = QAction(
            QIcon(str(__icon_path__)),
            f"{__plugin_name__} - Documentation",
            self.iface.mainWindow(),
        )
        self.action_help_plugin_menu_documentation.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.iface.pluginHelpMenu().addAction(
            self.action_help_plugin_menu_documentation
        )

    def initProcessing(self):
        self.provider = BdTopoExtractorProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def create_gpf_plugins_actions(self, parent: QWidget) -> list[QAction]:
        """Create action to be inserted a Geoplateforme plugin

        :param parent: parent widget
        :type parent: QWidget
        :return: list of action to add in Geoplateforme plugin
        :rtype: list[QAction]
        """
        available_actions = []
        available_actions.append(self.action_launch)

        return available_actions

    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API.

        :param message: string to be translated.
        :type message: str

        :returns: Translated version of message.
        :rtype: str
        """
        return QCoreApplication.translate(self.__class__.__name__, message)

    def unload(self):
        """Cleans up when plugin is disabled/uninstalled."""
        # -- Clean up menu
        self.iface.removePluginMenu(
            f"{__plugin_name__}", self.action_launch
        )  # noqa: E501
        self.iface.removeToolBarIcon(self.action_launch)
        self.iface.removePluginMenu(
            f"{__plugin_name__}", self.action_help
        )  # noqa: E501
        self.iface.removePluginMenu(
            f"{__plugin_name__}", self.action_settings
        )  # noqa: E501

        # -- Clean up preferences panel in QGIS settings
        self.iface.unregisterOptionsWidgetFactory(self.options_factory)

        # -- Unregister processing
        QgsApplication.processingRegistry().removeProvider(self.provider)

        # remove from QGIS help/extensions menu
        if self.action_help_plugin_menu_documentation:
            self.iface.pluginHelpMenu().removeAction(
                self.action_help_plugin_menu_documentation
            )

        # remove actions
        del self.action_launch
        del self.action_settings
        del self.action_help
        self.pluginIsActive = False

    def run(self):
        """Main process.

        Try to connect to internet, if successfull, the dialog appear.
        Else an error message appear.
        """
        self.internet_checker = InternetChecker(None, self.manager)
        self.internet_checker.finished.connect(self.handle_finished)
        self.internet_checker.ping(
            f"{self.url}?service=wfs&request=GetCapabilities"
        )  # noqa: E501

    def handle_finished(self):
        # Check if plugin is already launched
        if not self.pluginIsActive:
            self.pluginIsActive = True
            # Open Dialog
            self.dlg = BdTopoExtractorDialog(
                self.project, self.iface, self.url, self.manager, self.locale
            )
            self.dlg.show()
            # If there is no layers, Plan IGN V2 is added
            # to simplify the rectangle drawing
            if len(self.project.instance().mapLayers()) == 0:
                # Type of WMTS, url and name

                uri = "contextualWMSLegend=0&tileMatrixSet={tilematset}&tilePixelRatio=0&crs={crs}&dpiMode=7&featureCount=10&format={format}&layers={layers}&styles={styles}&url={url}".format(  # noqa: E501
                    tilematset="PM",
                    crs="EPSG:3857",
                    format="image/png",
                    layers="GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2",
                    styles="normal",
                    url="https://data.geopf.fr/wmts?SERVICE%3DWMTS%26REQUEST%3DGetCapabilities",  # noqa: E501
                )
                name = "Plan IGN V2"
                provider = "wms"

                # Add WMTS to the QgsProject
                self.iface.addRasterLayer(uri, name, provider)
            else:
                pass
            self.dlg.getcapabilities.finished_dl.connect(self.launch_zoom)
            result = self.dlg.exec()
            if result:
                # If dialog is accepted, "OK" is pressed, the process is launch
                self.processing()
            else:
                # Else the dialog close and plugin can be launched again
                self.pluginIsActive = False
        # If the plugin is already launched, clicking on the plugin icon will
        # put back the window on top
        else:
            self.dlg.activateWindow()

    def launch_zoom(self):
        # This timer is necessary in case there is no layer in the project
        # Without the timer canvas extent does not change
        QTimer.singleShot(750, self.zoom_to_extent)

    def zoom_to_extent(self):
        # Reproject the max bounding box of the wfs
        transformed_extent = self.transform_crs(
            self.dlg.getcapabilities.max_bounding_box,
            QgsCoordinateReferenceSystem("EPSG:" + str(__wfs_crs__)),
            self.project.crs(),
        )
        if transformed_extent.contains(self.iface.mapCanvas().extent()):
            pass
        else:
            self.iface.mapCanvas().zoomToFeatureExtent(transformed_extent)

    def add_style(self, layer, group):
        theme = None

        # If styled layer are set to true in metadata.txt,
        # a specific style is applied to every layer.
        if self.dlg.style_checkbox.isChecked():
            # style name is based on layer name in
            # uppercase with underscore instead of spaces
            # and single quotes
            style_name = (
                str(layer.name()).replace("'", "_").replace(" ", "_").upper()
            )  # noqa: E501
            if __wfs_layer_order__ == "":
                # style name is based on layer name in uppercase with
                # underscore instead of spaces and single quotes
                style_name = (
                    str(layer.name())
                    .replace("'", "_")
                    .replace(" ", "_")
                    .upper()  # noqa: E501
                )
                style_name_ext = style_name + ".qml"
                style_path: Path = (
                    DIR_PLUGIN_ROOT
                    / f'{"resources/styles"}'
                    / f"{style_name_ext}"  # noqa: E501
                )
                # if the style exists it is added to the layer.
                if os.path.isfile(style_path.__str__()):
                    layer.loadNamedStyle(style_path.__str__())
                else:
                    print(
                        "ERROR : style "
                        + str(style_name_ext)
                        + " doesn't exists."  # noqa: E501
                    )

                group.addLayer(layer)
            else:
                layer_order_dict = json.loads(__wfs_layer_order__)
                # the layer are ordered based on a dictionnary
                # with theme as key.
                for elem in layer_order_dict:
                    if style_name in list(layer_order_dict[elem].keys()):
                        theme = group.findGroup(elem)
                        # if the theme doesn't exists
                        # it is created.
                        if not theme:
                            group.insertGroup(
                                int(layer_order_dict["ORDER"][elem]),
                                elem,
                            )
                            theme = group.findGroup(elem)

                if not theme:
                    theme = group.findGroup("AUTRE")

                    if not theme:
                        group.insertGroup(
                            int(layer_order_dict["ORDER"]["AUTRE"]),
                            "AUTRE",
                        )
                        theme = group.findGroup("AUTRE")
                    theme.addLayer(layer)
                else:
                    theme.addLayer(layer)
                    style_name_ext = style_name + ".qml"
                    style_path: Path = (
                        DIR_PLUGIN_ROOT
                        / f'{"resources/styles"}'
                        / f"{style_name_ext}"  # noqa: E501
                    )
                    # if the style exists it is added to the layer.
                    if os.path.isfile(style_path.__str__()):
                        layer.loadNamedStyle(style_path.__str__())
                    else:
                        print(
                            "ERROR : style "
                            + str(style_name_ext)
                            + " doesn't exists."  # noqa: E501
                        )
        else:
            group.addLayer(layer)

    def processing(self):
        """Processing chain if the dialog is accepted
        Depending on user's choices, a folder can be created, the wfs is
        requested and the layers in the specific extent can be added to
        the QGIS project

        """
        # Show the dialog back for the ProgressBar
        self.dlg.show()

        # Creation of the folder name
        today = datetime.datetime.now()
        year = today.year
        month = today.strftime("%m")
        day = today.strftime("%d")
        hour = today.strftime("%H")
        minute = today.strftime("%M")
        folder = (
            "BDTopoExport_"
            + str(year)
            + str(month)
            + str(day)
            + "_"
            + str(hour)
            + str(minute)
        )
        if self.dlg.save_result_checkbox.isChecked():
            # Creation of the folder
            path = self.dlg.line_edit_output_folder.text() + "/" + str(folder)
            if not os.path.exists(path):
                os.makedirs(path)
        else:
            path = None

        # Creation of a group of layers to store the results of the request
        if self.dlg.add_to_project_checkbox.isChecked():
            self.project.instance().layerTreeRoot().insertGroup(0, folder)
            group = self.project.instance().layerTreeRoot().findGroup(folder)
        # Fetch if the results must be clipped or kept full
        for button in self.dlg.geom_button_group.buttons():
            if button.isChecked():
                result_geometry = button.accessibleName()
        # Fetch the number of data requested by the user
        max = 0
        for button in self.dlg.layer_check_group.buttons():
            if button.isChecked():
                max = max + 1
        # Set the ProgressBar
        self.dlg.thread.set_max(max)
        n = 0
        error_list = []
        good_list = []
        # Download the layer for every data asked by the user
        for button in self.dlg.layer_check_group.buttons():
            if button.isChecked():
                request = WfsRequest(
                    project=self.project,
                    iface=self.iface,
                    url=self.url,
                    data=button.accessibleName(),
                    crs=self.dlg.crs_selector.crs(),
                    boundingbox=self.dlg.extent,
                    path=path,
                    schema=self.dlg.schema,
                    geom=result_geometry,
                    format=self.dlg.output_format(),
                    error=error_list,
                    good=good_list,
                )
                n = n + 1
                if request.wfs_layer and request.wfs_layer.featureCount() > 0:
                    self.process_wfs_layer(
                        request.wfs_layer, group, path, result_geometry
                    )
                # Increase the ProgressBar value
                self.dlg.thread.add_one()
                self.dlg.dl_progress_bar_label.setText(
                    self.tr("Downloaded data : ")  # noqa: E501
                )
                self.dlg.select_progress_bar_label.setText(
                    str(n) + "/" + str(max)
                )  # noqa: E501
        msg = QMessageBox()
        msg.information(
            None,
            self.tr("Informations"),
            self.tr("No data number : ")
            + str(len(error_list))
            + "\n"
            + self.tr("Data number : ")
            + str(len(good_list))
            + "\n"
            + self.tr("Total data : ")
            + str(n),
        )
        # Once it's finished, the ProgressBar is set back to 0
        self.dlg.thread.finish()
        self.dlg.select_progress_bar_label.setText("")
        self.dlg.thread.reset_value()
        self.dlg.close()
        self.pluginIsActive = False

    def transform_crs(self, rectangle, input_crs, output_crs):
        # Reproject a rectangle to the project crs
        geom = QgsGeometry().fromRect(rectangle)
        geom.transform(
            QgsCoordinateTransform(input_crs, output_crs, self.project)  # noqa: E501
        )
        transformed_extent = geom.boundingBox()
        return transformed_extent

    def process_wfs_layer(self, wfs_layer, group, path, result_geometry):
        # Check if the layer needs to be clipped with the extent.
        if result_geometry != "intersect":
            # Output for a memory layer.
            output = "memory:" + str(wfs_layer.name()) + "_memory"

            # Check geometry type to create a memory layer to get
            # all features from the WFS request.
            geom_type = QgsWkbTypes.geometryDisplayString(
                wfs_layer.getFeature(1).geometry().type()
            )
            if geom_type == "Line":
                geom_type = "Linestring"
            # Create a memory layer
            memory_layer = QgsVectorLayer(
                geom_type + "?crs=epsg:" + str(__wfs_crs__),
                str(wfs_layer.name()),
                "memory",
            )
            # Add all features to the memory layer
            attr = wfs_layer.dataProvider().fields().toList()
            memory_layer.dataProvider().addAttributes(attr)
            memory_layer.startEditing()
            for feature in wfs_layer.getFeatures():
                memory_layer.dataProvider().addFeatures([feature])
                memory_layer.updateExtents()
            memory_layer.commitChanges()
            memory_layer.triggerRepaint()
            # Creation of a layer with the extent.
            if result_geometry == "within":
                clipping_layer = QgsVectorLayer(
                    "Polygon?crs=epsg:" + str(__wfs_crs__), "clipper", "memory"
                )
                clipping_layer.startEditing()
                new_geom = QgsGeometry().fromRect(self.dlg.extent)
                new_feature = QgsFeature(clipping_layer.fields())
                new_feature.setGeometry(new_geom)
                clipping_layer.dataProvider().addFeatures([new_feature])
                clipping_layer.updateExtents()
                clipping_layer.commitChanges()
                clipping_layer.triggerRepaint()
            else:
                clipping_layer = self.dlg.select_layer_combo_box.currentLayer()

            # Clip the layer with the extent.
            clip_parameters = {
                "INPUT": memory_layer,
                "OVERLAY": clipping_layer,
                "OUTPUT": "memory:" + str(wfs_layer.name()),
            }
            wfs_layer = processing.run("native:clip", clip_parameters)["OUTPUT"]

        if not self.dlg.save_result_checkbox.isChecked():
            if (
                result_geometry == "within"
                and self.dlg.crs_selector.crs() != QgsCoordinateReferenceSystem(4326)
            ):
                # Reproject the memory layer to the right crs
                reproject_parameter = {
                    "INPUT": wfs_layer,
                    "TARGET_CRS": self.dlg.crs_selector.crs(),
                    "OUTPUT": "memory:" + str(wfs_layer.name()),
                }

                wfs_layer = processing.run(
                    "native:reprojectlayer", reproject_parameter
                )["OUTPUT"]
            self.project.instance().addMapLayer(wfs_layer, False)  # noqa: E501
            # If styled layer are set to true in metadata.txt,
            # a specific style is applied to every layer.
            if __wfs_style__:
                self.add_style(wfs_layer, group)
            else:
                group.addLayer(wfs_layer)
        else:
            context = self.project.instance().transformContext()
            options = QgsVectorFileWriter.SaveVectorOptions()
            tr = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:" + str(__wfs_crs__)),
                self.dlg.crs_selector.crs(),
                self.project.instance(),
            )
            options.ct = tr
            options.layerName = str(wfs_layer.name())
            options.fileEncoding = wfs_layer.dataProvider().encoding()
            if self.dlg.output_format() == "gpkg":  # TODO save style in geopackage
                # Specific procedure if the layer must be saved as a GPKG.
                # Every data are saved in the same GeoPackage.
                options.driverName = "GPKG"
                # Check if the GeoPackage already exists,
                # to know if it's need to be created or not
                if os.path.isfile(path + "/" + "bd_topo_extract.gpkg"):  # noqa: E501
                    options.actionOnExistingFile = (
                        QgsVectorFileWriter.CreateOrOverwriteLayer
                    )

                if Qgis.QGIS_VERSION_INT > 32000:
                    QgsVectorFileWriter.writeAsVectorFormatV3(
                        wfs_layer,
                        path + "/" + "bd_topo_extract.gpkg",
                        context,
                        options,
                    )
                else:
                    QgsVectorFileWriter.writeAsVectorFormatV2(
                        wfs_layer,
                        path + "/" + "bd_topo_extract.gpkg",
                        context,
                        options,
                    )
                uri = "{}|layername={}".format(
                    path + "/" + "bd_topo_extract.gpkg",
                    wfs_layer.name(),
                )
                # Create layer
                self.final_layer = QgsVectorLayer(uri, wfs_layer.name(), "ogr")
            else:
                # Creation of the output path used for SHP and GeoJSON.
                output = (
                    path
                    + "/"
                    + str(wfs_layer.name())
                    + "."
                    + str(self.dlg.output_format())  # noqa: E501
                )
                # For every other format, the procedure is the same.
                if self.dlg.output_format() == "shp":
                    options.driverName = "ESRI Shapefile"
                elif self.dlg.output_format() == "geojson":
                    options.driverName = "GeoJSON"
                if Qgis.QGIS_VERSION_INT > 32000:
                    QgsVectorFileWriter.writeAsVectorFormatV3(
                        wfs_layer,
                        output,
                        context,
                        options,
                    )
                else:
                    QgsVectorFileWriter.writeAsVectorFormatV2(
                        wfs_layer,
                        output,
                        context,
                        options,
                    )
                self.final_layer = QgsVectorLayer(
                    output,
                    str(wfs_layer.name()),
                    "ogr",
                )
            if self.dlg.add_to_project_checkbox.isChecked():
                self.project.instance().addMapLayer(
                    self.final_layer, False  # noqa: E501
                )
                # If styled layer are set to true in metadata.txt,
                # a specific style is applied to every layer.
                if __wfs_style__:
                    self.add_style(self.final_layer, group)
                else:
                    group.addLayer(self.final_layer)


class InternetChecker(QObject):
    """Constructor.

    Class wich is going to ping a website
    to know if the user is connected to internet.
    """

    finished = pyqtSignal()

    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self._manager = manager
        self.manager.finished.connect(self.handle_finished)

    @property
    def manager(self):
        return self._manager

    @property
    def pending_ping(self):
        return self._pending_ping

    def ping(self, url):
        qrequest = QNetworkRequest(QUrl(url))
        self.manager.get(qrequest)

    def handle_finished(self, reply):
        if reply.error() != QNetworkReply.NoError:
            # If the user has an internet connexion issue,
            # the plugin does not launch.
            msg = QMessageBox()
            # IGN is down
            if reply.error() == 403:
                msg.critical(
                    None,
                    self.tr("Error"),
                    self.tr("IGN Services' are down."),
                )
            # No internet connexion
            elif reply.error() == 3:
                msg.critical(
                    None,
                    self.tr("Error"),
                    self.tr("You are not connected to the Internet."),
                )
            # Else, might be a plugin issue
            else:
                msg.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        f"Code error : {str(reply.error())}<br>Go to<br><a href={__uri_tracker__}>FramaGit</a><br>to report the issue."  # noqa: E501
                    ),
                )
        else:
            self.finished.emit()
