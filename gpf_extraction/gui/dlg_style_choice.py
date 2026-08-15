#! python3  # noqa: E265

"""Choix du style à appliquer, quand plusieurs styles candidats existent
pour une même couche extraite (cf. `core/style_bundle.py`)."""

from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from gpf_extraction.core.style_bundle import StyleCandidate


class StyleChoiceDialog(QDialog):
    """Une ligne par couche ayant plusieurs styles candidats, avec une liste
    déroulante pour choisir lequel appliquer (ou aucun)."""

    def __init__(self, candidates_by_layer: dict[str, list[StyleCandidate]], parent=None):
        """
        :param candidates_by_layer: styles candidats par nom de couche
            (n'inclure que les couches ayant au moins 2 candidats).
        :type candidates_by_layer: dict[str, list[StyleCandidate]]
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Choix des styles"))
        self.setMinimumWidth(480)

        self._combos: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        info = QLabel(
            self.tr(
                "Plusieurs styles ont été trouvés pour certaines couches "
                "extraites. Choisissez celui à appliquer (ou aucun)."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        for layer_name, candidates in candidates_by_layer.items():
            combo = QComboBox()
            combo.addItem(self.tr("(aucun style)"), None)
            for candidate in candidates:
                combo.addItem(candidate.label, candidate)
            self._combos[layer_name] = combo
            form.addRow(layer_name, combo)
        layout.addLayout(form)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    def get_choices(self) -> dict[str, Optional[StyleCandidate]]:
        """
        :return: pour chaque couche, le style choisi (ou None).
        :rtype: dict[str, Optional[StyleCandidate]]
        """
        return {
            layer_name: combo.currentData() for layer_name, combo in self._combos.items()
        }
