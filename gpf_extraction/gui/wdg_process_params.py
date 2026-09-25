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

from qgis.core import QgsGeometry, QgsRectangle
from qgis.PyQt.QtCore import QCoreApplication, Qt, pyqtSignal
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

from gpf_extraction.core.models import ProcessDetails, ProcessInputField, StoredDataDescription
from gpf_extraction.gui.wdg_relations_builder import DEFAULT_PREDICATES, RelationsBuilderWidget

#: Fragments de nom de champ évoquant une emprise géographique, utilisés pour
#: pré-remplir automatiquement la valeur avec l'emprise choisie par l'utilisateur.
_EXTENT_FIELD_HINTS = ("bbox", "emprise", "extent", "envelope", "footprint", "zone")

#: Identifiant d'input observé pour le sélecteur de tables des processus
#: d'extraction "ARCHIVE depuis VECTOR-DB" (BD TOPO, GPU_EXTRACTION, ...) :
#: prend en charge son propre widget dédié (RelationsBuilderWidget) plutôt
#: que le formulaire générique.
_RELATIONS_FIELD_ID = "relations"

#: Valeurs à privilégier, par ordre de préférence, quand un input de type
#: enum (ex. `format`) ne déclare pas de défaut : "GeoPackage" est le format
#: le plus directement exploitable dans QGIS parmi ceux généralement
#: proposés par ce service (GPKG, ESRI SHAPEFILE, GEOJSON, PGDUMP, GML,
#: PARQUET, ...).
_PREFERRED_ENUM_VALUES = ("GPKG", "GeoPackage", "ESRI SHAPEFILE", "GEOJSON")

#: Libellés plus explicites que le nom brut d'un input tel que déclaré par
#: l'API (`field.title`), pour certains champs dont le nom technique ne
#: parle pas de lui-même à l'utilisateur. L'identifiant réellement envoyé
#: au serveur (`field.id`) n'est pas affecté par cette table, seul le
#: libellé affiché dans le formulaire change.
_FIELD_LABEL_OVERRIDES = {
    "append": "Fusionner toutes les tables en un seul fichier",
}

#: Identifiant d'input observé pour la projection de sortie (`"La projection
#: de sortie des données géométrie sous la forme EPSG:xxxx"`) : prend en
#: charge son propre widget (QComboBox éditable) plutôt que le QLineEdit
#: générique, pour proposer le SRS natif de la donnée stockée et quelques
#: projections courantes en plus de la saisie libre.
_SRS_FIELD_ID = "srs"

#: Projections courantes proposées en plus du SRS natif de la donnée stockée
#: (ajouté dynamiquement en tête de liste par `set_stored_data`, s'il est
#: connu et différent de celles-ci). Pas de liste "officielle" des
#: projections disponibles côté service : ce champ reste un texte libre
#: (`EPSG:xxxx`) d'après sa description, cette liste n'est qu'un confort.
_COMMON_SRS = ["EPSG:4326", "EPSG:2154", "EPSG:3857", "EPSG:4171"]

#: Outputs déclarés par le service mais à ne pas demander dans le corps
#: d'exécution. `jobName` (« Nom du job d'extraction »), apparu côté service
#: après la 3.4.0, est refusé quand on le demande vide comme les autres :
#: HTTP 400 « Erreur indéterminée dans le JSON » (constaté en conditions
#: réelles). Le job se crée normalement sans lui.
_OUTPUTS_NOT_REQUESTED = frozenset({"jobName"})

def _srid_from_crs(crs: str) -> int:
    """Extrait le code EPSG numérique d'une chaîne "EPSG:xxxx", avec repli
    sur 4326 (CRS de travail par défaut du plugin, cf. core/constants.py)."""
    if crs and ":" in crs:
        code = crs.rsplit(":", 1)[-1]
        if code.isdigit():
            return int(code)
    return 4326


class ProcessParamsWidget(QWidget):
    #: Émis quand un choix pouvant affecter la validité du formulaire change
    #: (ex. sélection de tables dans le sélecteur `relations`), pour que le
    #: dialogue parent puisse revalider l'activation de son bouton OK.
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[ProcessDetails] = None
        self._field_widgets: dict[str, QWidget] = {}
        self._field_objs: dict[str, ProcessInputField] = {}
        self._extent_bbox: Optional[list[float]] = None
        self._extent_crs: str = ""
        self._extent_rectangle: Optional[QgsRectangle] = None
        self._extent_geometry: Optional[QgsGeometry] = None
        self._predicates: list[str] = list(DEFAULT_PREDICATES)
        self._relations_widget: Optional[RelationsBuilderWidget] = None
        self._pending_stored_data: Optional[StoredDataDescription] = None
        self._srs_widget: Optional[QComboBox] = None

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
        self._field_objs = {}
        self._relations_widget = None
        self._srs_widget = None
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
            self._field_objs[field.id] = field
            if isinstance(widget, RelationsBuilderWidget):
                self._relations_widget = widget
                widget.changed.connect(self._refresh_advanced_preview)
                widget.changed.connect(self.changed)
            elif field.id.lower() == _SRS_FIELD_ID and isinstance(widget, QComboBox):
                self._srs_widget = widget
                # Change de SRS => l'emprise envoyée doit être reprojetée dans
                # cette même projection (cf. dlg_main.py::_validate) : signale
                # au dialogue parent via `changed`, comme pour `relations`.
                widget.currentTextChanged.connect(self.changed)
            label = _FIELD_LABEL_OVERRIDES.get(field.id.lower(), field.title or field.id)
            if field.required:
                label += " *"
            self.simple_form.addRow(label, widget)

        if self._relations_widget is not None:
            if self._pending_stored_data is not None:
                self._relations_widget.set_tables(self._pending_stored_data.tables)
            if self._extent_rectangle is not None:
                self._relations_widget.set_extent(
                    self._extent_rectangle,
                    _srid_from_crs(self._extent_crs),
                    geometry=self._extent_geometry,
                )
            self._relations_widget.set_predicates(self._predicates)

        self._wire_format_append_compatibility()
        self._refresh_advanced_preview()

    def _wire_format_append_compatibility(self) -> None:
        """`append` n'est compatible qu'avec les formats multi-couches
        (GPKG, PGDUMP) — documenté sur le service d'extraction. Désactive
        et décoche automatiquement `append` pour les autres formats, et le
        coche par défaut pour un format multi-couches (pratique quand
        plusieurs tables sont sélectionnées : un seul fichier résultat)."""
        format_widget = self._field_widgets.get("format")
        append_widget = self._field_widgets.get("append")
        if not isinstance(format_widget, QComboBox) or not isinstance(append_widget, QCheckBox):
            return

        def _is_multilayer_format() -> bool:
            value = format_widget.currentData() or format_widget.currentText()
            return str(value).upper() in ("GPKG", "PGDUMP")

        def _sync(*_args) -> None:
            multilayer_ok = _is_multilayer_format()
            append_widget.setEnabled(multilayer_ok)
            if not multilayer_ok:
                append_widget.setChecked(False)
            append_widget.setToolTip(
                ""
                if multilayer_ok
                else self.tr(
                    "Disponible seulement pour les formats multi-couches (GPKG, PGDUMP)."
                )
            )

        format_widget.currentIndexChanged.connect(_sync)
        _sync()
        append_field = self._field_objs.get("append")
        if _is_multilayer_format() and append_field is not None and append_field.default is None:
            append_widget.setChecked(True)

    def set_stored_data(self, description: Optional[StoredDataDescription]) -> None:
        """Fournit la liste des tables exploitables (obtenue via le lien
        `describedby` du processus) au sélecteur de tables, s'il est présent
        dans le formulaire courant (input `relations`). Met aussi à jour le
        combo de projection avec le SRS natif de cette donnée, s'il en a un
        et qu'un champ `srs` est présent dans ce formulaire."""
        self._pending_stored_data = description
        if self._relations_widget is not None:
            self._relations_widget.set_tables(description.tables if description else [])
            self._refresh_advanced_preview()

        if self._srs_widget is not None and description and description.srs:
            native_srs = description.srs.strip()
            idx = self._srs_widget.findText(native_srs)
            if idx < 0:
                self._srs_widget.insertItem(0, native_srs, native_srs)
                idx = 0
            self._srs_widget.setItemText(
                idx, self.tr("{} (natif de la donnée)").format(native_srs)
            )
            self._srs_widget.setCurrentIndex(idx)

    def get_selected_srs(self) -> str:
        """Projection de sortie actuellement choisie dans le formulaire
        (ex. `EPSG:2154`), ou une chaîne vide si ce processus n'a pas de champ
        `srs` (l'appelant doit alors garder le CRS de travail par défaut)."""
        if self._srs_widget is None:
            return ""
        combo = self._srs_widget
        index = combo.currentIndex()
        # Un QComboBox éditable ne réinitialise PAS `currentIndex()` quand le
        # texte saisi ne correspond à aucun item (avec `NoInsert`) : il faut
        # donc vérifier explicitement que le texte affiché correspond encore
        # à l'item indexé avant de faire confiance à `currentData()` — sans
        # quoi une saisie libre renvoyait à tort la dernière valeur choisie
        # dans la liste (constaté en conditions réelles).
        if index >= 0 and combo.itemText(index) == combo.currentText():
            data = combo.itemData(index)
            if data:
                return str(data).strip()
        # Saisie libre, ou pas de correspondance : le libellé du SRS natif
        # porte un suffixe (" (natif de la donnée)") absent d'une saisie
        # libre, mais on le retire quand même par sécurité.
        return combo.currentText().split(" ", 1)[0].strip()

    def set_extent(
        self,
        rectangle: Optional[QgsRectangle],
        crs: str,
        geometry: Optional[QgsGeometry] = None,
    ) -> None:
        """Mémorise l'emprise choisie par l'utilisateur, pour pré-remplissage
        automatique des champs qui y ressemblent (bbox, emprise, ...) et pour
        le sélecteur de tables (filtre spatial par table).

        :param geometry: géométrie réelle de l'emprise (contour administratif
            ou couche du projet), dans le même CRS que `rectangle` — transmise
            telle quelle au sélecteur de tables pour un filtre `ST_GeomFromText`
            plutôt qu'un simple `ST_MakeEnvelope`, quand disponible.
        :type geometry: Optional[QgsGeometry], optional
        """
        self._extent_rectangle = rectangle
        self._extent_geometry = geometry
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

        if self._relations_widget is not None:
            self._relations_widget.set_extent(rectangle, _srid_from_crs(crs), geometry=geometry)

        self._refresh_advanced_preview()

    def set_predicates(self, predicates: list[str]) -> None:
        """Transmet au sélecteur de tables les prédicats géométriques cochés
        par l'utilisateur (combinés en OU dans le filtre de chaque table)."""
        self._predicates = list(predicates) or list(DEFAULT_PREDICATES)
        if self._relations_widget is not None:
            self._relations_widget.set_predicates(self._predicates)
        self._refresh_advanced_preview()

    # ------------------------------------------------------------------
    # Construction des widgets
    # ------------------------------------------------------------------
    def _build_field_widget(self, field: ProcessInputField) -> Optional[QWidget]:
        if field.id.lower() == _RELATIONS_FIELD_ID:
            return RelationsBuilderWidget()

        if field.id.lower() == _SRS_FIELD_ID:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            for value in _COMMON_SRS:
                combo.addItem(value, value)
            # SRS natif de la donnée stockée (si déjà connue à ce stade) : mis
            # en tête et présélectionné par set_stored_data, appelé après
            # set_process dans le flux normal (dlg_main.py::_on_process_selected)
            # — voir set_stored_data pour le cas où il arrive après coup.
            if isinstance(field.default, str) and field.default:
                idx = combo.findText(field.default)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                combo.setCurrentIndex(0)
            return combo

        if field.enum:
            combo = QComboBox()
            if not field.required:
                # Champ optionnel : ne rien présélectionner par défaut. Sans
                # ça, un champ comme "compression" (dont l'unique valeur
                # possible est "7zip") se retrouvait systématiquement
                # envoyé alors que l'utilisateur n'en avait rien demandé,
                # produisant une archive fractionnée (.7z.0001) au lieu du
                # fichier directement exploitable (constaté en conditions
                # réelles).
                combo.addItem(self.tr("(non spécifié)"), None)
            for value in field.enum:
                combo.addItem(str(value), value)
            if field.default is not None:
                idx = combo.findData(field.default)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            elif field.required:
                # Pas de défaut déclaré par le processus : préfère un format
                # directement exploitable dans QGIS (GeoPackage) quand ce
                # choix est proposé, plutôt que le premier de la liste
                # (qui peut être un format de dump non chargeable tel quel,
                # ex. "PGDUMP" observé sur le processus BD TOPO).
                for preferred in _PREFERRED_ENUM_VALUES:
                    idx = combo.findText(preferred, Qt.MatchFlag.MatchFixedString)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                        break
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
            if field.id == "lifetime":
                # Bornes documentées (durée de rétention, en heures) :
                # https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/
                # "Valeur comprise entre 7 et 336 (soit 14 jours)". La borne
                # basse 0 sert de valeur spéciale "non renseigné" : dans ce
                # cas, le champ est omis du corps de requête (cf.
                # _simple_values) et le serveur applique son propre défaut
                # (168h, d'après la description du processus).
                spin.setRange(0, 336)
                spin.setSpecialValueText(self.tr("(168h, défaut serveur)"))
            else:
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
            if isinstance(widget, RelationsBuilderWidget):
                values[field_id] = widget.get_value()
                # L'emprise est déjà injectée table par table (ST_Intersects
                # dans chaque filtre) : pas besoin du repli "bbox" générique.
                if self._extent_rectangle is not None:
                    extent_field_filled = True
            elif field_id.lower() == _SRS_FIELD_ID and isinstance(widget, QComboBox):
                # `currentData()` brut n'est pas fiable ici : ce combo est
                # éditable, et `setCurrentText`/une saisie libre ne réinitialise
                # pas `currentIndex` quand le texte affiché ne correspond pas
                # exactement à l'item resté sélectionné (constaté en conditions
                # réelles : `currentData()` renvoyait encore le SRS natif après
                # avoir choisi un autre SRS de la liste, envoyant la mauvaise
                # projection de sortie au serveur). `get_selected_srs()` gère
                # déjà ce cas correctement.
                srs_value = self.get_selected_srs()
                if srs_value:
                    values[field_id] = srs_value
            elif isinstance(widget, QComboBox):
                data = widget.currentData()
                if data is not None:
                    values[field_id] = data
            elif isinstance(widget, QCheckBox):
                values[field_id] = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                field_obj = self._field_objs.get(field_id)
                is_untouched_optional = (
                    field_obj is not None
                    and not field_obj.required
                    and field_obj.default is None
                    and widget.value() == 0
                )
                if not is_untouched_optional:
                    # Champ optionnel laissé à sa valeur neutre (0) : on
                    # l'omet plutôt que d'écraser le défaut du serveur (ex.
                    # "Durée de rétention" par défaut 168h côté API si omis).
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

    def _outputs_value(self) -> dict:
        """Construit la valeur du champ `outputs`, obligatoire pour ce
        service (constaté par retour d'erreur de l'API : `Le champ outputs
        ne doit pas être null`). Une entrée vide par output déclaré par le
        processus laisse le mode de transmission au choix du serveur."""
        output_ids = self._process.output_ids if self._process else []
        return {
            output_id: {}
            for output_id in output_ids
            if output_id not in _OUTPUTS_NOT_REQUESTED
        }

    def _refresh_advanced_preview(self) -> None:
        if self.chk_advanced.isChecked():
            return  # l'utilisateur a la main, on ne l'écrase pas
        body = {"inputs": self._simple_values(), "outputs": self._outputs_value()}
        self.txt_advanced.setPlainText(json.dumps(body, indent=2, ensure_ascii=False))

    def _toggle_advanced(self, checked: bool) -> None:
        self.txt_advanced.setVisible(True)
        self.txt_advanced.setReadOnly(not checked)
        for widget in self._field_widgets.values():
            widget.setEnabled(not checked)
        if not checked:
            self._refresh_advanced_preview()

    def is_ready(self) -> tuple[bool, str]:
        """Vérifie que le formulaire est en état d'être soumis.

        En mode simple, le sélecteur de tables (`relations`), quand il est
        présent, doit avoir au moins une table cochée : l'API refuse
        explicitement une valeur vide pour cet input (constaté en
        conditions réelles : "Le paramètre en inputs.relations doit
        contenir au moins un élément"). L'édition avancée n'est pas
        vérifiée ici (l'utilisateur a la main sur le JSON).

        :return: (prêt, message d'erreur si non prêt).
        :rtype: tuple[bool, str]
        """
        if self.chk_advanced.isChecked():
            return True, ""
        if self._relations_widget is not None and not self._relations_widget.has_selection():
            return False, self.tr(
                "Sélectionnez au moins une table dans le sélecteur ci-dessus."
            )
        return True, ""

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
                return {"inputs": {}, "outputs": self._outputs_value()}
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    self.tr("Le corps de requête JSON est invalide : {}").format(exc)
                ) from exc

        return {"inputs": self._simple_values(), "outputs": self._outputs_value()}
