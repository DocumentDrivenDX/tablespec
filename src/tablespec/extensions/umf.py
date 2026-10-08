"""TableSpec's compiler binding; shared Python machinery is owned by UMF."""

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, ConfigDict
from umf import Diagnostic, Document, Extension, Registry, validate_document

EXTENSION_ID = "tablespec.pipeline"
EXTENSION_VERSION = "0.1.0"
ARCHIVE_ID = "tablespec.source-archive"
NATIVE_TO_SCALAR = {
    "VARCHAR": "string",
    "CHAR": "string",
    "TEXT": "string",
    "INTEGER": "integer",
    "DECIMAL": "decimal",
    "FLOAT": "float",
    "DATE": "date",
    "DATETIME": "timestamp",
    "TIMESTAMP": "timestamp",
    "BOOLEAN": "boolean",
}
SHARED_COLUMN = ("name", "description", "title", "aliases")


class PipelinePayload(BaseModel):
    """Native refinements and pipeline metadata; never part of UMF core."""

    model_config = ConfigDict(extra="allow", strict=True)
    metadata: dict[str, Any]


def pipeline_registry() -> Registry:
    registry = Registry()

    def semantics(payload, context):
        diagnostics = [
            Diagnostic(
                "TABLESPEC_NATIVE_UNCHECKED",
                context["path"],
                "Document validation does not execute native compiler or pipeline rules",
                "warning",
            )
        ]
        unknown = set(payload) - {"metadata"}
        for key in unknown:
            diagnostics.append(
                Diagnostic(
                    "UNKNOWN_TABLESPEC_PAYLOAD",
                    context["path"] + "/" + key,
                    "Payload qualifier preserved without interpretation",
                    "warning",
                )
            )
        reserved = {"table_name", "columns"} if context["scope"] == "module" else set()
        for key in set(payload["metadata"]) & reserved:
            diagnostics.append(
                Diagnostic(
                    "DUPLICATE_SCHEMA_AUTHORITY",
                    context["path"] + "/metadata/" + key,
                    "Shared schema property must be authored in UMF core",
                )
            )
        return diagnostics

    registry.register(
        Extension(
            EXTENSION_ID,
            EXTENSION_VERSION,
            ("module", "element"),
            json.loads(
                files(__package__)
                .joinpath("pipeline.schema.json")
                .read_text(encoding="utf-8")
            ),
            semantics,
        )
    )
    registry.register(
        Extension(
            ARCHIVE_ID,
            "0.1.0",
            ("document",),
            json.loads(
                files(__package__)
                .joinpath("source-archive.schema.json")
                .read_text(encoding="utf-8")
            ),
            lambda payload, context: [],
        )
    )
    return registry


def from_legacy(data: dict, *, document_id: str | None = None) -> Document:
    """Migrate the raw mapping without normalizing it through Pydantic defaults."""
    data = deepcopy(data)
    name = data.pop("table_name")
    columns = data.pop("columns")
    elements = []
    for index, original in enumerate(columns):
        metadata = dict(original)
        element = {"id": f"column:{index}", "kind": "field", "extensions": {}}
        for key in SHARED_COLUMN:
            # Preserve native null/empty/duplicate aliases in the extension instead
            # of inventing a valid shared declaration from an invalid native shape.
            value = metadata.get(key)
            shared = value is not None
            if key == "aliases":
                shared = (
                    isinstance(value, list)
                    and all(isinstance(v, str) and v for v in value)
                    and len(set(value)) == len(value)
                )
            if shared:
                element[key] = metadata.pop(key)
        native_type = metadata.get("data_type")
        scalar = NATIVE_TO_SCALAR.get(native_type) if isinstance(native_type, str) else None
        if scalar is not None:
            element["scalarType"] = scalar
        element["extensions"][EXTENSION_ID] = {"metadata": metadata}
        elements.append(element)
    return Document.model_validate(
        {
            "umf": "0.8.0",
            "id": document_id or name,
            "vocabularies": {EXTENSION_ID: {"version": EXTENSION_VERSION}},
            "modules": [
                {
                    "id": "table",
                    "namespace": name,
                    "elements": elements,
                    "extensions": {EXTENSION_ID: {"metadata": data}},
                }
            ],
        }
    )


def _metadata(node: dict) -> dict:
    payload = node.get("extensions", {}).get(EXTENSION_ID)
    if payload is None:
        return {}
    if set(payload) != {"metadata"}:
        raise ValueError("Unknown TableSpec payload qualifiers cannot be executed")
    return deepcopy(payload["metadata"])


def to_legacy(document: Document) -> dict:
    """Derive the compiler view; refuse relevant semantics without a binding."""
    document = document.checked_copy()
    validation = validate_document(document, pipeline_registry())
    if not validation.valid:
        raise ValueError(
            "Invalid UMF document: "
            + "; ".join(d.message for d in validation.diagnostics)
        )
    data = document.to_dict()
    if data["umf"] != "0.8.0" or len(data["modules"]) != 1:
        raise ValueError("TableSpec requires core 0.8.0 and exactly one table module")
    if set(data) - {
        "umf",
        "id",
        "vocabularies",
        "modules",
        "extensions",
        "title",
        "aliases",
    }:
        raise ValueError("Unknown document properties cannot be executed")
    module = data["modules"][0]
    if set(module) - {"id", "namespace", "elements", "extensions", "title", "aliases"}:
        raise ValueError("Unsupported module semantics cannot be executed")
    table = _metadata(module)
    table["table_name"] = module["namespace"]
    table.setdefault("version", "1.0")
    columns = []
    for element in module["elements"]:
        if element.get("kind") != "field":
            raise ValueError("TableSpec table binding requires scalar Fields")
        unsupported = set(element) - {
            "id",
            "name",
            "description",
            "title",
            "aliases",
            "kind",
            "scalarType",
            "extensions",
        }
        if unsupported:
            raise ValueError(
                f"Unsupported core properties on {element['id']}: {sorted(unsupported)}"
            )
        column = _metadata(element)
        for key in SHARED_COLUMN:
            if key in element:
                if key in column:
                    raise ValueError(f"Duplicate shared schema authority for {key}")
                column[key] = element[key]
        native_type = column.get("data_type")
        scalar = element.get("scalarType")
        if native_type is None:
            raise ValueError(
                f"Explicit TableSpec data_type binding required on {element['id']}; "
                "a core scalar family does not define native storage or coercion"
            )
        elif NATIVE_TO_SCALAR.get(native_type) != scalar:
            raise ValueError(
                f"Native data_type and shared scalarType disagree on {element['id']}"
            )
        columns.append(column)
    table["columns"] = columns
    return table


def compiler_view(document: Document):
    """Return a native validated view retaining the authoritative shared document."""
    from tablespec.models.umf import UMF, UMFColumn

    data = to_legacy(document)
    for column in data["columns"]:
        unknown = set(column) - set(UMFColumn.model_fields)
        if unknown:
            raise ValueError(
                f"Unknown native column semantics cannot be executed: {sorted(unknown)}"
            )
    view = UMF.model_validate(data)

    def check_ignored(raw, parsed):
        if isinstance(parsed, BaseModel) and isinstance(raw, dict):
            unknown = set(raw) - set(type(parsed).model_fields)
            if unknown and type(parsed).model_config.get("extra") != "allow":
                raise ValueError(
                    f"Unknown native model fields cannot be executed: {sorted(unknown)}"
                )
            for key in raw.keys() & type(parsed).model_fields.keys():
                check_ignored(raw[key], getattr(parsed, key))
        elif isinstance(parsed, list) and isinstance(raw, list):
            for original, item in zip(raw, parsed, strict=True):
                check_ignored(original, item)

    check_ignored(data, view)
    view._shared_document = document.checked_copy()
    view._shared_snapshot = view.model_dump(mode="json", exclude_none=True)
    return view


def document_from_view(view) -> Document:
    if view._shared_document is not None:
        current = view.model_dump(mode="json", exclude_none=True)
        if current != view._shared_snapshot:
            raise ValueError(
                "Derived compiler view was edited; edit its authoritative UMF document and derive a new view"
            )
        return view._shared_document.checked_copy()
    return from_legacy(view.model_dump(mode="json", exclude_none=True))


def _fingerprint(document: Document) -> str:
    data = document.to_dict()
    data.get("extensions", {}).pop(ARCHIVE_ID, None)
    data["vocabularies"].pop(ARCHIVE_ID, None)
    if not data.get("extensions"):
        data.pop("extensions", None)
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def retain_sources(document: Document, files: dict[str, str]) -> Document:
    """Retain exact UTF-8 legacy files for explicit unchanged-source rollback."""
    data = document.to_dict()
    snapshot = _fingerprint(document)
    data["vocabularies"][ARCHIVE_ID] = {"version": "0.1.0"}
    data.setdefault("extensions", {})[ARCHIVE_ID] = {
        "files": files,
        "snapshot": snapshot,
        "filesSha256": _files_hash(files),
    }
    return Document.model_validate(data)


def recover_sources(document: Document) -> dict[str, str]:
    """Recover original file strings; refuse to represent edited meaning as old source."""
    document = document.checked_copy()
    archive = document.to_dict().get("extensions", {}).get(ARCHIVE_ID)
    if archive is None or set(archive) != {"files", "snapshot", "filesSha256"}:
        raise ValueError("No supported retained source archive")
    if document.vocabularies[ARCHIVE_ID].version != "0.1.0":
        raise ValueError("Unsupported source archive version")
    if _fingerprint(document) != archive["snapshot"]:
        raise ValueError(
            "Document changed since migration; original-source rollback would discard edits"
        )
    if _files_hash(archive["files"]) != archive["filesSha256"]:
        raise ValueError("Retained source files changed since migration")
    return deepcopy(archive["files"])


def _files_hash(files: dict[str, str]) -> str:
    text = json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
