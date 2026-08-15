#! python3  # noqa: E265

"""
    Main plugin module.
"""

# standard
from functools import partial
from pathlib import Path

# PyQGIS
from qgis.core import QgsApplication, QgsProject, QgsSettings
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QWidget

# project
from bd_topo_extractor.__about__ import (
    DIR_PLUGIN_ROOT,
    __icon_path__,
    __plugin_name__,
    __title__,
    __uri_homepage__,
)
from bd_topo_extractor.gui.dlg_main import BdTopoExtractorDialog
from bd_topo_extractor.gui.dlg_settings import PlgOptionsFactory
from bd_topo_extractor.processing import BdTopoExtractorProvider
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
        self.log = PlgLogger().log
        self.provider = None
        self.pluginIsActive = False
        self.action_launch = None
        self.dlg = None

        # translation
        # initialize the locale
        self.locale: str = QgsSettings().value("locale/userLocale", QLocale().name())[
            0:2
        ]
        locale_file = f"resources/i18n/{__title__.lower()}_{self.locale}.qm"
        locale_path: Path = DIR_PLUGIN_ROOT / locale_file
        self.log(message=f"Translation: {self.locale}, {locale_path}", log_level=4)
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
        self.iface.addPluginToMenu(f"{__plugin_name__}", self.action_launch)
        self.iface.addPluginToMenu(f"{__plugin_name__}", self.action_settings)
        self.iface.addPluginToMenu(f"{__plugin_name__}", self.action_help)

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
        self.iface.removePluginMenu(f"{__plugin_name__}", self.action_launch)
        self.iface.removeToolBarIcon(self.action_launch)
        self.iface.removePluginMenu(f"{__plugin_name__}", self.action_settings)

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
        """Main process : opens the extraction dialog.

        The dialog manages its own connected/disconnected state (see
        `BdTopoExtractorDialog`), so there is nothing else to check here.
        """
        # Check if plugin is already launched
        if not self.pluginIsActive:
            self.pluginIsActive = True
            self.dlg = BdTopoExtractorDialog(
                project=self.project, iface=self.iface, locale=self.locale
            )
            self.dlg.finished.connect(self._on_dialog_finished)
            self.dlg.show()
        else:
            # If the plugin is already launched, clicking on the plugin icon
            # will put back the window on top
            self.dlg.activateWindow()

    def _on_dialog_finished(self, _result: int) -> None:
        self.pluginIsActive = False
