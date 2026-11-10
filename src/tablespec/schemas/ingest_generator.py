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
       - change_tracking, merge      -> latest operation per key, then MERGE
                                        (delete codes DELETE, others upsert)
       - change_tracking, rebuild    -> INSERT OVERWRITE of the live state from
                                        the full raw history (newest baseline
                                        supersedes)

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


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


@dataclass(frozen=True)
class ChangeFeed:
    """Change-tracking settings of an :class:`IngestSelect`, rendered as SQL.

    Every emitter (Spark artifact, dbt, LDP) builds its change-tracking SQL
    from these fragments so the operation, delete and baseline semantics are
    identical everywhere. Operation codes compare trimmed and upper-cased.

    Attributes:
    ----------
        strategy: ``"merge"`` (apply each batch) or ``"rebuild"`` (recompute
            from the full raw history; the newest baseline supersedes).
        operation_column: raw column with the operation code.
        delete_values: upper-cased codes that delete the keyed row.
        baseline_values: upper-cased codes marking baseline rows, or ``None``
            for "operation is NULL or blank".
        version_column: raw per-row change version, ordered after ``order_by``.
        version_order: the version's ORDER BY expression -- ``try_cast(... as
            BIGINT)`` on all-STRING raw so versions sort numerically.
        delivery_column: raw column ordering deliveries (``rebuild``).
    """

    strategy: str
    operation_column: str
    delete_values: tuple[str, ...]
    baseline_values: tuple[str, ...] | None
    version_column: str | None
    delivery_column: str
    version_order: str | None = None

    #: Name the normalized operation code travels under in generated SQL.
    OPERATION_ALIAS = "_ct_operation"

    @property
    def operation_expr(self) -> str:
        """Normalized operation code over the raw operation column."""
        return f"upper(trim({self.operation_column}))"

    def is_delete(self, op: str = OPERATION_ALIAS) -> str:
        """Boolean (never NULL) -- *op* is a delete code."""
        return f"coalesce({op} IN ({_sql_list(self.delete_values)}), false)"

    def is_baseline(self, op: str = OPERATION_ALIAS) -> str:
        """Boolean (never NULL) -- *op* marks a baseline row."""
        if self.baseline_values is None:
            return f"({op} IS NULL OR {op} = '')"
        return f"coalesce({op} IN ({_sql_list(self.baseline_values)}), false)"


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
        change_feed: change_tracking only -- the feed's :class:`ChangeFeed`.
        key_casts: the typed cast expression of each primary key column, in
            primary_key order (what a key compares as in the target).
    """

    columns: list[str]
    mode: str
    primary_key: list[str]
    order_by: list[str]
    dialect: str
    select_block: str
    key_exprs: tuple[str, ...] = ()
    change_feed: ChangeFeed | None = None
    key_casts: tuple[str, ...] = ()

    @property
    def order_terms(self) -> list[str]:
        """Newest-first ordering columns: ``order_by`` then the change version."""
        feed = self.change_feed
        if feed is not None and feed.version_column:
            return [*self.order_by, feed.version_order or feed.version_column]
        return list(self.order_by)

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
        order_clause = ", ".join(f"{c} DESC" for c in self.order_terms)
        return (
            "        SELECT * FROM (\n"
            "            SELECT *, row_number() OVER "
            f"(PARTITION BY {partition} ORDER BY {order_clause}) AS _rn\n"
            f"            FROM {source}\n"
            "        ) WHERE _rn = 1"
        )

    def feed(self) -> ChangeFeed:
        """The change feed, for mode ``change_tracking`` (raises otherwise)."""
        if self.change_feed is None:
            msg = f"ingestion mode {self.mode!r} has no change feed"
            raise ValueError(msg)
        return self.change_feed

    def _with_operation(self, source: str) -> str:
        feed = self.feed()
        return (
            f"(SELECT *, {feed.operation_expr} AS {feed.OPERATION_ALIAS} FROM {source})"
        )

    def change_batch_sql(self, source: str) -> str:
        """Latest row per key in *source* (one or more batches), deletes kept.

        Rows carry ``_ct_operation`` so the caller can delete or upsert; the
        ``merge`` strategy applies this set to the target.
        """
        return self.dedup_window_sql(self._with_operation(source) + " AS ct_src")

    def change_state_sql(self, source: str) -> str:
        """Current live rows from *source*'s full history (``rebuild``).

        Scopes to the newest baseline's rows (by ``delivery_column``) plus every
        increment delivered after it -- all rows when no baseline has landed --
        then keeps the latest row per key and drops keys whose latest operation
        is a delete.
        """
        feed = self.feed()
        delivery = feed.delivery_column
        partition = ", ".join(self.key_exprs or self.primary_key)
        order_clause = ", ".join(f"{c} DESC" for c in self.order_terms)
        changes = self._with_operation(source)
        return (
            "        SELECT * FROM (\n"
            "            SELECT *, row_number() OVER "
            f"(PARTITION BY {partition} ORDER BY {order_clause}) AS _rn\n"
            "            FROM (\n"
            "                SELECT c.* FROM "
            f"{changes} AS c\n"
            "                CROSS JOIN (\n"
            f"                    SELECT max({delivery}) AS _ct_baseline FROM {changes} AS b\n"
            f"                    WHERE {feed.is_baseline('b.' + feed.OPERATION_ALIAS)}\n"
            "                ) AS nb\n"
            "                WHERE nb._ct_baseline IS NULL\n"
            f"                   OR ({feed.is_baseline('c.' + feed.OPERATION_ALIAS)} "
            f"AND c.{delivery} = nb._ct_baseline)\n"
            f"                   OR (NOT {feed.is_baseline('c.' + feed.OPERATION_ALIAS)} "
            f"AND c.{delivery} > nb._ct_baseline)\n"
            "            ) AS scoped\n"
            f"        ) WHERE _rn = 1 AND NOT {feed.is_delete()}"
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
    change_feed: ChangeFeed | None = None
    key_inputs: dict[str, str] = {}
    if mode == "change_tracking":
        ct = ingestion.get("change_tracking") or {}
        baseline_values = ct.get("baseline_values")
        change_feed = ChangeFeed(
            strategy=ct.get("strategy") or "merge",
            operation_column=ct.get("operation_column") or "SYS_CHANGE_OPERATION",
            delete_values=tuple(
                v.strip().upper() for v in ct.get("delete_values") or ["D"]
            ),
            baseline_values=(
                tuple(v.strip().upper() for v in baseline_values)
                if baseline_values is not None
                else None
            ),
            version_column=ct.get("version_column"),
            delivery_column=ct.get("delivery_column") or order_by[0],
            version_order=(
                None
                if not ct.get("version_column")
                else ct["version_column"]
                if source_kind in TYPED_RAW_SOURCE_KINDS
                else f"try_cast({ct['version_column']} as BIGINT)"
            ),
        )
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

    by_name = {c["name"]: c for c in cols}
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
        change_feed=change_feed,
        key_casts=tuple(cast(by_name[k]) for k in pk if k in by_name),
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
    if ct.get("version_column"):
        out.append((ct["version_column"], "BIGINT" if typed_raw else "STRING"))
    return out


def _change_tracking_transform(raw: str, ingested: str, ingest: IngestSelect) -> str:
    """Render the change_tracking write for the feed's strategy.

    ``merge``: the latest operation per key in the batch is MERGEd -- delete
    codes DELETE, anything else (baseline rows included) upserts. The source
    carries ``_ct_operation``, so the MERGE lists columns explicitly rather
    than ``SET *`` / ``INSERT *``.

    ``rebuild``: the table is overwritten with the live state recomputed from
    the full raw history (:meth:`IngestSelect.change_state_sql`).
    """
    feed = ingest.feed()
    order = ", ".join(ingest.order_terms)
    if feed.strategy == "rebuild":
        return (
            f"-- change_tracking (rebuild): live state from the full raw history; the newest\n"
            f"-- baseline (by {feed.delivery_column}) supersedes earlier rows (order_by: {order})\n"
            f"INSERT OVERWRITE {ingested}\n"
            f"    SELECT\n{ingest.select_block}\n"
            f"    FROM (\n{ingest.change_state_sql(raw)}\n    ) src_raw;"
        )
    on = " AND ".join(f"tgt.{k} = src.{k}" for k in ingest.primary_key)
    sets = ", ".join(f"tgt.{c} = src.{c}" for c in ingest.columns)
    cols = ", ".join(ingest.columns)
    vals = ", ".join(f"src.{c}" for c in ingest.columns)
    op = f"src.{feed.OPERATION_ALIAS}"
    return (
        f"-- change_tracking (merge): latest {feed.operation_column} per key "
        f"(order_by: {order})\n"
        f"MERGE INTO {ingested} AS tgt\n"
        "USING (\n"
        f"    SELECT\n{ingest.select_block},\n"
        f"        {feed.OPERATION_ALIAS}\n"
        f"    FROM (\n{ingest.change_batch_sql(raw)}\n    ) src_raw\n"
        ") AS src\n"
        f"ON {on}\n"
        f"WHEN MATCHED AND {feed.is_delete(op)} THEN DELETE\n"
        f"WHEN MATCHED THEN UPDATE SET {sets}\n"
        f"WHEN NOT MATCHED AND NOT {feed.is_delete(op)} THEN\n"
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
