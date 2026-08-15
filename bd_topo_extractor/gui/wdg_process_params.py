#! python3  # noqa: E265

"""Formulaire de paramètres généré dynamiquement pour un processus d'extraction.

Le schéma exact des entrées (`inputs`) d'un processus n'étant pas figé dans
l'OpenAPI du service (cf. `core/models.py`), ce widget construit au mieux un
formulaire simple à partir de ce que renvoie `GET /processes/{id}`, et fournit
systématiquement un éditeur JSON brut en secours pour les cas non couverts —
ou pour corriger le corps de requête si l'hypothèse par défaut (forme
standard OGC API - Processes : `{"inputs": {id: valeur, ...}}`) ne
correspond pas exactement à ce qu'attend le service.
"""

from __future__ import annotations

import json
from typing import Optional

from qgis.core import QgsRectangle
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from bd_topo_extractor.core.models import ProcessDetails, ProcessInputField

#: Fragments de nom de champ évoquant une emprise géographique, utilisés pour
#: pré-remplir automatiquement la valeur avec l'emprise choisie par l'utilisateur.
_EXTENT_FIELD_HINTS = ("bbox", "emprise", "extent", "envelope", "footprint", "zone")


class ProcessParamsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[ProcessDetails] = None
        self._field_widgets: dict[str, QWidget] = {}
        self._extent_bbox: Optional[list[float]] = None
        self._extent_crs: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_description = QLabel()
        self.lbl_description.setWordWrap(True)
        layout.addWidget(self.lbl_description)

        self.simple_form = QFormLayout()
        layout.addLayout(self.simple_form)

        self.chk_advanced = QCheckBox(
            self.tr("Édition avancée du corps de requête (JSON)")
        )
        self.chk_advanced.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.chk_advanced)

        self.txt_advanced = QPlainTextEdit()
        self.txt_advanced.setVisible(False)
        self.txt_advanced.setMinimumHeight(140)
        layout.addWidget(self.txt_advanced)

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_process(self, process: Optional[ProcessDetails]) -> None:
        """Reconstruit le formulaire pour le processus donné."""
        self._process = process
        self._field_widgets = {}
        self.chk_advanced.setChecked(False)

        while self.simple_form.rowCount():
            self.simple_form.removeRow(0)

        if process is None:
            self.lbl_description.setText("")
            self.txt_advanced.setPlainText("")
            return

        self.lbl_description.setText(process.description)

        if not process.inputs:
            note = QLabel(
                self.tr(
                    "Ce processus ne déclare aucune entrée exploitable "
                    "automatiquement : utilisez l'édition avancée ci-dessous."
                )
            )
            note.setWordWrap(True)
            self.simple_form.addRow(note)
            self.chk_advanced.setChecked(True)

        for field in process.inputs:
            widget = self._build_field_widget(field)
            if widget is None:
                continue
            self._field_widgets[field.id] = widget
            label = field.title or field.id
            if field.required:
                label += " *"
            self.simple_form.addRow(label, widget)

        self._refresh_advanced_preview()

    def set_extent(self, rectangle: QgsRectangle, crs: str) -> None:
        """Mémorise l'emprise choisie par l'utilisateur, pour pré-remplissage
        automatique des champs qui y ressemblent (bbox, emprise, ...)."""
        if rectangle is None:
            self._extent_bbox = None
            self._extent_crs = ""
        else:
            self._extent_bbox = [
                rectangle.xMinimum(),
                rectangle.yMinimum(),
                rectangle.xMaximum(),
                rectangle.yMaximum(),
            ]
            self._extent_crs = crs
        self._refresh_advanced_preview()

    # ------------------------------------------------------------------
    # Construction des widgets
    # ------------------------------------------------------------------
    def _build_field_widget(self, field: ProcessInputField) -> Optional[QWidget]:
        if field.enum:
            combo = QComboBox()
            for value in field.enum:
                combo.addItem(str(value), value)
            if field.default is not None:
                idx = combo.findData(field.default)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(self._refresh_advanced_preview)
            return combo

        field_type = field.type
        if field_type == "boolean":
            check = QCheckBox()
            check.setChecked(bool(field.default))
            check.toggled.connect(self._refresh_advanced_preview)
            return check

        if field_type in ("integer", "number"):
            spin = QDoubleSpinBox()
            spin.setDecimals(0 if field_type == "integer" else 6)
            spin.setRange(-1_000_000_000, 1_000_000_000)
            if isinstance(field.default, (int, float)):
                spin.setValue(field.default)
            spin.valueChanged.connect(self._refresh_advanced_preview)
            return spin

        if field_type in ("", "string"):
            line = QLineEdit()
            if isinstance(field.default, str):
                line.setText(field.default)
            elif self._looks_like_extent_field(field.id):
                line.setPlaceholderText(self.tr("Rempli automatiquement avec l'emprise choisie"))
            line.textChanged.connect(self._refresh_advanced_preview)
            return line

        # array / object / type non reconnu : pas de widget simple, l'édition
        # avancée reste le moyen de le renseigner.
        return None

    @staticmethod
    def _looks_like_extent_field(field_id: str) -> bool:
        field_id_lower = field_id.lower()
        return any(hint in field_id_lower for hint in _EXTENT_FIELD_HINTS)

    # ------------------------------------------------------------------
    # Valeurs
    # ------------------------------------------------------------------
    def _simple_values(self) -> dict:
        values: dict = {}
        extent_field_filled = False
        for field_id, widget in self._field_widgets.items():
            if isinstance(widget, QComboBox):
                values[field_id] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[field_id] = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                values[field_id] = widget.value()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                if not text and self._extent_bbox and self._looks_like_extent_field(field_id):
                    values[field_id] = self._extent_bbox
                    extent_field_filled = True
                elif text:
                    values[field_id] = text
                    if self._looks_like_extent_field(field_id):
                        extent_field_filled = True

        # Aucun champ reconnu comme une emprise (schéma du processus non
        # couvert par nos heuristiques) : on ajoute quand même l'emprise
        # choisie sous une clé usuelle, à corriger via l'édition avancée si
        # le processus attend une autre forme.
        if not extent_field_filled and self._extent_bbox:
            values.setdefault("bbox", self._extent_bbox)

        return values

    def _refresh_advanced_preview(self) -> None:
        if self.chk_advanced.isChecked():
            return  # l'utilisateur a la main, on ne l'écrase pas
        body = {"inputs": self._simple_values()}
        self.txt_advanced.setPlainText(json.dumps(body, indent=2, ensure_ascii=False))

    def _toggle_advanced(self, checked: bool) -> None:
        self.txt_advanced.setVisible(True)
        self.txt_advanced.setReadOnly(not checked)
        for widget in self._field_widgets.values():
            widget.setEnabled(not checked)
        if not checked:
            self._refresh_advanced_preview()

    def get_body(self) -> dict:
        """Construit le corps de requête pour `POST /processes/{id}/execution`.

        Par défaut (mode simple), suit la forme standard OGC API - Processes
        `{"inputs": {id: valeur, ...}}`. En mode avancé, le JSON saisi par
        l'utilisateur est utilisé tel quel.

        :raises ValueError: si le JSON en mode avancé est invalide.
        """
        if self.chk_advanced.isChecked() or not self._field_widgets:
            text = self.txt_advanced.toPlainText().strip()
            if not text:
                return {"inputs": {}}
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    self.tr("Le corps de requête JSON est invalide : {}").format(exc)
                ) from exc

        return {"inputs": self._simple_values()}
