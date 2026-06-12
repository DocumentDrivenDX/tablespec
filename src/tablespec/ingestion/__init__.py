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

import csv
import io
from pathlib import Path
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
from tablespec.models.umf import DelimitedSource, ParquetSource

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
    if spec.comment_char is not None:
        options["comment"] = spec.comment_char
    if spec.quote_char is not None:
        options["quote"] = spec.quote_char
    if spec.escape_char is not None:
        options["escape"] = spec.escape_char
    return options


def delimited_source_has_text_quirks(spec: DelimitedSource) -> bool:
    """Whether *spec* needs line-level normalization before parsing."""
    return any(
        (
            spec.skip_rows > 0,
            spec.footer_rows is not None and spec.footer_rows > 0,
            spec.line_terminator is not None,
            spec.null_escape is not None,
        )
    )


def _resolve_line_terminator(line_terminator: str | None) -> str | None:
    if line_terminator is None:
        return None
    token = line_terminator.strip()
    upper = token.upper()
    if upper == "CRLF":
        return "\r\n"
    if upper == "LF":
        return "\n"
    if upper == "CR":
        return "\r"
    return token


def delimited_source_lines(spec: DelimitedSource, path: Path) -> list[str]:
    """Return the source file as normalized logical records.

    The returned list reflects the declared skip/footer/terminator behaviour:
    leading ``skip_rows`` rows are removed, trailing ``footer_rows`` are dropped,
    and the logical record separator is normalized to line-oriented strings.
    """
    text = path.read_bytes().decode(spec.encoding or "utf-8")
    terminator = _resolve_line_terminator(spec.line_terminator)
    if terminator is None or terminator in {"\n", "\r", "\r\n"}:
        lines = text.splitlines()
    else:
        lines = text.split(terminator)
        if lines and lines[-1] == "":
            lines.pop()

    if spec.skip_rows:
        lines = lines[spec.skip_rows :]
    footer_rows = spec.footer_rows or 0
    if footer_rows:
        lines = lines[: max(0, len(lines) - footer_rows)]

    comment_char = spec.comment_char
    if comment_char is not None:
        lines = [line for line in lines if not line.startswith(comment_char)]

    return lines


def _csv_reader_kwargs(spec: DelimitedSource) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "delimiter": spec.delimiter or "|",
        "skipinitialspace": False,
    }
    quote_char = spec.quote_char
    if quote_char is None:
        kwargs["quoting"] = csv.QUOTE_NONE
        kwargs["quotechar"] = '"'
    else:
        kwargs["quotechar"] = quote_char
    if spec.escape_char is not None:
        kwargs["escapechar"] = spec.escape_char
    return kwargs


def delimited_source_records(
    spec: DelimitedSource,
    path: Path,
    *,
    fieldnames: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str | None]]]:
    """Parse a delimited file into headers + all-string row dicts.

    ``\\N`` is always recognized as a null escape in addition to the declared
    ``null_value`` token when present.
    """
    lines = delimited_source_lines(spec, path)
    if not lines:
        headers = fieldnames or []
        return headers, []

    kwargs = _csv_reader_kwargs(spec)
    if spec.header:
        header_reader = csv.reader(io.StringIO(lines[0]), **kwargs)
        headers = next(header_reader)
        data_lines = lines[1:]
    else:
        headers = fieldnames or []
        data_lines = lines
        if not headers and data_lines:
            sample_reader = csv.reader(io.StringIO(data_lines[0]), **kwargs)
            sample = next(sample_reader)
            headers = [f"column{i}" for i in range(len(sample))]

    records: list[dict[str, str | None]] = []
    reader = csv.DictReader(
        io.StringIO("\n".join(data_lines)), fieldnames=headers, **kwargs
    )
    for row in reader:
        if row is None:
            continue
        normalized: dict[str, str | None] = {}
        for key, value in row.items():
            if key is None:
                continue
            if value is None:
                normalized[key] = None
                continue
            if (
                value == "\\N"
                or (spec.null_value is not None and value == spec.null_value)
                or (spec.null_escape is not None and value == spec.null_escape)
            ):
                normalized[key] = None
            else:
                normalized[key] = value
        records.append(normalized)
    return headers, records


def create_string_dataframe(
    spark: SparkSession,
    rows: list[dict[str, str | None]],
    columns: list[str],
) -> DataFrame:
    """Create a Spark DataFrame with every column forced to STRING."""
    from pyspark.sql.types import StringType, StructField, StructType

    schema = StructType([StructField(name, StringType(), True) for name in columns])
    if not rows:
        return spark.createDataFrame([], schema)
    return spark.createDataFrame(rows, schema=schema)


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
        if delimited_source_has_text_quirks(spec):
            headers, rows = delimited_source_records(spec, Path(spec.path))
            return create_string_dataframe(spark, rows, headers)
        options = {
            "header": spec.header,
            "sep": spec.delimiter or "|",
            "nullValue": spec.null_value,
            "encoding": normalize_spark_encoding(spec.encoding or "UTF-8"),
            "inferSchema": False,
        }
        if spec.comment_char is not None:
            options["comment"] = spec.comment_char
        return spark.read.options(**options).csv(str(spec.path))


class ParquetReader:
    """Parquet reader backed by the active Spark session."""

    def read(self, spec: SourceSpec, spark: SparkSession) -> DataFrame:
        if not isinstance(spec, ParquetSource):
            msg = f"ParquetReader requires a parquet source, got kind={spec.kind!r}"
            raise TypeError(msg)
        if spec.path is None:
            msg = "ParquetSource.path must be set before reading"
            raise ValueError(msg)
        return spark.read.parquet(str(spec.path))


def get_reader(spec: SourceSpec) -> SourceReader:
    """Build the :class:`SourceReader` for *spec*, dispatching on ``kind``."""
    kind = getattr(spec, "kind", None)
    if kind == "delimited":
        return CsvReader()
    if kind == "parquet":
        return ParquetReader()
    if kind == "jdbc":
        return JdbcReader()
    msg = f"unknown source kind: {kind!r}"
    raise ValueError(msg)


__all__ = [
    "CsvReader",
    "HeaderMatch",
    "JdbcReader",
    "ParquetReader",
    "SecretResolutionError",
    "create_string_dataframe",
    "delimited_source_has_text_quirks",
    "delimited_source_lines",
    "delimited_source_records",
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
