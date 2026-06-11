"""Shared ingestion constants and normalizers."""

from __future__ import annotations

#: Canonical provenance metadata columns the ingest pipeline adds to every
#: table. ``tablespec.completeness_validator`` imports this as the required
#: set for ``tablespec validate``; spec-producing flows (e.g. JDBC discovery)
#: append these columns so their emitted UMFs are pipeline-complete. Keys and
#: types mirror the long-standing canonical list (sync_baseline /
#: completeness_validator fallback).
PROVENANCE_COLUMNS: dict[str, dict[str, str]] = {
    "meta_source_name": {
        "name": "meta_source_name",
        "data_type": "VARCHAR",
        "source": "metadata",
        "description": "Source name (e.g. filename or source table) recorded at ingest",
    },
    "meta_source_checksum": {
        "name": "meta_source_checksum",
        "data_type": "VARCHAR",
        "source": "metadata",
        "description": "Checksum of the source artifact (ingest-computed)",
    },
    "meta_load_dt": {
        "name": "meta_load_dt",
        "data_type": "DATETIME",
        "source": "metadata",
        "description": "Timestamp when ingestion ran",
    },
    "meta_snapshot_dt": {
        "name": "meta_snapshot_dt",
        "data_type": "DATETIME",
        "source": "metadata",
        "description": "Snapshot timestamp of the source data",
    },
    "meta_source_offset": {
        "name": "meta_source_offset",
        "data_type": "INTEGER",
        "source": "metadata",
        "description": "Row offset within the source (ingest-assigned)",
    },
    "meta_checksum": {
        "name": "meta_checksum",
        "data_type": "VARCHAR",
        "source": "metadata",
        "description": "Row content checksum for change detection",
    },
    "meta_pipeline_version": {
        "name": "meta_pipeline_version",
        "data_type": "VARCHAR",
        "source": "metadata",
        "description": "Pipeline version that produced the row",
    },
    "meta_component": {
        "name": "meta_component",
        "data_type": "VARCHAR",
        "source": "metadata",
        "description": "Pipeline component that produced the row",
    },
}

#: Common encoding-name aliases mapped to the canonical java.nio charset names
#: Spark's CSV reader accepts. Keys are matched after strip()+casefold().
_SPARK_ENCODING_ALIASES: dict[str, str] = {
    "ascii": "US-ASCII",
    "cp1252": "windows-1252",
    "iso-8859-1": "ISO-8859-1",
    "iso8859-1": "ISO-8859-1",
    "iso_8859_1": "ISO-8859-1",
    "latin-1": "ISO-8859-1",
    "latin1": "ISO-8859-1",
    "latin_1": "ISO-8859-1",
    "us-ascii": "US-ASCII",
    "utf-16": "UTF-16",
    "utf-8": "UTF-8",
    "utf16": "UTF-16",
    "utf8": "UTF-8",
    "utf_16": "UTF-16",
    "utf_8": "UTF-8",
    "windows-1252": "windows-1252",
    "windows1252": "windows-1252",
}


def normalize_spark_encoding(encoding: str) -> str:
    """Normalize common encoding aliases to Spark-accepted charset names.

    Examples: ``latin-1`` / ``iso-8859-1`` -> ``ISO-8859-1``, ``utf8`` ->
    ``UTF-8``. Values that are not recognized aliases are returned as-is
    (behavior-compatible with the previous pass-through fallback in
    ``tablespec.merge``); Java charset lookup is itself alias-aware, so an
    already-canonical name needs no translation.
    """
    return _SPARK_ENCODING_ALIASES.get(encoding.strip().casefold(), encoding)
