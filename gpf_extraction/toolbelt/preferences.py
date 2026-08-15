#! python3  # noqa: E265

"""
    Plugin settings.
"""

# standard
from dataclasses import asdict, dataclass, fields
from typing import Optional

# PyQGIS
from qgis.core import QgsSettings

# package
import gpf_extraction.toolbelt.log_handler as log_hdlr
from gpf_extraction.__about__ import __title__, __version__
from gpf_extraction.core.constants import (
    DEFAULT_API_BASE,
    DEFAULT_STATUS_CHECK_SLEEP,
)

# ############################################################################
# ########## Classes ###############
# ##################################


@dataclass
class PlgSettingsStructure:
    """Plugin settings structure and defaults values."""

    # global
    debug_mode: bool = False
    version: str = __version__

    # network and authentication
    api_base: str = DEFAULT_API_BASE
    qgis_auth_id: Optional[str] = None

    # extraction jobs
    status_check_sleep: int = DEFAULT_STATUS_CHECK_SLEEP
    last_output_dir: str = ""


class PlgOptionsManager:
    @staticmethod
    def disconnect(delete_config: bool = False) -> None:
        """Déconnecte l'utilisateur en oubliant la configuration d'authentification
        utilisée.

        :param delete_config: si True, supprime aussi la configuration
            d'authentification de QGIS. À ne faire que si elle a été créée
            par ce plugin (une configuration réutilisée, par ex. celle du
            plugin officiel Géoplateforme, ne doit jamais être supprimée
            depuis ici), defaults to False.
        :type delete_config: bool, optional
        """
        from qgis.core import QgsApplication

        plg_settings = PlgOptionsManager.get_plg_settings()
        if delete_config and plg_settings.qgis_auth_id:
            QgsApplication.authManager().removeAuthenticationConfig(
                plg_settings.qgis_auth_id
            )
        plg_settings.qgis_auth_id = None
        PlgOptionsManager.save_from_object(plg_settings)

    @staticmethod
    def get_plg_settings() -> PlgSettingsStructure:
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings
        :rtype: PlgSettingsStructure
        """
        # get dataclass fields definition
        settings_fields = fields(PlgSettingsStructure)

        # retrieve settings from QGIS/Qt
        settings = QgsSettings()
        settings.beginGroup(__title__)

        # map settings values to preferences object
        li_settings_values = []
        for i in settings_fields:
            try:
                li_settings_values.append(
                    settings.value(key=i.name, defaultValue=i.default, type=i.type)
                )
            except TypeError:
                # occurs for typing constructs QgsSettings can't coerce to
                # (e.g. Optional[str]) : fall back to an untyped read.
                li_settings_values.append(
                    settings.value(key=i.name, defaultValue=i.default)
                )

        # instanciate new settings object
        options = PlgSettingsStructure(*li_settings_values)

        settings.endGroup()

        return options

    @staticmethod
    def get_value_from_key(key: str, default=None, exp_type=None):
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings value matching key
        """
        if not hasattr(PlgSettingsStructure, key):
            log_hdlr.PlgLogger.log(
                message="Bad settings key. Must be one of: {}".format(
                    ",".join(PlgSettingsStructure._fields)
                ),
                log_level=1,
            )
            return None

        settings = QgsSettings()
        settings.beginGroup(__title__)

        try:
            out_value = settings.value(
                key=key, defaultValue=default, type=exp_type
            )  # noqa: E501
        except Exception as err:
            log_hdlr.PlgLogger.log(
                message="Error occurred trying to get settings: {}.Trace: {}".format(  # noqa: E501
                    key, err
                )
            )
            out_value = None

        settings.endGroup()

        return out_value

    @classmethod
    def set_value_from_key(cls, key: str, value) -> bool:
        """Set plugin QSettings value using the key.

        :param key: QSettings key
        :type key: str
        :param value: value to set
        :type value: depending on the settings
        :return: operation status
        :rtype: bool
        """
        if not hasattr(PlgSettingsStructure, key):
            log_hdlr.PlgLogger.log(
                message="Bad settings key. Must be one of: {}".format(
                    ",".join(PlgSettingsStructure._fields)
                ),
                log_level=2,
            )
            return False

        settings = QgsSettings()
        settings.beginGroup(__title__)

        try:
            settings.setValue(key, value)
            out_value = True
        except Exception as err:
            log_hdlr.PlgLogger.log(
                message="Error occurred trying to set settings: {}.Trace: {}".format(  # noqa: E501
                    key, err
                )
            )
            out_value = False

        settings.endGroup()

        return out_value

    @classmethod
    def save_from_object(cls, plugin_settings_obj: PlgSettingsStructure):
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings value matching key
        """
        settings = QgsSettings()
        settings.beginGroup(__title__)

        for k, v in asdict(plugin_settings_obj).items():
            cls.set_value_from_key(k, v)

        settings.endGroup()
