"""Shared ingestion constants and normalizers."""

from __future__ import annotations

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
