"""Modèles de données pour l'API d'extraction (OGC API - Processes).

Le schéma exact des entrées d'un processus (`inputs`) n'est pas typé dans
l'OpenAPI du service (cf. `docs/extraction_openapi_notes.md`) : selon le
processus, `GET /processes/{id}` peut renvoyer `inputs` comme un
dictionnaire (forme standard OGC API - Processes : `{id: schema}`) ou comme
une liste d'objets. Le parsing ci-dessous reste volontairement défensif et
conserve toujours le JSON brut (`raw`) pour que l'UI puisse s'y raccrocher
si le mapping "propre" échoue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ProcessInputField:
    """Un champ d'entrée normalisé d'un processus, au mieux de ce qui a pu
    être extrait du JSON brut."""

    id: str
    title: str = ""
    description: str = ""
    schema: dict = field(default_factory=dict)
    required: bool = False
    raw: Any = None

    @property
    def type(self) -> str:
        """Type JSON Schema déclaré ("string", "number", "boolean",
        "array", "object", ...), vide si non déterminable."""
        return self.schema.get("type", "") if isinstance(self.schema, dict) else ""

    @property
    def enum(self) -> Optional[list]:
        if isinstance(self.schema, dict):
            return self.schema.get("enum")
        return None

    @property
    def default(self) -> Any:
        if isinstance(self.schema, dict):
            return self.schema.get("default")
        return None


@dataclass
class ProcessSummary:
    id: str
    title: str = ""
    description: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "ProcessSummary":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title") or data.get("id", "")),
            description=str(data.get("description", "")),
            raw=data,
        )


#: Identifiants d'outputs observés en pratique sur ce service (constaté par
#: retour d'erreur de l'API : le champ `outputs` du corps d'exécution est
#: obligatoire). Utilisé comme repli si `GET /processes/{id}` ne permet pas
#: d'en extraire la liste exacte pour un processus donné.
DEFAULT_OUTPUT_IDS = ("logs", "summary", "extractedData")


@dataclass
class ProcessDetails:
    id: str
    title: str = ""
    description: str = ""
    version: str = ""
    inputs: list = field(default_factory=list)
    output_ids: list = field(default_factory=list)
    described_by_url: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "ProcessDetails":
        output_ids = _normalize_output_ids(data.get("outputs"))
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title") or data.get("id", "")),
            description=str(data.get("description", "")),
            version=str(data.get("version", "")),
            inputs=_normalize_inputs(data.get("inputs")),
            output_ids=output_ids or list(DEFAULT_OUTPUT_IDS),
            described_by_url=_find_described_by_url(data.get("links")),
            raw=data,
        )


#: Certains `title` observés côté API sont des libellés humains, pas
#: l'identifiant réel attendu dans le corps de requête `inputs` — confirmé
#: par la documentation officielle du service d'extraction
#: (https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/),
#: dont l'exemple de corps de requête utilise la clé `lifetime` là où le
#: processus déclare le titre "Durée de rétention".
_TITLE_TO_INPUT_ID = {
    "durée de rétention": "lifetime",
}


def _normalize_inputs(raw_inputs: Any) -> list[ProcessInputField]:
    """Normalise `inputs`, qu'il soit un dict `{id: schema}` (forme standard
    OGC API - Processes) ou une liste d'objets (forme observée dans
    l'OpenAPI de ce service, qui semble refléter une sérialisation
    polymorphe imparfaite)."""
    fields: list[ProcessInputField] = []

    if isinstance(raw_inputs, dict):
        for input_id, schema in raw_inputs.items():
            if not isinstance(schema, dict):
                schema = {}
            fields.append(
                ProcessInputField(
                    id=str(input_id),
                    title=str(schema.get("title") or input_id),
                    description=str(schema.get("description", "")),
                    schema=schema.get("schema", schema),
                    required=schema.get("minOccurs", 1) not in (0, None),
                    raw=schema,
                )
            )
    elif isinstance(raw_inputs, list):
        for item in raw_inputs:
            if not isinstance(item, dict):
                continue
            # Forme observée dans l'OpenAPI du service : {"input": {...}}
            if "input" in item and isinstance(item["input"], dict) and len(item) == 1:
                item = item["input"]
            # Constaté en conditions réelles sur ce service : les entrées de
            # `inputs` n'ont pas de champ `id`/`name` distinct, seulement un
            # `title` qui fait office d'identifiant (ex. "compression",
            # "relations", "format"...) — utilisé tel quel comme clé du corps
            # de requête `inputs`.
            input_id = str(item.get("id") or item.get("name") or item.get("title") or "")
            input_id = _TITLE_TO_INPUT_ID.get(input_id.lower(), input_id)
            if not input_id:
                # Dernier recours : un dict à une seule clé, ex. {"bbox": {...}}
                if len(item) == 1:
                    input_id, item = next(iter(item.items()))
                    if not isinstance(item, dict):
                        item = {}
                else:
                    continue
            fields.append(
                ProcessInputField(
                    id=input_id,
                    title=str(item.get("title") or input_id),
                    description=str(item.get("description", "")),
                    schema=item.get("schema", item),
                    required=str(item.get("minOccurs", 1)) not in ("0",),
                    raw=item,
                )
            )

    return fields


def _find_described_by_url(raw_links: Any) -> Optional[str]:
    """Cherche, dans les `links` d'un processus, l'URL "describedby" pointant
    vers la description de la donnée stockée sous-jacente (liste des tables
    et attributs disponibles pour l'input `relations`)."""
    if not isinstance(raw_links, list):
        return None
    for link in raw_links:
        if isinstance(link, dict) and link.get("rel") == "describedby":
            href = link.get("href")
            if href:
                return str(href)
    return None


def _normalize_output_ids(raw_outputs: Any) -> list[str]:
    """Extrait la liste des identifiants d'outputs déclarés par un processus.

    Comme pour `inputs`, la forme exacte n'est pas garantie par l'OpenAPI du
    service (`ProcessOutputDto` déclare des propriétés génériques). En
    pratique, `outputs` est un dict `{id: schema}` (forme standard OGC API -
    Processes) ; on se contente d'en récupérer les clés.
    """
    if isinstance(raw_outputs, dict):
        return [str(k) for k in raw_outputs.keys()]
    if isinstance(raw_outputs, list):
        ids = []
        for item in raw_outputs:
            if isinstance(item, dict):
                output_id = item.get("id") or item.get("name")
                if output_id:
                    ids.append(str(output_id))
        return ids
    return []


@dataclass
class StoredDataTable:
    """Une table exploitable d'une donnée stockée de type VECTOR-DB (obtenue
    via le lien `describedby` d'un processus), telle qu'attendue par l'input
    `relations` des processus d'extraction "ARCHIVE depuis VECTOR-DB"."""

    name: str
    attributes: dict = field(default_factory=dict)  # {nom_colonne: type_pg}
    primary_key: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def geometry_attribute(self) -> Optional[str]:
        """Nom de la colonne géométrique de la table, si elle en a une."""
        for attr_name, attr_type in self.attributes.items():
            if isinstance(attr_type, str) and attr_type.startswith("geometry"):
                return attr_name
        return None

    @classmethod
    def from_json(cls, data: dict) -> "StoredDataTable":
        return cls(
            name=str(data.get("name", "")),
            attributes=data.get("attributes") or {},
            primary_key=data.get("primary_key") or [],
            raw=data,
        )


@dataclass
class StoredDataDescription:
    """Description d'une donnée stockée (jeu de données source d'un
    processus d'extraction), avec la liste de ses tables exploitables."""

    id: str
    name: str = ""
    type: str = ""
    srs: str = ""
    tables: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "StoredDataDescription":
        type_infos = data.get("type_infos") or {}
        raw_relations = type_infos.get("relations") or []
        # Inclut aussi bien les TABLE que les VIEW (constaté sur des données
        # stockées réelles) : toutes deux sont des relations exploitables
        # par l'input `relations` d'un processus d'extraction.
        tables = [
            StoredDataTable.from_json(item)
            for item in raw_relations
            if isinstance(item, dict) and item.get("name")
        ]
        return cls(
            id=str(data.get("_id", "")),
            name=str(data.get("name", "")),
            type=str(data.get("type", "")),
            srs=str(data.get("srs", "")),
            tables=tables,
            raw=data,
        )


@dataclass
class JobStatus:
    job_id: str
    status: str
    message: str = ""
    created: Optional[str] = None
    started: Optional[str] = None
    finished: Optional[str] = None
    process_id: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "JobStatus":
        return cls(
            job_id=str(data.get("jobID", "")),
            status=str(data.get("status", "")),
            message=str(data.get("message", "")),
            created=data.get("created"),
            started=data.get("started"),
            finished=data.get("finished"),
            process_id=str(data.get("processID", "")),
            raw=data,
        )

    @property
    def is_running(self) -> bool:
        return self.status.upper() in ("RUNNING", "ACCEPTED", "WAITING", "PROGRESS")

    @property
    def is_successful(self) -> bool:
        return self.status.upper() == "SUCCESSFUL"

    @property
    def is_failed(self) -> bool:
        return self.status.upper() in ("FAILED", "DISMISSED")


@dataclass
class JobResult:
    logs: str = ""
    summary_href: Optional[str] = None
    extract_data_href: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "JobResult":
        summary = data.get("summary") or {}
        extract = data.get("extractData") or {}
        return cls(
            logs=str(data.get("logs", "")),
            summary_href=summary.get("href") if isinstance(summary, dict) else None,
            extract_data_href=extract.get("href") if isinstance(extract, dict) else None,
            raw=data,
        )


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
