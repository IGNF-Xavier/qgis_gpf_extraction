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

from gpf_extraction.core.extent_fit import (
    DEFAULT_BUDGET_BYTES,
    FIT_AUTO,
    MIN_FILTER_BYTES,
    TWKB_WRAPPER_BYTES,
    ExtentFit,
    fit_extent,
    to_polygons,
    twkb_precision,
)
from gpf_extraction.core.job_batch import plan_batches, split_evenly
from gpf_extraction.core.predicates import effective_predicates
from gpf_extraction.core.twkb import to_hex
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
        #: Contour réellement envoyé (précis, simplifié, rectangles, bbox) : voir
        #: `core/extent_fit.py`. Le calcul est coûteux sur un contour de plusieurs
        #: centaines de milliers de sommets : mémoïsé tant que la géométrie ne change pas.
        self._fit_mode: str = FIT_AUTO
        self._fit_cache: dict = {}
        self._fit_geom_cache: dict = {}  # simplifications/encodages réutilisés d'un budget à l'autre
        self._fit_fingerprint: Optional[int] = None
        #: Si renseigné, `get_value` ne renvoie que ces tables (un lot d'une extraction découpée).
        self._table_subset: Optional[set] = None

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
        # L'appelant repousse l'emprise (reprojetée, donc nouvel objet) à chaque validation :
        # on ne vide le cache que si le contenu a réellement changé.
        fingerprint = (
            hash((srid, bytes(geometry.asWkb()))) if geometry is not None and not geometry.isNull() else None
        )
        if fingerprint != self._fit_fingerprint:
            self._fit_fingerprint = fingerprint
            self._fit_cache.clear()
            self._fit_geom_cache.clear()

    def set_fit_mode(self, mode: str) -> None:
        """Choisit le contour envoyé : `auto`, `precise`, `envelopes` ou `bbox`."""
        self._fit_mode = mode

    def set_table_subset(self, names: Optional[list]) -> None:
        """Restreint `get_value` à ces tables (lot d'une extraction découpée) ; None = toutes les cochées."""
        self._table_subset = set(names) if names is not None else None

    def _selected_tables(self) -> list:
        tables = [item.data(Qt.ItemDataRole.UserRole) for item in self._checked_items()]
        if self._table_subset is not None:
            tables = [t for t in tables if t.name in self._table_subset]
        return tables

    def _filter_budget_bytes(self, tables: int, other_bytes: int) -> int:
        """Budget d'un filtre (octets) : ce qui reste du budget de la requête une fois comptés les
        noms et colonnes des tables, réparti sur les copies du contour (tables × prédicats effectifs)."""
        copies = max(1, tables) * len(effective_predicates(self._predicates))
        return max(MIN_FILTER_BYTES, (DEFAULT_BUDGET_BYTES - other_bytes) // copies)

    def _other_bytes(self, tables: list, count: Optional[int] = None) -> int:
        """Poids de la requête hors filtres : tables et colonnes, plus les entrées fixes. Pour un lot
        de `count` tables, on prorate le poids de toute la sélection."""
        total = sum(len(t.name) + sum(len(a) + 4 for a in t.attributes) + 40 for t in tables) + 300
        if count is not None and tables:
            return int(total * count / len(tables))
        return total

    def current_fit(self, tables_in_request: Optional[int] = None) -> Optional[ExtentFit]:
        """Contour retenu pour le filtre de chaque table, ou None sans contour (BBox dessinée).

        Le contour est recopié dans le filtre de chaque table et de chaque prédicat (après réduction
        logique) : son budget dépend du nombre de tables de la requête. Il est choisi d'après la
        taille **encodée** du filtre, pas d'après un nombre de sommets estimé.

        :param tables_in_request: nombre de tables à compter (pour tester un lot) ; par défaut, les
            tables retenues par la sélection ou le lot courant.
        """
        geometry = self._extent_geometry
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            return None
        selected = [t for t in self._selected_tables() if t.geometry_attribute]
        all_checked = [item.data(Qt.ItemDataRole.UserRole) for item in self._checked_items()]
        n_tables = max(1, tables_in_request if tables_in_request is not None else len(selected))
        other = self._other_bytes(all_checked, n_tables) if tables_in_request is not None else self._other_bytes(selected)
        max_bytes = self._filter_budget_bytes(n_tables, other)
        key = (self._fit_mode, max_bytes)
        if key not in self._fit_cache:
            srid = self._extent_srid
            self._fit_cache[key] = fit_extent(
                geometry,
                srid,
                self._fit_mode,
                max_bytes=max_bytes,
                size_of=lambda geom, kind: len(to_hex(to_polygons(geom), twkb_precision(srid, kind))) + TWKB_WRAPPER_BYTES,
                cache=self._fit_geom_cache,
            )
        return self._fit_cache[key]

    def suggest_batches(self) -> list:
        """Découpage proposé de la sélection en lots de tables (liste de listes de noms), ou `[]`.

        Une seule requête sur toutes les tables dégrade-t-elle le contour (simplification forte,
        rectangles, bbox) alors que quelques lots successifs le garderaient fidèle ? Voir `core/job_batch.py`."""
        selected = [t for t in self._selected_tables() if t.geometry_attribute]
        if self._extent_geometry is None or len(selected) < 2:
            return []
        batches = plan_batches(len(selected), self.current_fit)
        if batches < 2:
            return []
        return [[t.name for t in chunk] for chunk in split_evenly(selected, batches)]

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
        """Expression SQL de l'emprise : pour une vraie géométrie (contour administratif ou
        couche du projet), un TWKB hexadécimal (`ST_GeomFromTWKB`), ~4 à 5 fois plus léger que
        le WKT recopié dans le filtre de chaque table ; `ST_MakeEnvelope(...)` en repli pour une
        simple BBox rectangulaire. Le TWKB ne porte pas de SRID : `ST_SetSRID`."""
        fit = self.current_fit()
        if fit is not None and fit.geometry is not None:
            precision = twkb_precision(self._extent_srid, fit.kind)
            twkb = to_hex(to_polygons(fit.geometry), precision)
            return f"ST_SetSRID(ST_GeomFromTWKB(decode('{twkb}','hex')), {self._extent_srid})"
        if self._extent is not None:  # BBox dessinée, ou contour remplacé par un rectangle unique
            return (
                f"ST_MakeEnvelope({self._extent.xMinimum()}, {self._extent.yMinimum()}, "
                f"{self._extent.xMaximum()}, {self._extent.yMaximum()}, {self._extent_srid})"
            )
        return None

    def get_value(self) -> dict:
        """Construit la valeur de l'input `relations` pour les tables cochées."""
        expr = self._extent_sql_expression()
        # `Intersects OR Contains` = `Intersects` : on n'envoie (et ne recopie) que ce qui change le résultat.
        predicates = effective_predicates(self._predicates or DEFAULT_PREDICATES)

        result: dict = {}
        for table in self._selected_tables():
            entry: dict = {"attributes": list(table.attributes.keys())}
            geom_attr = table.geometry_attribute
            if geom_attr and expr is not None:
                clauses = [f"{PREDICATE_SQL[p]}({geom_attr}, {expr})" for p in predicates]
                entry["filters"] = clauses[0] if len(clauses) == 1 else f"({' OR '.join(clauses)})"
            result[table.name] = entry
        return result

    def has_selection(self) -> bool:
        return len(self._checked_items()) > 0
