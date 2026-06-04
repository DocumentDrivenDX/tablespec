"""Generate a committed raw->ingest SQL artifact from a UMF spec.

The output is plain Spark SQL (Databricks/Delta dialect) with three parts:

  1. a ``raw_<table>`` landing table (every column ``STRING`` + ingest metadata),
  2. a typed ``ingested_<table>`` target table, and
  3. a cast + write transform whose shape depends on ``ingestion.mode`` and
     ``primary_key``:

       - incremental + primary_key  -> dedup-latest then MERGE (upsert)
       - incremental, no primary_key -> blind INSERT INTO (+ warning)
       - snapshot                    -> INSERT OVERWRITE (drop/reload)

The cast expressions come from :func:`tablespec.casting_utils.cast_column_sql`,
so they match what the runtime caster produces. The result is meant to be written
to a ``.sql`` file, code-reviewed, and run independently of this library.
"""

from __future__ import annotations

from typing import Any

from tablespec.casting_utils import cast_column_sql
from tablespec.schemas.generators import _resolve_nullable

# Databricks/Spark-SQL-correct type names for the typed target table.
# (generate_sql_ddl emits a literal DATETIME, which Spark SQL does not accept.)
_SPARK_TYPE: dict[str, str] = {
    "VARCHAR": "STRING",
    "TEXT": "STRING",
    "CHAR": "STRING",
    "STRING": "STRING",
    "INTEGER": "INT",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
}

# Ingest provenance columns appended to the raw landing table.
_META_COLUMNS: list[tuple[str, str]] = [
    ("_source_file", "STRING"),
    ("_load_ts", "TIMESTAMP"),
]
_DEFAULT_ORDER_BY: list[str] = ["_load_ts"]


def _typed_type(col: dict[str, Any]) -> str:
    """Spark-SQL type for the typed target column (matches the cast target)."""
    dt = col.get("data_type", "VARCHAR").upper()
    if dt == "DECIMAL":
        precision = col.get("precision") or 10
        scale = col["scale"] if col.get("scale") is not None else 2
        return f"DECIMAL({precision},{scale})"
    if dt == "VARCHAR" and col.get("max_length"):
        return f"VARCHAR({col['max_length']})"
    return _SPARK_TYPE.get(dt, "STRING")


def _cast_for(col: dict[str, Any]) -> str:
    """Canonical SQL cast expression for one column."""
    return cast_column_sql(
        col["name"],
        col.get("data_type", "VARCHAR"),
        col.get("format"),
        precision=col.get("precision"),
        scale=col.get("scale"),
    )


def _create_table(name: str, body_lines: list[str], comment: str | None = None) -> str:
    lines = [
        f"CREATE TABLE IF NOT EXISTS {name} (",
        ",\n".join(body_lines),
        ") USING DELTA",
    ]
    if comment:
        lines.append(f"COMMENT '{comment.replace(chr(39), chr(39) * 2)[:255]}'")
    return "\n".join(lines) + ";"


def generate_ingest_sql(
    umf_data: dict[str, Any],
    *,
    raw_table: str | None = None,
    ingested_table: str | None = None,
) -> str:
    """Generate the raw->ingest SQL artifact for a UMF table.

    Args:
    ----
        umf_data: UMF table data (e.g. ``umf.model_dump(exclude_none=True)``).
        raw_table: Override for the landing table name (default ``raw_<table>``).
        ingested_table: Override for the target table name (default ``ingested_<table>``).

    Returns:
    -------
        A Spark SQL string containing the raw DDL, typed DDL, and transform.

    """
    name = umf_data["table_name"]
    raw = raw_table or f"raw_{name}"
    ingested = ingested_table or f"ingested_{name}"
    cols: list[dict[str, Any]] = umf_data["columns"]
    pk: list[str] = umf_data.get("primary_key") or []
    ingestion = umf_data.get("ingestion") or {}
    mode = ingestion.get("mode", "incremental")  # snapshot | incremental
    order_by = ingestion.get("order_by") or _DEFAULT_ORDER_BY

    pad = max((len(c["name"]) for c in cols), default=0)

    # --- 1. raw landing table: every column STRING + ingest metadata ---
    raw_body = [f"    {c['name']:<{pad}} STRING" for c in cols]
    raw_body += [f"    {n:<{pad}} {t}" for n, t in _META_COLUMNS]
    raw_ddl = _create_table(raw, raw_body, "Raw landing zone -- untyped, as received")

    # --- 2. typed target table ---
    ing_body = []
    for c in cols:
        not_null = "" if _resolve_nullable(c.get("nullable")) else " NOT NULL"
        ing_body.append(f"    {c['name']:<{pad}} {_typed_type(c)}{not_null}")
    ing_ddl = _create_table(ingested, ing_body, umf_data.get("description"))

    # --- 3. cast + write transform ---
    cast_pad = max((len(_cast_for(c)) for c in cols), default=0)
    select_block = ",\n".join(
        f"        {_cast_for(c):<{cast_pad}} AS {c['name']}" for c in cols
    )
    transform = _build_transform(raw, ingested, select_block, mode, pk, order_by)

    header = (
        "-- ============================================================================\n"
        f"-- Ingest plan: {raw} -> {ingested}\n"
        "-- ============================================================================\n"
        "-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.\n"
        f"-- Mode: {mode}    Primary key: {pk or '(none)'}    Order by: {', '.join(order_by)}\n"
        "-- ============================================================================"
    )
    return "\n\n".join(
        [
            header,
            "-- 1. Raw landing table\n" + raw_ddl,
            "-- 2. Typed target table\n" + ing_ddl,
            "-- 3. Raw -> ingested transform\n" + transform,
        ]
    )


def _build_transform(
    raw: str,
    ingested: str,
    select_block: str,
    mode: str,
    pk: list[str],
    order_by: list[str],
) -> str:
    """Build the part-3 transform statement for the given mode + key."""
    if mode == "incremental" and pk:
        partition = ", ".join(pk)
        order_clause = ", ".join(f"{c} DESC" for c in order_by)
        on = " AND ".join(f"tgt.{k} = src.{k}" for k in pk)
        source = (
            "        SELECT * FROM (\n"
            "            SELECT *, row_number() OVER "
            f"(PARTITION BY {partition} ORDER BY {order_clause}) AS _rn\n"
            f"            FROM {raw}\n"
            "        ) WHERE _rn = 1"
        )
        return (
            f"MERGE INTO {ingested} AS tgt\n"
            "USING (\n"
            f"    SELECT\n{select_block}\n"
            f"    FROM (\n{source}\n    ) src_raw\n"
            ") AS src\n"
            f"ON {on}\n"
            "WHEN MATCHED THEN UPDATE SET *\n"
            "WHEN NOT MATCHED THEN INSERT *;"
        )

    if mode == "incremental":
        return (
            "-- WARNING: no primary_key + incremental mode -> cannot dedup/upsert.\n"
            "-- WARNING: appending blindly; duplicate rows are possible on re-ingest.\n"
            f"INSERT INTO {ingested}\n"
            f"    SELECT\n{select_block}\n"
            f"    FROM {raw};"
        )

    if pk:
        return (
            f"-- snapshot mode: full drop/reload (order_by: {', '.join(order_by)})\n"
            f"INSERT OVERWRITE {ingested}\n"
            f"    SELECT\n{select_block}\n"
            f"    FROM {raw};"
        )

    return (
        "-- WARNING: no primary_key + snapshot mode -> blind drop/reload.\n"
        "-- WARNING: entire table is overwritten; no key-level reconciliation.\n"
        f"INSERT OVERWRITE {ingested}\n"
        f"    SELECT\n{select_block}\n"
        f"    FROM {raw};"
    )
