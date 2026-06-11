"""Multi-source ingestion (FEAT-031 / ADR-015): source readers + raw-header utilities.

A :class:`SourceReader` turns a UMF ``source:`` spec (see
``tablespec.models.umf.SourceSpec``) into a Spark DataFrame. ``get_reader``
dispatches on the spec's ``kind``; delimited flat files (:class:`CsvReader`)
and jdbc sources (:class:`JdbcReader`, bead tablespec-4b65c810) are delivered
here, parquet raises :class:`NotImplementedError` until its bead lands
(tablespec-61da147e).

This package never imports PySpark at module import time -- readers receive an
active session, keeping ``tablespec[spark]`` optional (ADR-003).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from tablespec.ingestion.constants import normalize_spark_encoding
from tablespec.ingestion.jdbc import (
    JdbcReader,
    SecretResolutionError,
    jdbc_connection_options,
    jdbc_options,
    quote_identifier,
    resolve_secret_ref,
    sanitize_identifier,
)
from tablespec.ingestion.raw_ingester import (
    HeaderMatch,
    build_column_lookup,
    map_headers,
)
from tablespec.models.umf import DelimitedSource

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from tablespec.models.umf import SourceSpec


@runtime_checkable
class SourceReader(Protocol):
    """Reads one source spec into a Spark DataFrame."""

    def read(self, spec: SourceSpec, spark: SparkSession) -> DataFrame:
        """Read the rows *spec* describes using the active *spark* session."""
        ...


def spark_csv_options(spec: DelimitedSource) -> dict[str, Any]:
    """Spark ``DataFrameReader`` CSV options derived from a delimited spec.

    Optional characters (``null_value`` / ``quote_char`` / ``escape_char``)
    are included only when declared, so callers can layer their own defaults
    on top.
    """
    options: dict[str, Any] = {
        "header": spec.header,
        "sep": spec.delimiter or "|",
        "encoding": normalize_spark_encoding(spec.encoding or "UTF-8"),
        "inferSchema": False,
    }
    if spec.null_value is not None:
        options["nullValue"] = spec.null_value
    if spec.quote_char is not None:
        options["quote"] = spec.quote_char
    if spec.escape_char is not None:
        options["escape"] = spec.escape_char
    return options


class CsvReader:
    """Delimited flat-file reader with UMF-derived options.

    The read logic extracted from ``tablespec.merge`` (header / delimiter /
    null-token / encoding from the spec, schema inference off -- raw columns
    stay strings per ADR-007). The spec's ``path`` names the file to read.
    """

    def read(self, spec: SourceSpec, spark: SparkSession) -> DataFrame:
        """Read ``spec.path`` as CSV with the spec's reader options."""
        if not isinstance(spec, DelimitedSource):
            msg = f"CsvReader requires a delimited source, got kind={spec.kind!r}"
            raise TypeError(msg)
        if spec.path is None:
            msg = "DelimitedSource.path must be set before reading"
            raise ValueError(msg)
        return spark.read.options(
            header=spec.header,
            sep=spec.delimiter or "|",
            nullValue=spec.null_value,
            encoding=normalize_spark_encoding(spec.encoding or "UTF-8"),
            inferSchema=False,
        ).csv(str(spec.path))


def get_reader(spec: SourceSpec) -> SourceReader:
    """Build the :class:`SourceReader` for *spec*, dispatching on ``kind``."""
    kind = getattr(spec, "kind", None)
    if kind == "delimited":
        return CsvReader()
    if kind == "parquet":
        msg = "parquet source reading is delivered by bead tablespec-61da147e"
        raise NotImplementedError(msg)
    if kind == "jdbc":
        return JdbcReader()
    msg = f"unknown source kind: {kind!r}"
    raise ValueError(msg)


__all__ = [
    "CsvReader",
    "HeaderMatch",
    "JdbcReader",
    "SecretResolutionError",
    "SourceReader",
    "build_column_lookup",
    "get_reader",
    "jdbc_connection_options",
    "jdbc_options",
    "map_headers",
    "normalize_spark_encoding",
    "quote_identifier",
    "resolve_secret_ref",
    "sanitize_identifier",
    "spark_csv_options",
]
