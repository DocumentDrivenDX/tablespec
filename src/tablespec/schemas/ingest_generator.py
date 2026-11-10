# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate a committed raw->ingest SQL artifact from a UMF spec.

The output is plain Spark SQL (Databricks/Delta dialect) with three parts:

  1. a ``raw_<table>`` landing table (``STRING`` for delimited sources, native
     typed columns for typed raw sources + ingest metadata),
  2. a typed ``ingested_<table>`` target table, and
  3. a cast + write transform whose shape depends on ``ingestion.mode`` and
     ``primary_key``:

       - incremental + primary_key  -> dedup-latest then MERGE (upsert)
       - incremental, no primary_key -> blind INSERT INTO (+ warning)
       - snapshot                    -> INSERT OVERWRITE (drop/reload)
       - append                      -> INSERT INTO (every landed row kept)
       - change_tracking             -> latest operation per key, then MERGE
                                        (delete codes DELETE, others upsert)

The cast expressions come from :func:`tablespec.casting_utils.cast_column_sql`,
so they match what the runtime caster produces. The result is meant to be written
to a ``.sql`` file, code-reviewed, and run independently of this library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tablespec.casting_utils import cast_column_sql
from tablespec.dialects import normalize_cast_dialect
from tablespec.models.umf import TYPED_RAW_SOURCE_KINDS
from tablespec.schemas.generators import _resolve_nullable, _sql_comment

# Databricks/Spark-SQL-correct type names for the typed target table.
# (generate_sql_ddl emits a literal DATETIME, which Spark SQL does not accept.)
_SPARK_TYPE: dict[str, str] = {
    "VARCHAR": "STRING",
    "TEXT": "STRING",
    "CHAR": "STRING",
    "STRING": "STRING",
    "INTEGER": "INT",
    "BIGINT": "BIGINT",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
    "EMBEDDING": "ARRAY<FLOAT>",
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


def _cast_for(
    col: dict[str, Any],
    *,
    dialect: str = "spark",
    source_kind: str | None = None,
    target_type_override: str | None = None,
) -> str:
    """Canonical SQL cast expression for one column."""
    if target_type_override is not None:
        col = {**col, "data_type": target_type_override}
    return cast_column_sql(
        col["name"],
        col.get("data_type", "VARCHAR"),
        col.get("format"),
        precision=col.get("precision"),
        scale=col.get("scale"),
        dialect=dialect,
        source_kind=source_kind,
    )


def _declared_source_kind(umf_data: dict[str, Any]) -> str | None:
    """Return the declared source kind, when the UMF uses the discriminated form."""
    source = umf_data.get("source")
    if isinstance(source, dict):
        kind = source.get("kind")
    else:
        kind = getattr(source, "kind", None)
    return kind.lower() if isinstance(kind, str) else kind


@dataclass(frozen=True)
class IngestSelect:
    """The dialect-agnostic core of a raw->ingest transform.

    This is the single shared seam between the two emitters
    (:func:`generate_ingest_sql` for the committed Databricks artifact and
    ``generate_dbt_project`` for dbt): both build their cast SELECT + dedup window
    from here and differ only in packaging + write strategy.

    Attributes:
    ----------
        columns: ordered output column names (UMF column order).
        mode: ``"incremental"``, ``"snapshot"``, ``"append"`` or
            ``"change_tracking"``.
        primary_key: declared primary key columns (may be empty).
        order_by: provenance ordering columns for dedup-latest (newest wins).
        dialect: public dialect spelling (``"spark"``, ``"databricks"``, or
            ``"duckdb"``). The Spark-family spellings share the same render path.
        select_block: aligned ``<cast> AS <name>`` lines, one per column, with the
            8-space indentation the artifact/dbt model bodies expect.
        key_exprs: raw-side key expressions the dedup window partitions by, one
            per primary key column (the bare key names, except for
            change_tracking with key_columns: ``coalesce(<key_col>, <pk>)``).
        operation_column: change_tracking only -- the raw operation column.
        delete_values: change_tracking only -- operation codes that delete.
    """

    columns: list[str]
    mode: str
    primary_key: list[str]
    order_by: list[str]
    dialect: str
    select_block: str
    key_exprs: tuple[str, ...] = ()
    operation_column: str | None = None
    delete_values: tuple[str, ...] = ()

    @property
    def has_dedup(self) -> bool:
        """True when a dedup-latest window applies (incremental or change_tracking + key)."""
        return self.mode in ("incremental", "change_tracking") and bool(
            self.primary_key
        )

    def dedup_window_sql(self, source: str) -> str:
        """Return a ``SELECT * ... WHERE _rn = 1`` dedup-latest subquery over *source*.

        Partitions by the primary key and keeps the newest row per key (``order_by``
        DESC). Shared by both emitters so Spark and dbt dedup identically.

        Determinism note: the winner is well-defined only when ``order_by`` is
        unique within each key partition. If two rows share the same key AND the
        same ``order_by`` value, ``row_number()`` may pick either, and the two
        engines could disagree. The pipeline contract is therefore that the
        ``order_by`` provenance (``_load_ts`` by default) is strictly increasing per
        ingest, which the fixtures uphold. (A stricter cross-engine tie-break is
        intentionally NOT added here: it would change the committed byte-for-byte
        ingest_sql goldens, and the ``order_by``-unique contract makes it moot.)
        """
        partition = ", ".join(self.key_exprs or self.primary_key)
        order_clause = ", ".join(f"{c} DESC" for c in self.order_by)
        return (
            "        SELECT * FROM (\n"
            "            SELECT *, row_number() OVER "
            f"(PARTITION BY {partition} ORDER BY {order_clause}) AS _rn\n"
            f"            FROM {source}\n"
            "        ) WHERE _rn = 1"
        )


def build_ingest_select(
    umf_data: dict[str, Any],
    *,
    dialect: str = "spark",
    cast_type_overrides: dict[str, str] | None = None,
) -> IngestSelect:
    """Build the shared cast SELECT + dedup metadata for a UMF table.

    Extracted from :func:`generate_ingest_sql` so both the committed Databricks
    artifact and the dbt project emit the exact same cast logic and dedup window
    from one place. The two emitters then differ only in packaging and write
    strategy.

    Args:
    ----
        umf_data: UMF table data (e.g. ``umf.model_dump(exclude_none=True)``).
        dialect: ``"spark"`` (default), ``"databricks"``, or ``"duckdb"``.
        cast_type_overrides: Optional explicit target types keyed by UMF column
            name, for protocol fields with a fixed physical type.

    Returns:
    -------
        An :class:`IngestSelect` carrying the aligned cast ``select_block`` and the
        mode/key/order metadata needed to build the write step.

    """
    cols: list[dict[str, Any]] = umf_data["columns"]
    overrides = cast_type_overrides or {}
    unknown_overrides = set(overrides) - {column["name"] for column in cols}
    if unknown_overrides:
        raise ValueError(
            "cast type overrides reference undeclared columns: "
            + ", ".join(sorted(unknown_overrides))
        )
    pk: list[str] = umf_data.get("primary_key") or []
    ingestion = umf_data.get("ingestion") or {}
    mode = ingestion.get("mode", "incremental")
    order_by = ingestion.get("order_by") or _DEFAULT_ORDER_BY
    render_dialect = normalize_cast_dialect(dialect)
    source_kind = _declared_source_kind(umf_data)

    # change_tracking: a delete row may carry its key only in a dedicated key
    # column, so each key is coalesce(<key_col>, <pk>) on the raw side -- both
    # for the dedup partition and for the key's own cast input.
    key_exprs: tuple[str, ...] = tuple(pk)
    operation_column = None
    delete_values: tuple[str, ...] = ()
    key_inputs: dict[str, str] = {}
    if mode == "change_tracking":
        ct = ingestion.get("change_tracking") or {}
        operation_column = ct.get("operation_column") or "SYS_CHANGE_OPERATION"
        delete_values = tuple(ct.get("delete_values") or ["D"])
        key_columns = ct.get("key_columns")
        if key_columns:
            key_inputs = {
                k: f"coalesce({kc}, {k})" for k, kc in zip(pk, key_columns, strict=True)
            }
            key_exprs = tuple(key_inputs[k] for k in pk)

    def cast(c: dict[str, Any]) -> str:
        expr = _cast_for(
            {**c, "name": key_inputs.get(c["name"], c["name"])},
            dialect=render_dialect,
            source_kind=source_kind,
            target_type_override=overrides.get(c["name"]),
        )
        return expr

    cast_pad = max((len(cast(c)) for c in cols), default=0)
    select_block = ",\n".join(
        f"        {cast(c):<{cast_pad}} AS {c['name']}" for c in cols
    )

    return IngestSelect(
        columns=[c["name"] for c in cols],
        mode=mode,
        primary_key=pk,
        order_by=order_by,
        dialect=dialect,
        select_block=select_block,
        key_exprs=key_exprs,
        operation_column=operation_column,
        delete_values=delete_values,
    )


def _create_table(name: str, body_lines: list[str], comment: str | None = None) -> str:
    lines = [
        f"CREATE TABLE IF NOT EXISTS {name} (",
        ",\n".join(body_lines),
        ") USING DELTA",
    ]
    if comment:
        lines.append(f"COMMENT '{_sql_comment(comment)}'")
    return "\n".join(lines) + ";"


def generate_ingest_sql(
    umf_data: dict[str, Any],
    *,
    raw_table: str | None = None,
    ingested_table: str | None = None,
    dialect: str = "spark",
) -> str:
    """Generate the raw->ingest SQL artifact for a UMF table.

    Args:
    ----
        umf_data: UMF table data (e.g. ``umf.model_dump(exclude_none=True)``).
        raw_table: Override for the landing table name (default ``raw_<table>``).
        ingested_table: Override for the target table name (default ``ingested_<table>``).
        dialect: public cast dialect for the generated SELECT (``"spark"``,
            ``"databricks"``, or ``"duckdb"``). The Spark-family spellings share
            the same SQL render path.

    Returns:
    -------
        A Spark SQL string containing the raw DDL, typed DDL, and transform.

    """
    name = umf_data["table_name"]
    raw = raw_table or f"raw_{name}"
    ingested = ingested_table or f"ingested_{name}"
    cols: list[dict[str, Any]] = umf_data["columns"]
    source_kind = _declared_source_kind(umf_data)
    typed_raw = source_kind in TYPED_RAW_SOURCE_KINDS

    # Shared cast SELECT + dedup metadata (the single seam reused by dbt).
    ingest = build_ingest_select(umf_data, dialect=dialect)
    pk = ingest.primary_key
    mode = ingest.mode
    order_by = ingest.order_by

    feed_columns = _change_feed_columns(umf_data, typed_raw)
    pad = max(
        (len(n) for n in [*(c["name"] for c in cols), *(n for n, _ in feed_columns)]),
        default=0,
    )

    # --- 1. raw landing table: every column STRING for delimited sources or the
    #         native typed width for parquet/JDBC + ingest metadata ---
    raw_body = [
        f"    {c['name']:<{pad}} {_typed_type(c) if typed_raw else 'STRING'}"
        for c in cols
    ]
    raw_body += [f"    {n:<{pad}} {t}" for n, t in feed_columns]
    raw_body += [f"    {n:<{pad}} {t}" for n, t in _META_COLUMNS]
    raw_comment = (
        "Raw landing zone -- native typed, as received"
        if typed_raw
        else "Raw landing zone -- untyped, as received"
    )
    raw_ddl = _create_table(raw, raw_body, raw_comment)

    # --- 2. typed target table ---
    ing_body = []
    for c in cols:
        not_null = "" if _resolve_nullable(c.get("nullable")) else " NOT NULL"
        ing_body.append(f"    {c['name']:<{pad}} {_typed_type(c)}{not_null}")
    ing_ddl = _create_table(ingested, ing_body, umf_data.get("description"))

    # --- 3. cast + write transform ---
    transform = _build_transform(raw, ingested, ingest)

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


def _change_feed_columns(
    umf_data: dict[str, Any], typed_raw: bool
) -> list[tuple[str, str]]:
    """Raw-only columns a change_tracking feed carries: the key columns (typed
    like their primary key column on typed raw) and the operation column."""
    ingestion = umf_data.get("ingestion") or {}
    if ingestion.get("mode") != "change_tracking":
        return []
    ct = ingestion.get("change_tracking") or {}
    by_name = {c["name"]: c for c in umf_data["columns"]}
    pk: list[str] = umf_data.get("primary_key") or []
    out = [
        (kc, _typed_type(by_name[k]) if typed_raw and k in by_name else "STRING")
        for k, kc in zip(pk, ct.get("key_columns") or [], strict=False)
    ]
    out.append((ct.get("operation_column") or "SYS_CHANGE_OPERATION", "STRING"))
    return out


def _change_tracking_transform(raw: str, ingested: str, ingest: IngestSelect) -> str:
    """Latest operation per key wins; delete codes DELETE, anything else upserts.

    The source carries the operation as ``_ct_operation``, so the MERGE lists
    columns explicitly rather than ``SET *`` / ``INSERT *``.
    """
    on = " AND ".join(f"tgt.{k} = src.{k}" for k in ingest.primary_key)
    deletes = ", ".join("'" + v.replace("'", "''") + "'" for v in ingest.delete_values)
    sets = ", ".join(f"tgt.{c} = src.{c}" for c in ingest.columns)
    cols = ", ".join(ingest.columns)
    vals = ", ".join(f"src.{c}" for c in ingest.columns)
    return (
        f"-- change_tracking: latest {ingest.operation_column} per key "
        f"(order_by: {', '.join(ingest.order_by)})\n"
        f"MERGE INTO {ingested} AS tgt\n"
        "USING (\n"
        f"    SELECT\n{ingest.select_block},\n"
        f"        {ingest.operation_column} AS _ct_operation\n"
        f"    FROM (\n{ingest.dedup_window_sql(raw)}\n    ) src_raw\n"
        ") AS src\n"
        f"ON {on}\n"
        f"WHEN MATCHED AND src._ct_operation IN ({deletes}) THEN DELETE\n"
        f"WHEN MATCHED THEN UPDATE SET {sets}\n"
        f"WHEN NOT MATCHED AND src._ct_operation NOT IN ({deletes}) THEN\n"
        f"    INSERT ({cols}) VALUES ({vals});"
    )


def _build_transform(raw: str, ingested: str, ingest: IngestSelect) -> str:
    """Build the part-3 transform statement for the given mode + key."""
    select_block = ingest.select_block
    mode = ingest.mode
    pk = ingest.primary_key
    order_by = ingest.order_by

    if mode == "change_tracking":
        return _change_tracking_transform(raw, ingested, ingest)

    if mode == "append":
        return (
            "-- append mode: every landed row is kept (no dedup, no overwrite).\n"
            f"INSERT INTO {ingested}\n"
            f"    SELECT\n{select_block}\n"
            f"    FROM {raw};"
        )

    if mode == "incremental" and pk:
        on = " AND ".join(f"tgt.{k} = src.{k}" for k in pk)
        source = ingest.dedup_window_sql(raw)
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
