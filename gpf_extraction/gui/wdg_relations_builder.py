#! python3  # noqa: E265

"""Sélecteur de tables pour l'input `relations` des processus d'extraction
"ARCHIVE depuis VECTOR-DB" (BD TOPO, GPU_EXTRACTION, ...).

Constaté en conditions réelles sur le service : ce type de processus
n'accepte pas une simple bbox globale. L'emprise doit être injectée sous
forme de clause SQL (`ST_xxx(...)`, un ou plusieurs prédicats combinés en OU)
dans le filtre de *chaque* table sélectionnée, à l'intérieur du champ
`relations` :

    {"nom_table": {"attributes": ["col1", "col2", ...], "filters": "..."}}

Ce widget liste les tables disponibles (récupérées via `core/stored_data.py`)
avec une case à cocher par table (toutes les colonnes de chaque table
cochée sont incluses), et génère automatiquement le filtre spatial à partir
de l'emprise et des prédicats choisis par l'utilisateur.
"""

from __future__ import annotations

from typing import Optional

from qgis.core import QgsGeometry, QgsRectangle
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

from gpf_extraction.core.models import StoredDataTable

#: Correspondance prédicat (libellé UI) -> fonction PostGIS. `filters` est une
#: clause WHERE PostgreSQL/PostGIS libre (documenté par l'API), contrairement à
#: `attributes` qui est restreint aux noms de colonnes réels de la table
#: (vérifié en conditions réelles : une expression comme
#: `ST_Intersection(...) AS geometrie` y est rejetée par le serveur, HTTP 400
#: "L'attribut ... n'existe pas dans la relation ...") — un prédicat de
#: sélection reste donc la seule opération spatiale possible côté serveur, pas
#: un découpage (clip) de la géométrie elle-même.
PREDICATE_SQL = {
    "Intersects": "ST_Intersects",
    "Contains": "ST_Contains",
    "Within": "ST_Within",
    "Disjoint": "ST_Disjoint",
    "Touches": "ST_Touches",
    "Crosses": "ST_Crosses",
    "Overlaps": "ST_Overlaps",
    "Equals": "ST_Equals",
}

DEFAULT_PREDICATES = ["Intersects"]


class RelationsBuilderWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tables: list[StoredDataTable] = []
        self._extent: Optional[QgsRectangle] = None
        self._extent_srid: int = 4326
        #: Géométrie réelle de l'emprise (contour administratif ou couche du
        #: projet), déjà dans le SRID `_extent_srid` — None pour une emprise
        #: purement rectangulaire (BBox dessinée), auquel cas `_extent` sert
        #: directement à construire un `ST_MakeEnvelope`.
        self._extent_geometry: Optional[QgsGeometry] = None
        self._predicates: list[str] = list(DEFAULT_PREDICATES)

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

    def set_extent(
        self,
        rectangle: Optional[QgsRectangle],
        srid: int = 4326,
        geometry: Optional[QgsGeometry] = None,
    ) -> None:
        """Définit l'emprise à utiliser pour le filtre spatial de chaque table.

        :param rectangle: emprise, comme repli (`ST_MakeEnvelope`) quand
            `geometry` n'est pas fournie — cas d'une BBox dessinée à la main.
        :type rectangle: Optional[QgsRectangle]
        :param srid: SRID dans lequel `rectangle`/`geometry` sont exprimés
            (déjà reprojetés par l'appelant — ce widget ne reprojette rien),
            defaults to 4326.
        :type srid: int, optional
        :param geometry: géométrie réelle de l'emprise (contour administratif
            ou couche du projet) : utilisée à la place du rectangle
            (`ST_GeomFromText` plutôt que `ST_MakeEnvelope`) quand fournie,
            defaults to None.
        :type geometry: Optional[QgsGeometry], optional
        """
        self._extent = rectangle
        self._extent_srid = srid
        self._extent_geometry = geometry

    def set_predicates(self, predicates: list[str]) -> None:
        """Définit les prédicats géométriques à combiner (en OU) dans le
        filtre spatial de chaque table. Un repli sur `Intersects` est appliqué
        si la liste est vide (jamais de filtre spatial sans prédicat)."""
        self._predicates = list(predicates) or list(DEFAULT_PREDICATES)

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
    def _extent_sql_expression(self) -> Optional[str]:
        """Expression SQL de l'emprise : `ST_GeomFromText(...)` pour une vraie
        géométrie (contour administratif ou couche du projet), `ST_MakeEnvelope(...)`
        en repli pour une simple BBox rectangulaire."""
        if self._extent_geometry is not None and not self._extent_geometry.isEmpty():
            wkt = self._extent_geometry.asWkt()
            return f"ST_GeomFromText('{wkt}', {self._extent_srid})"
        if self._extent is not None:
            return (
                f"ST_MakeEnvelope({self._extent.xMinimum()}, {self._extent.yMinimum()}, "
                f"{self._extent.xMaximum()}, {self._extent.yMaximum()}, {self._extent_srid})"
            )
        return None

    def get_value(self) -> dict:
        """Construit la valeur de l'input `relations` pour les tables cochées."""
        expr = self._extent_sql_expression()
        predicates = self._predicates or DEFAULT_PREDICATES

        result: dict = {}
        for item in self._checked_items():
            table: StoredDataTable = item.data(Qt.ItemDataRole.UserRole)
            entry: dict = {"attributes": list(table.attributes.keys())}
            geom_attr = table.geometry_attribute
            if geom_attr and expr is not None:
                clauses = [f"{PREDICATE_SQL[p]}({geom_attr}, {expr})" for p in predicates]
                entry["filters"] = clauses[0] if len(clauses) == 1 else f"({' OR '.join(clauses)})"
            result[table.name] = entry
        return result

    def has_selection(self) -> bool:
        return len(self._checked_items()) > 0
