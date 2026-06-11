"""Discover UMF specs from a live database via Spark's JDBC connector.

FEAT-031 DISC-01..03 / ADR-015 decision point 6: ``JdbcToUmfMapper`` reads a
database's ``INFORMATION_SCHEMA`` -- tables, columns, nullability, primary
keys, foreign keys -- and emits one validated :class:`~tablespec.models.umf.UMF`
per BASE TABLE. ALL connectivity is ``spark.read.format("jdbc")``:
``option("query", ...)`` for the metadata queries and the reflected DataFrame
schema (a ``WHERE 1=0`` subquery) for column types, mapped through the
existing :class:`~tablespec.profiling.spark_mapper.SparkToUmfMapper`.
tablespec gains no direct database-driver dependency and never connects to
anything itself, even at discovery time.

Emitted UMFs carry:

* sanitized table/column names (JDBC-05) with the original identifiers
  preserved (``UMF.canonical_name`` / ``UMFColumn.canonical_name``, and the
  quoted original in the per-table ``source.dbtable``),
* ``primary_key`` and ``relationships.foreign_keys`` with sanitized refs,
* a ``source:`` block of kind ``jdbc`` whose credentials are the input
  spec's ``password_secret_ref`` only (DISC-02 -- no credential material),
* the canonical provenance metadata columns
  (:data:`tablespec.ingestion.constants.PROVENANCE_COLUMNS`), so each spec is
  pipeline-complete and passes ``tablespec validate`` unmodified (DISC-02).

Note: This module requires pyspark. Install with: pip install tablespec[spark]
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from tablespec.ingestion.constants import PROVENANCE_COLUMNS
from tablespec.ingestion.jdbc import (
    jdbc_connection_options,
    quote_identifier,
    resolve_secret_ref,
    sanitize_identifier,
)
from tablespec.models.umf import UMF
from tablespec.profiling.spark_mapper import SQL_TO_UMF_TYPE, SparkToUmfMapper

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from tablespec.models.umf import JdbcSource

logger = logging.getLogger(__name__)

# INFORMATION_SCHEMA metadata queries (issued through Spark's JDBC ``query``
# option, which wraps them as derived tables -- hence no ORDER BY here; rows
# are sorted in Python).
_TABLES_SQL = (
    "SELECT TABLE_SCHEMA, TABLE_NAME "
    "FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE = 'BASE TABLE'"
)

_COLUMNS_SQL = (
    "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, "
    "IS_NULLABLE, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
    "NUMERIC_PRECISION, NUMERIC_SCALE "
    "FROM INFORMATION_SCHEMA.COLUMNS"
)

_PRIMARY_KEYS_SQL = (
    "SELECT kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.COLUMN_NAME, "
    "kcu.ORDINAL_POSITION "
    "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu "
    "ON kcu.CONSTRAINT_CATALOG = tc.CONSTRAINT_CATALOG "
    "AND kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
    "AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
    "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'"
)

_FOREIGN_KEYS_SQL = (
    "SELECT fk.TABLE_SCHEMA AS FK_SCHEMA, fk.TABLE_NAME AS FK_TABLE, "
    "fk.COLUMN_NAME AS FK_COLUMN, pk.TABLE_NAME AS REF_TABLE, "
    "pk.COLUMN_NAME AS REF_COLUMN "
    "FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fk "
    "ON fk.CONSTRAINT_CATALOG = rc.CONSTRAINT_CATALOG "
    "AND fk.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA "
    "AND fk.CONSTRAINT_NAME = rc.CONSTRAINT_NAME "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pk "
    "ON pk.CONSTRAINT_CATALOG = rc.UNIQUE_CONSTRAINT_CATALOG "
    "AND pk.CONSTRAINT_SCHEMA = rc.UNIQUE_CONSTRAINT_SCHEMA "
    "AND pk.CONSTRAINT_NAME = rc.UNIQUE_CONSTRAINT_NAME "
    "AND pk.ORDINAL_POSITION = fk.ORDINAL_POSITION"
)

# INFORMATION_SCHEMA declared types whose UMF refinement Spark's dialect
# collapses into plain StringType: fixed-width CHAR and unbounded TEXT both
# reflect as StringType -> VARCHAR, so the declared type (via the existing
# SQL_TO_UMF_TYPE map) restores the width semantics the UMF model carries.
_STRING_UMF_REFINEMENTS = frozenset({"CHAR", "TEXT"})

# Declared types whose CHARACTER_MAXIMUM_LENGTH is a meaningful UMF ``length``
# (positive, bounded). MAX/LOB types report -1 or huge sentinels -- skipped.
_LENGTH_BEARING_TYPES = frozenset(
    {"char", "nchar", "varchar", "nvarchar", "binary", "varbinary"}
)


def _normalize_declared_type(declared: str) -> str | None:
    """Map an INFORMATION_SCHEMA DATA_TYPE to a UMF type via SQL_TO_UMF_TYPE.

    Reuses the existing SQL->UMF map (no second type-mapping seam): national
    variants (``nchar``/``nvarchar``/``ntext``) resolve through their base
    names.
    """
    base = declared.strip().upper()
    if base not in SQL_TO_UMF_TYPE and base.startswith("N"):
        base = base[1:]
    return SQL_TO_UMF_TYPE.get(base)


class JdbcToUmfMapper:
    """Discover one UMF per BASE TABLE from a live database (DISC-01..03).

    Connectivity is exclusively the caller's Spark session
    (``spark.read.format("jdbc")``); type mapping is exclusively the existing
    :class:`SparkToUmfMapper` over the reflected DataFrame schema, enriched
    with INFORMATION_SCHEMA nullability, lengths, and precision/scale.
    """

    def __init__(self) -> None:
        self._spark_mapper = SparkToUmfMapper()

    def discover(self, spec: JdbcSource, spark: SparkSession) -> list[UMF]:
        """Discover UMF specs for every BASE TABLE reachable via *spec*.

        *spec* supplies the connection parameters (``url``, ``driver``,
        ``user``, ``password_secret_ref``, ``fetch_size``); its
        ``dbtable``/``query`` is ignored -- each emitted UMF gets its own
        per-table ``source.dbtable``. The secret reference is resolved once,
        up front, and fails closed naming the ref (JDBC-04) before any read.
        """
        conn = jdbc_connection_options(spec)
        if spec.password_secret_ref is not None:
            # JDBC-04: fail closed BEFORE any read; never logged or persisted.
            conn["password"] = resolve_secret_ref(spec.password_secret_ref)

        tables = self._table_list(spark, conn)
        columns_meta = self._columns_metadata(spark, conn)
        primary_keys = self._primary_keys(spark, conn)
        foreign_keys = self._foreign_keys(spark, conn)

        umfs: list[UMF] = []
        for schema_name, table_name in tables:
            umfs.append(
                self._table_umf(
                    spark=spark,
                    spec=spec,
                    conn=conn,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns_meta=columns_meta.get((schema_name, table_name), {}),
                    pk_columns=primary_keys.get((schema_name, table_name), []),
                    fk_rows=foreign_keys.get((schema_name, table_name), []),
                )
            )
        logger.info("Discovered %d base tables via JDBC", len(umfs))
        return umfs

    # -- metadata reads (all via spark.read.format("jdbc")) -------------------

    def _metadata_rows(
        self, spark: SparkSession, conn: dict[str, str], sql: str
    ) -> list[Any]:
        """Run an INFORMATION_SCHEMA query through Spark's JDBC ``query`` option."""
        return (
            spark.read.format("jdbc").options(**conn).option("query", sql).load()
        ).collect()

    def _table_list(
        self, spark: SparkSession, conn: dict[str, str]
    ) -> list[tuple[str, str]]:
        rows = self._metadata_rows(spark, conn, _TABLES_SQL)
        return sorted((r["TABLE_SCHEMA"], r["TABLE_NAME"]) for r in rows)

    def _columns_metadata(
        self, spark: SparkSession, conn: dict[str, str]
    ) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
        """Per-table column metadata keyed by original column name."""
        per_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        for r in self._metadata_rows(spark, conn, _COLUMNS_SQL):
            per_table[(r["TABLE_SCHEMA"], r["TABLE_NAME"])][r["COLUMN_NAME"]] = {
                "is_nullable": (r["IS_NULLABLE"] or "").upper() == "YES",
                "data_type": r["DATA_TYPE"] or "",
                "char_max_length": r["CHARACTER_MAXIMUM_LENGTH"],
                "numeric_precision": r["NUMERIC_PRECISION"],
                "numeric_scale": r["NUMERIC_SCALE"],
            }
        return per_table

    def _primary_keys(
        self, spark: SparkSession, conn: dict[str, str]
    ) -> dict[tuple[str, str], list[str]]:
        """Per-table PK column names (original identifiers, key order)."""
        grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
        for r in self._metadata_rows(spark, conn, _PRIMARY_KEYS_SQL):
            grouped[(r["TABLE_SCHEMA"], r["TABLE_NAME"])].append(
                (int(r["ORDINAL_POSITION"]), r["COLUMN_NAME"])
            )
        return {
            key: [name for _, name in sorted(cols)] for key, cols in grouped.items()
        }

    def _foreign_keys(
        self, spark: SparkSession, conn: dict[str, str]
    ) -> dict[tuple[str, str], list[dict[str, str]]]:
        """Per-table FK rows: column -> referenced table.column (originals)."""
        grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for r in self._metadata_rows(spark, conn, _FOREIGN_KEYS_SQL):
            grouped[(r["FK_SCHEMA"], r["FK_TABLE"])].append(
                {
                    "column": r["FK_COLUMN"],
                    "references_table": r["REF_TABLE"],
                    "references_column": r["REF_COLUMN"],
                }
            )
        return grouped

    def _reflect_schema(
        self,
        spark: SparkSession,
        conn: dict[str, str],
        spec: JdbcSource,
        schema_name: str,
        table_name: str,
    ) -> DataFrame:
        """Reflect column types from an empty read of the original table.

        Bracket/backtick quoting of the ORIGINAL identifier happens here, at
        the read boundary (JDBC-05).
        """
        qualified = (
            f"{quote_identifier(schema_name, spec.url)}."
            f"{quote_identifier(table_name, spec.url)}"
        )
        reflect = f"(SELECT * FROM {qualified} WHERE 1=0) tablespec_reflect"
        return (
            spark.read.format("jdbc").options(**conn).option("dbtable", reflect).load()
        )

    # -- UMF assembly ----------------------------------------------------------

    def _table_umf(
        self,
        *,
        spark: SparkSession,
        spec: JdbcSource,
        conn: dict[str, str],
        schema_name: str,
        table_name: str,
        columns_meta: dict[str, dict[str, Any]],
        pk_columns: list[str],
        fk_rows: list[dict[str, str]],
    ) -> UMF:
        df = self._reflect_schema(spark, conn, spec, schema_name, table_name)
        base = self._spark_mapper.map_dataframe_to_umf(
            df, sanitize_identifier(table_name)
        )

        columns: list[dict[str, Any]] = []
        for col in base["columns"]:
            original_name = col["name"]
            meta = columns_meta.get(original_name, {})
            columns.append(self._column_dict(col, original_name, meta))
        columns.extend(dict(prov) for prov in PROVENANCE_COLUMNS.values())

        data: dict[str, Any] = {
            "version": "1.0",
            "table_name": base["table_name"],
            "canonical_name": table_name,
            "table_type": base["table_type"],
            "description": f"Discovered from JDBC source table {schema_name}.{table_name}",
            "columns": columns,
            "source": self._table_source(spec, schema_name, table_name),
        }
        if pk_columns:
            data["primary_key"] = [sanitize_identifier(c) for c in pk_columns]
        if fk_rows:
            data["relationships"] = {
                "foreign_keys": [
                    {
                        "column": sanitize_identifier(fk["column"]),
                        "references_table": sanitize_identifier(fk["references_table"]),
                        "references_column": sanitize_identifier(
                            fk["references_column"]
                        ),
                        "type": "foreign_key",
                        "detection_method": "information_schema",
                    }
                    for fk in sorted(fk_rows, key=lambda f: f["column"])
                ]
            }
        return UMF(**data)

    def _column_dict(
        self,
        spark_column: dict[str, Any],
        original_name: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """One UMF column: Spark-reflected type enriched with INFORMATION_SCHEMA."""
        column: dict[str, Any] = {
            "name": sanitize_identifier(original_name),
            "canonical_name": original_name,
            "data_type": spark_column["data_type"],
            "description": spark_column.get("description"),
        }

        declared = str(meta.get("data_type", ""))
        # Width refinement: the declared CHAR/TEXT class survives even though
        # Spark reflects every string as StringType -> VARCHAR.
        if column["data_type"] == "VARCHAR":
            refined = _normalize_declared_type(declared)
            if refined in _STRING_UMF_REFINEMENTS:
                column["data_type"] = refined

        # Prefer INFORMATION_SCHEMA nullability over Spark's reflected flag.
        if meta:
            column["nullable"] = {"default": bool(meta["is_nullable"])}
        elif isinstance(spark_column.get("nullable"), bool):
            column["nullable"] = {"default": spark_column["nullable"]}

        # Lengths for bounded character/binary types ((n)var)char(n); MAX/LOB
        # sentinels (-1, multi-GB) are not meaningful UMF lengths.
        char_len = meta.get("char_max_length")
        if (
            declared.lower() in _LENGTH_BEARING_TYPES
            and isinstance(char_len, int)
            and char_len > 0
        ):
            column["length"] = char_len

        # Precision/scale: Spark's DecimalType already carries them; fall back
        # to INFORMATION_SCHEMA when the reflected type didn't.
        if column["data_type"] == "DECIMAL":
            precision = spark_column.get("precision", meta.get("numeric_precision"))
            scale = spark_column.get("scale", meta.get("numeric_scale"))
            if precision is not None:
                column["precision"] = int(precision)
            if scale is not None:
                column["scale"] = int(scale)

        return column

    def _table_source(
        self, spec: JdbcSource, schema_name: str, table_name: str
    ) -> dict[str, Any]:
        """The per-table ``source:`` block -- secret reference only (DISC-02)."""
        source: dict[str, Any] = {
            "kind": "jdbc",
            "url": spec.url,
            "dbtable": (
                f"{quote_identifier(schema_name, spec.url)}."
                f"{quote_identifier(table_name, spec.url)}"
            ),
        }
        if spec.driver is not None:
            source["driver"] = spec.driver
        if spec.user is not None:
            source["user"] = spec.user
        if spec.password_secret_ref is not None:
            source["password_secret_ref"] = spec.password_secret_ref
        if spec.fetch_size is not None:
            source["fetch_size"] = spec.fetch_size
        return source
