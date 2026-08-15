#! python3  # noqa: E265

"""Boîte de dialogue d'authentification à la Géoplateforme.

Reprend les principes mis en oeuvre par le plugin officiel QGIS Géoplateforme
(`geoplateforme/gui/dlg_authentication.py`) : un bouton « Se connecter » crée
une configuration OAuth2 QGIS, l'enregistre dans le gestionnaire
d'authentification de QGIS, puis vérifie qu'elle fonctionne réellement avant
de l'adopter. Complété d'une section permettant de réutiliser une
configuration d'authentification déjà existante (par ex. celle créée par le
plugin officiel Géoplateforme, s'il est installé) via `QgsAuthConfigSelect` —
pattern déjà utilisé par l'auteur dans son plugin `gpf_validation`.
"""

from __future__ import annotations

from socket import AF_INET, SOCK_STREAM
from socket import error as socket_error
from socket import socket

from qgis.core import Qgis, QgsApplication, QgsAuthMethodConfig
from qgis.gui import QgsAuthConfigSelect, QgsMessageBar
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from bd_topo_extractor.core.constants import OAUTH_DECLARED_REDIRECT_PORTS
from bd_topo_extractor.core.exceptions import ApiRequestError, AuthenticationError
from bd_topo_extractor.core.extraction_api_client import ExtractionApiClient
from bd_topo_extractor.core.oauth2_configuration import build_default_config
from bd_topo_extractor.toolbelt import PlgLogger, PlgOptionsManager


def _is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket(AF_INET, SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except socket_error:
            return False


def _first_available_port() -> int:
    for port in OAUTH_DECLARED_REDIRECT_PORTS:
        if _is_port_available(port):
            return port
    # Aucun port libre parmi ceux déclarés : on tente quand même le premier,
    # QGIS remontera une erreur explicite si la connexion échoue.
    return OAUTH_DECLARED_REDIRECT_PORTS[0]


class AuthenticationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Connexion à la Géoplateforme"))
        self.setMinimumWidth(480)

        self.log = PlgLogger().log
        self.plg_settings_mngr = PlgOptionsManager()

        layout = QVBoxLayout(self)

        explanation = QLabel(
            self.tr(
                "Connectez-vous à cartes.gouv.fr pour extraire la BD TOPO® et les "
                "autres produits de la Géoplateforme auxquels votre compte donne accès."
            )
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.btn_log_in = QPushButton(
            self.tr("Se connecter avec mon compte cartes.gouv.fr")
        )
        self.btn_log_in.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_log_in.clicked.connect(self._connect_new)
        layout.addWidget(self.btn_log_in)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        reuse_label = QLabel(
            self.tr(
                "Ou réutiliser une configuration d'authentification existante "
                "(par exemple celle du plugin Géoplateforme, si installé) :"
            )
        )
        reuse_label.setWordWrap(True)
        layout.addWidget(reuse_label)

        reuse_layout = QHBoxLayout()
        self.auth_select = QgsAuthConfigSelect(self)
        reuse_layout.addWidget(self.auth_select, stretch=1)
        self.btn_use_existing = QPushButton(self.tr("Utiliser cette configuration"))
        self.btn_use_existing.clicked.connect(self._use_existing)
        reuse_layout.addWidget(self.btn_use_existing)
        layout.addLayout(reuse_layout)

        layout.addStretch(1)

        self.msg_bar = QgsMessageBar(self)
        layout.addWidget(self.msg_bar)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Connexion via un nouveau login
    # ------------------------------------------------------------------
    def _connect_new(self) -> None:
        auth_manager = QgsApplication.authManager()

        oauth_config = build_default_config(redirect_port=_first_available_port())

        new_auth_config = QgsAuthMethodConfig(method="OAuth2", version=1)
        new_auth_config.setId(auth_manager.uniqueConfigId())
        new_auth_config.setName(oauth_config.name)
        new_auth_config.setConfigMap({"oauth2config": oauth_config.as_qgis_str_config_map()})

        if not new_auth_config.isValid():
            self.msg_bar.pushMessage(
                self.tr(
                    "Impossible de créer la configuration d'authentification "
                    "(configuration invalide)."
                ),
                level=Qgis.MessageLevel.Critical,
            )
            return

        stored, _ = auth_manager.storeAuthenticationConfig(new_auth_config, True)
        if not stored:
            self.msg_bar.pushMessage(
                self.tr(
                    "Impossible d'enregistrer la configuration d'authentification "
                    "dans le gestionnaire d'authentification de QGIS."
                ),
                level=Qgis.MessageLevel.Critical,
            )
            return

        self.log(
            message=f"Configuration d'authentification créée : {new_auth_config.id()}",
            log_level=Qgis.MessageLevel.NoLevel,
        )

        if self._check_connection(new_auth_config.id()):
            self._adopt(new_auth_config.id())
        else:
            auth_manager.removeAuthenticationConfig(new_auth_config.id())

    # ------------------------------------------------------------------
    # Réutilisation d'une configuration existante
    # ------------------------------------------------------------------
    def _use_existing(self) -> None:
        config_id = self.auth_select.configId().strip()
        if not config_id:
            self.msg_bar.pushMessage(
                self.tr("Veuillez sélectionner une configuration d'authentification."),
                level=Qgis.MessageLevel.Warning,
            )
            return

        if self._check_connection(config_id):
            self._adopt(config_id)

    # ------------------------------------------------------------------
    # Commun
    # ------------------------------------------------------------------
    def _check_connection(self, config_id: str) -> bool:
        """Vérifie qu'une configuration d'authentification permet réellement
        d'accéder à l'API d'extraction (liste des processus)."""
        plg_settings = self.plg_settings_mngr.get_plg_settings()
        try:
            client = ExtractionApiClient(authcfg=config_id, api_base=plg_settings.api_base)
            client.list_processes(page=1, limit=1)
        except (ApiRequestError, AuthenticationError, ConnectionError) as exc:
            self.msg_bar.pushMessage(
                self.tr("Échec de la connexion : {}").format(exc),
                level=Qgis.MessageLevel.Critical,
                duration=10,
            )
            return False

        self.msg_bar.pushMessage(
            self.tr("Connexion réussie."),
            level=Qgis.MessageLevel.Success,
            duration=5,
        )
        return True

    def _adopt(self, config_id: str) -> None:
        plg_settings = self.plg_settings_mngr.get_plg_settings()
        previous_id = plg_settings.qgis_auth_id
        plg_settings.qgis_auth_id = config_id
        self.plg_settings_mngr.save_from_object(plg_settings)

        if previous_id and previous_id != config_id:
            # On ne supprime pas une éventuelle configuration réutilisée
            # (elle peut appartenir à un autre plugin) : on l'oublie seulement.
            self.log(
                message=f"Configuration d'authentification précédente ({previous_id}) "
                "oubliée au profit de la nouvelle.",
                log_level=Qgis.MessageLevel.NoLevel,
            )

        self.accept()
