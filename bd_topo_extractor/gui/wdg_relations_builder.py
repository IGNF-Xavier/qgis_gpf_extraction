#! python3  # noqa: E265

"""Sélecteur de tables pour l'input `relations` des processus d'extraction
"ARCHIVE depuis VECTOR-DB" (BD TOPO, GPU_EXTRACTION, ...).

Constaté en conditions réelles sur le service : ce type de processus
n'accepte pas une simple bbox globale. L'emprise doit être injectée sous
forme de clause SQL (`ST_Intersects(...)`) dans le filtre de *chaque* table
sélectionnée, à l'intérieur du champ `relations` :

    {"nom_table": {"attributes": ["col1", "col2", ...], "filters": "..."}}

Ce widget liste les tables disponibles (récupérées via `core/stored_data.py`)
avec une case à cocher par table (toutes les colonnes de chaque table
cochée sont incluses), et génère automatiquement le filtre spatial à partir
de l'emprise choisie par l'utilisateur.
"""

from __future__ import annotations

from typing import Optional

from qgis.core import QgsRectangle
from qgis.PyQt.QtCore import QCoreApplication, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bd_topo_extractor.core.models import StoredDataTable


class RelationsBuilderWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tables: list[StoredDataTable] = []
        self._extent: Optional[QgsRectangle] = None
        self._extent_srid: int = 4326

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText(self.tr("Filtrer les tables..."))
        self.txt_filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.txt_filter)

        buttons_layout = QHBoxLayout()
        self.btn_select_all = QPushButton(self.tr("Tout cocher"))
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        buttons_layout.addWidget(self.btn_select_all)
        self.btn_select_none = QPushButton(self.tr("Tout décocher"))
        self.btn_select_none.clicked.connect(lambda: self._set_all_checked(False))
        buttons_layout.addWidget(self.btn_select_none)
        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

        self.list_tables = QListWidget()
        self.list_tables.setMaximumHeight(160)
        self.list_tables.itemChanged.connect(self._update_status_label)
        layout.addWidget(self.list_tables)

        self.lbl_status = QLabel()
        layout.addWidget(self.lbl_status)

        self._update_status_label()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate(self.__class__.__name__, message)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_tables(self, tables: list[StoredDataTable]) -> None:
        self._tables = tables
        self.list_tables.blockSignals(True)
        self.list_tables.clear()
        for table in sorted(tables, key=lambda t: t.name):
            item = QListWidgetItem(table.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, table)
            nb_attrs = len(table.attributes)
            item.setToolTip(
                self.tr("{} colonne(s){}").format(
                    nb_attrs,
                    "" if table.geometry_attribute else self.tr(" — sans géométrie"),
                )
            )
            self.list_tables.addItem(item)
        self.list_tables.blockSignals(False)
        self._update_status_label()

    def set_extent(self, rectangle: Optional[QgsRectangle], srid: int = 4326) -> None:
        self._extent = rectangle
        self._extent_srid = srid

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------
    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self.list_tables.count()):
            item = self.list_tables.item(row)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.list_tables.blockSignals(True)
        for row in range(self.list_tables.count()):
            item = self.list_tables.item(row)
            if not item.isHidden():
                item.setCheckState(state)
        self.list_tables.blockSignals(False)
        self._update_status_label()

    def _update_status_label(self, *_args) -> None:
        selected = len(self._checked_items())
        self.lbl_status.setText(
            self.tr("{}/{} table(s) sélectionnée(s)").format(selected, len(self._tables))
        )
        self.changed.emit()

    def _checked_items(self) -> list[QListWidgetItem]:
        return [
            self.list_tables.item(row)
            for row in range(self.list_tables.count())
            if self.list_tables.item(row).checkState() == Qt.CheckState.Checked
        ]

    # ------------------------------------------------------------------
    # Valeur
    # ------------------------------------------------------------------
    def get_value(self) -> dict:
        """Construit la valeur de l'input `relations` pour les tables cochées."""
        result: dict = {}
        for item in self._checked_items():
            table: StoredDataTable = item.data(Qt.ItemDataRole.UserRole)
            entry: dict = {"attributes": list(table.attributes.keys())}
            geom_attr = table.geometry_attribute
            if geom_attr and self._extent is not None:
                entry["filters"] = (
                    "ST_Intersects({geom}, ST_MakeEnvelope("
                    "{xmin}, {ymin}, {xmax}, {ymax}, {srid}))"
                ).format(
                    geom=geom_attr,
                    xmin=self._extent.xMinimum(),
                    ymin=self._extent.yMinimum(),
                    xmax=self._extent.xMaximum(),
                    ymax=self._extent.yMaximum(),
                    srid=self._extent_srid,
                )
            result[table.name] = entry
        return result

    def has_selection(self) -> bool:
        return len(self._checked_items()) > 0
