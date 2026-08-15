#! python3  # noqa: E265

"""
    Plugin settings form integrated into QGIS 'Options' menu.
"""

# standard
from functools import partial

# PyQGIS
from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

# project
from bd_topo_extractor.__about__ import (
    __icon_path__,
    __plugin_name__,
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __version__,
)
from bd_topo_extractor.core.constants import DEFAULT_API_BASE
from bd_topo_extractor.gui.dlg_authentication import AuthenticationDialog
from bd_topo_extractor.toolbelt import PlgLogger, PlgOptionsManager
from bd_topo_extractor.toolbelt.preferences import PlgSettingsStructure

# ############################################################################
# ########## Classes ###############
# ##################################


class ConfigOptionsPage(QgsOptionsPageWidget):
    """Settings form embedded into QGIS 'options' menu."""

    def __init__(self, parent):
        super().__init__(parent)
        self.log = PlgLogger().log
        self.plg_settings = PlgOptionsManager()

        self.setObjectName(f"mOptionsPage{__title__}")

        layout = QVBoxLayout(self)

        title_label = QLabel(f"{__plugin_name__} - Version {__version__}")
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)

        # -- Authentification --------------------------------------------
        auth_group = QGroupBox(self.tr("Connexion à la Géoplateforme"))
        auth_layout = QVBoxLayout(auth_group)

        self.lbl_auth_status = QLabel()
        self.lbl_auth_status.setWordWrap(True)
        auth_layout.addWidget(self.lbl_auth_status)

        auth_buttons_layout = QHBoxLayout()
        self.btn_connect = QPushButton(self.tr("Se connecter..."))
        self.btn_connect.clicked.connect(self._open_authentication_dialog)
        auth_buttons_layout.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton(self.tr("Se déconnecter"))
        self.btn_disconnect.clicked.connect(self._disconnect)
        auth_buttons_layout.addWidget(self.btn_disconnect)
        auth_buttons_layout.addStretch(1)
        auth_layout.addLayout(auth_buttons_layout)

        layout.addWidget(auth_group)

        # -- API ------------------------------------------------------------
        api_form = QFormLayout()
        self.txt_api_base = QLineEdit()
        self.txt_api_base.setPlaceholderText(DEFAULT_API_BASE)
        api_form.addRow(self.tr("URL de l'API d'extraction :"), self.txt_api_base)
        layout.addLayout(api_form)

        # -- Global -----------------------------------------------------
        self.opt_debug = QCheckBox(self.tr("Mode débogage"))
        layout.addWidget(self.opt_debug)

        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel(self.tr("Version enregistrée :")))
        self.lbl_version_saved_value = QLabel()
        version_layout.addWidget(self.lbl_version_saved_value)
        version_layout.addStretch(1)
        layout.addLayout(version_layout)

        layout.addStretch(1)

        # -- Footer buttons ------------------------------------------------
        footer_layout = QHBoxLayout()
        self.btn_help = QPushButton()
        self.btn_help.setIcon(QIcon(QgsApplication.iconPath("mActionHelpContents.svg")))
        self.btn_help.setText(self.tr("Aide"))
        self.btn_help.pressed.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )
        footer_layout.addWidget(self.btn_help)

        self.btn_report = QPushButton()
        self.btn_report.setIcon(
            QIcon(QgsApplication.iconPath("console/iconSyntaxErrorConsole.svg"))
        )
        self.btn_report.setText(self.tr("Signaler un problème"))
        self.btn_report.pressed.connect(
            partial(QDesktopServices.openUrl, QUrl(f"{__uri_tracker__}/new/choose"))
        )
        footer_layout.addWidget(self.btn_report)

        self.btn_reset = QPushButton()
        self.btn_reset.setIcon(QIcon(QgsApplication.iconPath("mActionUndo.svg")))
        self.btn_reset.setText(self.tr("Réinitialiser"))
        self.btn_reset.pressed.connect(self.reset_settings)
        footer_layout.addWidget(self.btn_reset)

        footer_layout.addStretch(1)
        layout.addLayout(footer_layout)

        # load previously saved settings
        self.load_settings()

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------
    def _open_authentication_dialog(self) -> None:
        dlg = AuthenticationDialog(self)
        if dlg.exec():
            self._refresh_auth_status()

    def _disconnect(self) -> None:
        PlgOptionsManager.disconnect()
        self._refresh_auth_status()

    def _refresh_auth_status(self) -> None:
        settings = self.plg_settings.get_plg_settings()
        if settings.qgis_auth_id:
            auth_config = QgsApplication.authManager().availableAuthMethodConfigs().get(
                settings.qgis_auth_id
            )
            name = auth_config.name() if auth_config else settings.qgis_auth_id
            self.lbl_auth_status.setText(
                self.tr("Connecté ({})").format(name)
            )
            self.btn_disconnect.setEnabled(True)
        else:
            self.lbl_auth_status.setText(self.tr("Non connecté."))
            self.btn_disconnect.setEnabled(False)

    # ------------------------------------------------------------------
    # QgsOptionsPageWidget
    # ------------------------------------------------------------------
    def apply(self):
        """Called to permanently apply the settings shown in the options
        page (e.g. save them to QgsSettings objects). This is usually
        called when the options dialog is accepted."""
        settings = self.plg_settings.get_plg_settings()

        settings.debug_mode = self.opt_debug.isChecked()
        settings.api_base = self.txt_api_base.text().strip() or DEFAULT_API_BASE
        settings.version = __version__

        self.plg_settings.save_from_object(settings)

        if __debug__:
            self.log(message="DEBUG - Settings successfully saved.", log_level=4)

    def load_settings(self):
        """Load options from QgsSettings into UI form."""
        settings = self.plg_settings.get_plg_settings()

        self.opt_debug.setChecked(settings.debug_mode)
        self.txt_api_base.setText(settings.api_base)
        self.lbl_version_saved_value.setText(settings.version)
        self._refresh_auth_status()

    def reset_settings(self):
        """Reset settings to default values (set in preferences.py module)."""
        default_settings = PlgSettingsStructure()
        default_settings.qgis_auth_id = (
            self.plg_settings.get_plg_settings().qgis_auth_id
        )

        self.plg_settings.save_from_object(default_settings)
        self.load_settings()


class PlgOptionsFactory(QgsOptionsWidgetFactory):
    """Factory for options widget."""

    def __init__(self):
        """Constructor."""
        super().__init__()

    def icon(self) -> QIcon:
        """Returns plugin icon, used to as tab icon in QGIS options tab widget."""
        return QIcon(str(__icon_path__))

    def createWidget(self, parent) -> ConfigOptionsPage:
        """Create settings widget."""
        return ConfigOptionsPage(parent)

    def title(self) -> str:
        """Returns plugin title, used to name the tab in QGIS options tab widget."""
        return f"{__plugin_name__}"

    def helpId(self) -> str:
        """Returns plugin help URL."""
        return __uri_homepage__
