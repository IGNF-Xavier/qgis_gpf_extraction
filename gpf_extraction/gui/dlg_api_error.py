#! python3  # noqa: E265

"""Boîte de dialogue d'erreur d'API : message lisible, plus la requête envoyée
et la réponse reçue dans des zones de texte sélectionnables, avec un bouton de
copie — pour pouvoir rejouer ou signaler l'erreur telle quelle (ex. dans un
signalement à l'équipe du service).

Le jeton d'authentification n'est jamais affiché : il est ajouté par QGIS au
moment de l'envoi, il n'apparaît donc pas dans ce que le plugin connaît de la
requête.
"""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QFontDatabase
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _pretty_json(value) -> str:
    """Met en forme un JSON (objet, `bytes` ou `str`) ; renvoie le texte brut
    tel quel s'il n'est pas du JSON."""
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


class ApiErrorDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        method: str = "",
        url: str = "",
        request_body=None,
        status_code: int | None = None,
        response_body=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)

        self._report = self._build_report(method, url, request_body, status_code, response_body)

        layout = QVBoxLayout(self)

        lbl_message = QLabel(message)
        lbl_message.setWordWrap(True)
        lbl_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(lbl_message)

        if self._report:
            mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            txt = QPlainTextEdit()
            txt.setReadOnly(True)
            txt.setFont(mono)
            txt.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            txt.setPlainText(self._report)
            layout.addWidget(txt, stretch=1)

            btn_copy = QPushButton(self.tr("Copier la requête et la réponse"))
            btn_copy.clicked.connect(self._copy)
            layout.addWidget(btn_copy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    @staticmethod
    def _build_report(method, url, request_body, status_code, response_body) -> str:
        parts: list[str] = []
        if method or url:
            parts.append(f"### Requête\n{method} {url}".rstrip())
            if request_body is not None:
                parts.append(_pretty_json(request_body))
        if status_code is not None or response_body:
            parts.append(f"\n### Réponse\nHTTP {status_code}" if status_code is not None else "\n### Réponse")
            if response_body:
                parts.append(_pretty_json(response_body))
        return "\n".join(parts)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._report)
