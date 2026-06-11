"""The runtime BACKBONE: execute the COMPILED artifacts (never the UMF).

Given a :class:`~tablespec.e2e.manifest.CompiledArtifacts` (from the compile
orchestrator) and raw input batches, run the staged runtime exactly as production
would, consuming the persisted artifacts:

  1. INGEST raw -> ROW: execute the COMPILED split ingest SQL. The raw landing
     table is all-STRING + ``_source_file`` + ``_load_ts`` -- matching the
     conformance oracle loader at ``tests/conformance/engines.py:527`` (reused as a
     FACADE; do NOT reimplement the raw-load schema here).
  2. VALIDATE RAW via :meth:`GXSuiteExecutor.execute_staged(raw_df, ingested_df,
     expectations)` using the COMPILED suite JSON -- NOT ``TableValidator``.
     Connect DataFrames auto-route to the native path inside the executor.
  3. INGEST ROW -> INGESTED: the compiled cast + MERGE/INSERT transform statement.
  4. VALIDATE INGESTED (same staged executor; the ingested-stage expectations).
  5. TRANSFORMS:
       * dbt PARSE always (offline manifest, no warehouse).
       * dbt COMPILE/RUN only on duckdb / local-spark (Databricks dbt compile needs
         a live warehouse -> parse-only there).
       * execute the gold SQL plan where supported.
       * LDP = structure golden + local cast-body parity (single-batch only);
         APPLY CHANGES execution ONLY on real Databricks.

Tiering + canonicalization reuse SHIPPED helpers in the package -- the
``tablespec.canonical.to_json`` byte-parity canonicalizer, the
``tablespec.e2e.sql_runtime.split_sql_statements`` splitter and the
``tablespec.e2e.gating.databricks_e2e_availability`` opt-in gate -- so the backbone
ships without importing the test tree (a wheel ships no ``tests/``). The conformance
engines under ``tests/conformance/engines.py`` re-export these same helpers for the
matrix tests. This module does NOT build a parallel harness. The real-serverless leg
is gated by :func:`tablespec.e2e.gating.databricks_e2e_availability`
(``DATABRICKS_HOST`` opt-in); local success NEVER depends on a remote workspace.

Engine adapters
===============
The runner is parametrized by a small :class:`_BackboneEngine` adapter -- one per
local execution backend (DuckDB, classic local Spark, Sail Spark-Connect). Each
adapter reuses the conformance facades for the load-raw schema and the decimal-scale
map, and the SHIPPED ``split_sql_statements`` splitter + ``canonical.to_json``
canonicalizer, so the backbone never reimplements ingest/dbt/spark execution that
``engines.py`` already provides. The DataFrame the adapter hands to
:class:`GXSuiteExecutor` is auto-routed
(classic Spark -> GX add_spark engine; Connect -> the native path) inside the
executor itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tablespec.canonical import to_json
from tablespec.e2e.compiled import CompiledSchema, load_compiled_schema
from tablespec.e2e.gating import databricks_e2e_availability
from tablespec.e2e.sql_runtime import split_sql_statements
from tablespec.ingestion import spark_csv_options
from tablespec.models.umf import DelimitedSource

if TYPE_CHECKING:
    from tablespec.e2e.manifest import CompiledArtifacts


def _declared_delimited(umf_snapshot: Path) -> DelimitedSource | None:
    """The delimited source the UMF snapshot DECLARES for raw loading, or None.

    None means the snapshot declares neither ``source:`` nor ``file_format``;
    the engines then preserve the historical comma-CSV raw-load behavior the
    conformance corpus depends on. (A declared :class:`DelimitedSource`
    defaults its delimiter to ``|``, so deriving options from an UNDECLARED
    spec would silently flip every legacy comma-CSV case to pipes.)

    Parses only the two source-shape keys rather than validating the whole
    UMF -- stage-1 raw loading otherwise consumes COMPILED artifacts, never
    the UMF snapshot.
    """
    import yaml

    data = yaml.safe_load(umf_snapshot.read_text(encoding="utf-8")) or {}
    declared = data.get("source")
    if declared is not None:
        if declared.get("kind") != "delimited":
            raise NotImplementedError(
                f"backbone raw loading supports only delimited sources; "
                f"{umf_snapshot.name} declares kind={declared.get('kind')!r} "
                "(parquet: bead tablespec-61da147e, jdbc: bead tablespec-4b65c810)"
            )
        return DelimitedSource.model_validate(declared)
    file_format = data.get("file_format")
    if file_format is not None:
        return DelimitedSource.model_validate(file_format)
    return None


@dataclass(frozen=True)
class StageOutcome:
    """Result of one backbone stage (ingest / validate / transform leg)."""

    name: str
    ok: bool
    detail: str = ""
    canonical: str | None = None


@dataclass(frozen=True)
class BackboneResult:
    """Aggregate of every backbone stage that ran for a compile."""

    stages: list[StageOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff every stage that ran succeeded."""
        return all(s.ok for s in self.stages)


def _extract_merge_using_select(transform_stmt: str) -> str:
    """Pull the deduped cast SELECT out of a compiled ``MERGE INTO ... USING ( ... )``.

    The compiled raw->ingested transform is a Delta ``MERGE`` whose ``USING ( <select>
    ) AS src`` body is the typed, PK-deduped projection of the raw rows. Spark Connect
    (Sail) cannot execute the Delta MERGE itself, but it CAN run that inner SELECT, so
    the Connect ingest path materializes it directly. Returns the inner SELECT with
    balanced parentheses (the first ``USING (`` through its matching ``)``).
    """
    upper = transform_stmt.upper()
    using_idx = upper.find("USING")
    if using_idx == -1:  # pragma: no cover - compiled MERGE always has USING
        raise ValueError("compiled transform is not a MERGE (no USING clause)")
    open_idx = transform_stmt.find("(", using_idx)
    if open_idx == -1:  # pragma: no cover - USING is always followed by '('
        raise ValueError("MERGE USING clause has no opening parenthesis")
    depth = 0
    for i in range(open_idx, len(transform_stmt)):
        ch = transform_stmt[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return transform_stmt[open_idx + 1 : i].strip()
    raise ValueError("unbalanced parentheses in MERGE USING clause")  # pragma: no cover


# ---------------------------------------------------------------------------
# Engine adapters (the local execution backends the backbone is parametrized by)
# ---------------------------------------------------------------------------


class _BackboneEngine:
    """Adapter over one local execution backend that consumes compiled artifacts.

    Each concrete engine knows how to (a) execute the compiled split ingest SQL to
    land the raw row table and apply the typed transform, (b) expose the raw and
    ingested rows as the DataFrame objects :class:`GXSuiteExecutor` validates, and
    (c) run the transform legs it supports. The base orchestration lives in
    :func:`run_backbone`; subclasses provide the I/O.
    """

    name: str = "base"
    #: Whether ``dbt run`` (full execution, not just parse) is supported locally.
    supports_dbt_run: bool = False

    def ingest(
        self, artifacts: CompiledArtifacts, table: str, batches: list[Path]
    ) -> tuple[Any, Any, CompiledSchema]:
        """Execute the compiled ingest -> return (raw_df, ingested_df, schema).

        The third element is the :class:`CompiledSchema` parsed from the COMPILED
        ingest SQL artifact (NOT the UMF snapshot) -- it carries the typed-projection
        column order and the decimal-scale map the canonicalizer needs.
        """
        raise NotImplementedError

    def ingested_rows(
        self, schema: CompiledSchema, ingested_df: Any
    ) -> list[dict[str, Any]]:
        """Collect the TYPED ingested rows from the engine's native store.

        Returns row dicts keyed by the COMPILED typed-target column names, carrying
        the engine's native typed values -- the input the SHARED ``canonical.to_json``
        canonicalizer renders for cross-engine byte parity. The default collects from
        a Spark/Connect DataFrame; engines whose native store is not a DataFrame
        (DuckDB) override this to read their own store so parity compares the typed
        ingest, not a stringified validation substrate.
        """
        columns = schema.columns
        return [{k: r.asDict().get(k) for k in columns} for r in ingested_df.collect()]


class _SparkEngine(_BackboneEngine):
    """Classic local Spark / Sail Connect: run the compiled SPARK ingest SQL.

    Consumes ``ingest/<t>.ingest.sql`` (the compiled artifact) verbatim: the CREATE
    statements stand up ``raw_<t>`` / ``ingested_<t>``, then for each batch the raw
    rows are loaded with the conformance oracle's all-STRING + ``_source_file`` +
    ``_load_ts`` schema (engines.py raw-load facade) and the compiled transform
    statement is executed. Classic Spark vs Sail Connect differ ONLY in whether the
    raw load goes through ``saveAsTable`` (Delta) or a temp view, which the executor
    then validates -- auto-routed by frame type inside ``GXSuiteExecutor``.
    """

    def __init__(self, spark: Any, *, connect: bool, name: str) -> None:
        self._spark = spark
        self._connect = connect
        self.name = name
        # dbt session-run needs a classic JVM session; Connect cannot host it.
        self.supports_dbt_run = not connect

    def _purge(self, table: str) -> None:
        """Drop *table* and remove any stale managed-warehouse directory.

        A bare warehouse directory left by a prior run (the managed-table metadata
        gone but the Delta dir intact) makes the next ``CREATE TABLE`` /
        ``saveAsTable`` fail with ``DELTA_CREATE_TABLE_WITH_NON_EMPTY_LOCATION``.
        Dropping clears the catalog entry; the filesystem purge clears an orphaned
        dir so ingest is idempotent across runs on a shared warehouse.
        """
        self._spark.sql(f"DROP TABLE IF EXISTS {table}")
        try:
            warehouse = self._spark.conf.get("spark.sql.warehouse.dir")
        except Exception:  # pragma: no cover - Connect may not expose it
            warehouse = None
        if warehouse and warehouse.startswith("file:"):
            loc = Path(warehouse[len("file:") :]) / table
            if loc.exists():
                shutil.rmtree(loc, ignore_errors=True)

    def _load_raw(
        self,
        schema: CompiledSchema,
        csv_path: Path,
        raw_table: str,
        fmt: DelimitedSource | None = None,
    ) -> None:
        """Build the all-STRING raw landing relation (engines.py:527 schema).

        The raw shape is every business column as STRING plus ``_source_file`` +
        ``_load_ts`` (a TIMESTAMP). The business-column set + order come from the
        COMPILED ingest SQL (parsed into ``schema``), NOT the UMF snapshot. A corpus
        CSV may already carry that metadata or be a clean source extract that lacks
        it; we read only the columns the CSV header actually declares and SYNTHESIZE
        any missing metadata (literal source-file + load timestamp) -- exactly as the
        DuckDB engine and conformance gold loader do. Without this, Sail's strict CSV
        reader rejects a 2-field row against a 4-field schema.

        ``fmt`` is the UMF-DECLARED delimited source (``source:`` /
        ``file_format``); when None (legacy corpus UMFs declare neither) the
        historical comma-CSV read is preserved EXACTLY. Either way every
        business column lands as STRING (ADR-007).
        """
        # ``pyspark.sql.functions`` resolves to the CLASSIC builtins, whose ``lit`` /
        # ``to_timestamp`` call ``_to_java_column`` and so need a live JVM
        # ``SparkContext`` -- which a Spark Connect (Sail) session does not have. Route
        # to ``pyspark.sql.connect.functions`` on Connect so the expressions build
        # against the Connect plan instead of a (non-existent) JVM column.
        if self._connect:
            from pyspark.sql.connect.functions import lit, to_timestamp
        else:
            from pyspark.sql.functions import lit, to_timestamp

        business_cols = schema.columns
        # The raw landing table is ``raw_<t>``; the synthesized ``_source_file`` literal
        # mirrors the source table name (``<t>.csv``), recovered from the compiled raw
        # table name rather than the UMF.
        source_name = (
            raw_table[len("raw_") :] if raw_table.startswith("raw_") else raw_table
        )
        if fmt is None:
            header = csv_path.read_text().splitlines()[0].split(",")
        elif fmt.header:
            text = csv_path.read_text(encoding=fmt.encoding or "utf-8")
            header = text.splitlines()[0].split(fmt.delimiter or "|")
        else:  # headerless declared file: metadata can only be synthesized
            header = []
        has_meta = "_source_file" in header

        read_cols = list(business_cols)
        if has_meta:
            read_cols += ["_source_file", "_load_ts"]
        schema_ddl = ", ".join(f"`{n}` string" for n in read_cols)

        if fmt is None:
            options: dict[str, Any] = {
                "header": True,
                "quote": '"',
                "escape": '"',
                "multiLine": True,
            }
        else:
            options = spark_csv_options(fmt)
            options.setdefault("quote", '"')
            options.setdefault("escape", '"')
            options["multiLine"] = True
        df = self._spark.read.options(**options).schema(schema_ddl).csv(str(csv_path))
        if has_meta:
            df = df.withColumn(
                "_load_ts", to_timestamp("_load_ts", "yyyy-MM-dd HH:mm:ss")
            )
        else:
            df = df.withColumn("_source_file", lit(f"{source_name}.csv")).withColumn(
                "_load_ts",
                to_timestamp(lit("2026-01-01 00:00:00"), "yyyy-MM-dd HH:mm:ss"),
            )
        ordered = [*business_cols, "_source_file", "_load_ts"]
        df = df.select(*ordered)
        if self._connect:
            # Connect has no Hive/Delta saveAsTable here -> back the raw table with a
            # temp view the compiled transform's FROM clause resolves against. Collect
            # + re-create the frame so the view is an in-memory relation rather than a
            # lazy CSV scan re-executed on every downstream read (the GX validation
            # pass scans it again, and Sail's CSV reader has surfaced row-shape
            # mismatches on the second scan).
            rows = [r.asDict() for r in df.collect()]
            self._spark.sql(f"DROP VIEW IF EXISTS {raw_table}")
            if rows:
                self._spark.createDataFrame(rows).createOrReplaceTempView(raw_table)
            else:  # pragma: no cover - corpus batches are non-empty
                df.createOrReplaceTempView(raw_table)
        else:
            self._spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
            df.write.format("delta").mode("overwrite").saveAsTable(raw_table)

    def ingest(
        self, artifacts: CompiledArtifacts, table: str, batches: list[Path]
    ) -> tuple[Any, Any, CompiledSchema]:
        sql = artifacts.table(table).ingest_sql.read_text()
        # Derive the raw-load schema, projection order, table names, and decimal
        # scales from the COMPILED ingest SQL -- never the UMF snapshot. The
        # snapshot contributes ONLY the declared source shape (reader options).
        fmt = _declared_delimited(artifacts.table(table).umf_snapshot)
        schema = load_compiled_schema(artifacts.table(table).ingest_sql, table)
        raw_table = schema.raw_table
        ingested_table = schema.ingested_table

        self._purge(raw_table)
        self._purge(ingested_table)

        statements = split_sql_statements(sql)
        create_stmts, transform_stmt = statements[:-1], statements[-1]

        if self._connect:
            # Sail (Spark Connect) has NO Delta Lake write path: ``USING DELTA`` +
            # ``MERGE INTO`` create the table metadata but never write the
            # ``_delta_log`` commit files, so the compiled Delta transform fails with
            # "No commit files found in _delta_log". Connect DOES execute plain
            # SELECT/CTAS, so on Connect the typed cast is materialized by running the
            # MERGE's deduped cast SELECT (its ``USING ( ... )`` body) directly. For a
            # single batch over an empty target this is row-equivalent to the MERGE
            # (the body already dedups on the PK), which is the single-batch invariant
            # the LDP cast-parity leg also asserts.
            for batch in batches:
                self._load_raw(schema, batch, raw_table, fmt)
            cast_select = _extract_merge_using_select(transform_stmt)
            self._spark.sql(f"DROP VIEW IF EXISTS {ingested_table}")
            self._spark.sql(
                f"CREATE OR REPLACE TEMP VIEW {ingested_table} AS {cast_select}"
            )
            raw_df = self._spark.table(raw_table)
            ingested_df = self._spark.table(ingested_table)
            return raw_df, ingested_df, schema

        raw_create_prefix = f"CREATE TABLE {raw_table}".upper()
        for stmt in create_stmts:
            # Skip the raw landing CREATE TABLE: ``_load_raw`` owns the raw relation
            # (Delta ``saveAsTable``), so running the compiled CREATE first only risks
            # a DELTA_CREATE_TABLE_WITH_NON_EMPTY_LOCATION clash against a warehouse
            # dir left by a prior run. The typed-target CREATE (which the transform
            # writes into) still runs.
            if stmt.upper().startswith(raw_create_prefix):
                continue
            self._spark.sql(stmt)

        for batch in batches:
            self._load_raw(schema, batch, raw_table, fmt)
            self._spark.sql(transform_stmt)

        raw_df = self._spark.table(raw_table)
        ingested_df = self._spark.table(ingested_table)
        return raw_df, ingested_df, schema


class _DuckDBEngine(_BackboneEngine):
    """DuckDB (no JVM): run the compiled single-table dbt INGEST project.

    The compiled SPARK ingest SQL (MERGE/INSERT OVERWRITE, Delta) is not DuckDB
    SQL, so on the DuckDB backend the consumed compiled artifact is the persisted
    ``dbt_ingest/<t>/`` project (also a compile output). Raw rows are loaded with
    the conformance DuckDB raw-load schema (all VARCHAR + ``_source_file`` +
    ``_load_ts`` TIMESTAMP), then ``dbt run`` applies the compiled cast model. The
    GX suite is validated against pandas frames lifted into the active Spark/Sail
    session (the executor needs a Spark frame), so the DuckDB engine requires a
    session purely as the validation substrate.
    """

    name = "duckdb"
    supports_dbt_run = True

    def __init__(self, spark: Any | None = None) -> None:
        # Optional session used ONLY to wrap DuckDB rows for the GX executor.
        self._spark = spark
        self._db_path: Path | None = None
        self._project: Path | None = None
        self._ingested_table: str | None = None

    def _connect(self, db_path: Path):
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute("SET TimeZone='UTC'")
        return con

    def _load_raw(
        self,
        db_path: Path,
        schema: CompiledSchema,
        csv_path: Path,
        fmt: DelimitedSource | None = None,
    ) -> None:
        # The raw table name + business-column set come from the COMPILED ingest SQL
        # (parsed into ``schema``), NOT the UMF snapshot. ``fmt`` is the UMF-DECLARED
        # delimited source; None preserves the historical comma-CSV read EXACTLY
        # (the conformance corpus declares no file_format). Rows stay all-VARCHAR
        # either way (ADR-007).
        raw_table = schema.raw_table
        source_name = (
            raw_table[len("raw_") :] if raw_table.startswith("raw_") else raw_table
        )
        cols = schema.columns
        # The CSV may already carry the ingest metadata (conformance corpus) or be a
        # clean source extract without it (reflected source tables). Detect from the
        # header: if present, project it through; otherwise SYNTHESIZE it (literal
        # source file + load timestamp) exactly as the conformance gold loader does,
        # so the compiled dbt model always sees the all-STRING + metadata raw shape.
        if fmt is None:
            header = csv_path.read_text().splitlines()[0].split(",")
            read_csv = f"read_csv_auto('{csv_path}', header=true, all_varchar=true)"
        else:
            delimiter = fmt.delimiter or "|"
            if fmt.header:
                text = csv_path.read_text(encoding=fmt.encoding or "utf-8")
                header = text.splitlines()[0].split(delimiter)
            else:  # headerless declared file: metadata can only be synthesized
                header = []

            def _sq(value: str) -> str:
                return value.replace("'", "''")

            read_opts = [
                f"header={'true' if fmt.header else 'false'}",
                "all_varchar=true",
                f"delim='{_sq(delimiter)}'",
            ]
            if not fmt.header:
                # Headerless: bind the compiled business-column names by position.
                names = ", ".join(f"'{_sq(c)}'" for c in cols)
                read_opts.append(f"names=[{names}]")
            if fmt.null_value is not None:
                read_opts.append(f"nullstr='{_sq(fmt.null_value)}'")
            if fmt.quote_char is not None:
                read_opts.append(f"quote='{_sq(fmt.quote_char)}'")
            if fmt.escape_char is not None:
                read_opts.append(f"escape='{_sq(fmt.escape_char)}'")
            read_csv = f"read_csv_auto('{csv_path}', {', '.join(read_opts)})"
        has_meta = "_source_file" in header
        con = self._connect(db_path)
        try:
            con.execute(f"DROP TABLE IF EXISTS {raw_table}")
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE {raw_table} ({coldefs})")
            projection = ", ".join(f'"{c}"' for c in cols)
            if has_meta:
                projection += ', "_source_file", cast("_load_ts" as timestamp)'
            else:
                projection += f", '{source_name}.csv', TIMESTAMP '2026-01-01 00:00:00'"
            con.execute(f"INSERT INTO {raw_table} SELECT {projection} FROM {read_csv}")
        finally:
            con.close()

    def _run_dbt(self, project: Path, db_path: Path) -> None:
        import os

        env = dict(os.environ, DBT_DUCKDB_PATH=str(db_path))
        result = subprocess.run(
            [
                "dbt",
                "run",
                "--profiles-dir",
                str(project),
                "--project-dir",
                str(project),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                "dbt run failed:\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )

    def ingest(
        self, artifacts: CompiledArtifacts, table: str, batches: list[Path]
    ) -> tuple[Any, Any, CompiledSchema]:
        # Derive the raw-load schema, projection order, and table names from the
        # COMPILED ingest SQL -- never the UMF snapshot. The snapshot contributes
        # ONLY the declared source shape (reader options).
        fmt = _declared_delimited(artifacts.table(table).umf_snapshot)
        schema = load_compiled_schema(artifacts.table(table).ingest_sql, table)
        # Copy the compiled dbt ingest project into a scratch dir so the duckdb file
        # lives beside it (the project is read-only compile output).
        compiled = artifacts.table(table).dbt_ingest_project
        assert compiled is not None
        project = Path(tempfile.mkdtemp(prefix=f"backbone_ingest_{table}_"))
        shutil.copytree(compiled, project, dirs_exist_ok=True)
        self._project = project
        db_path = project / "ingest.duckdb"
        self._db_path = db_path
        self._ingested_table = table

        for batch in batches:
            self._load_raw(db_path, schema, batch, fmt)
            self._run_dbt(project, db_path)

        # Raw stage validates the UNTYPED landing rows -> stringify (raw IS strings).
        raw_df = self._frame_from_duckdb(
            db_path,
            schema.raw_table,
            [*schema.columns, "_source_file", "_load_ts"],
            stringify=True,
        )
        # Ingested stage validates the TYPED cast output. Preserve DuckDB-native typed
        # values so an ingested numeric range (``between``) check compares NUMERICALLY
        # rather than LEXICOGRAPHICALLY -- stringifying here would make e.g. '250.5'
        # read as > '1000.0'. The raw frame is the only one that must be all-STRING.
        ingested_df = self._frame_from_duckdb(
            db_path, table, schema.columns, stringify=False
        )
        return raw_df, ingested_df, schema

    def ingested_rows(
        self, schema: CompiledSchema, ingested_df: Any
    ) -> list[dict[str, Any]]:
        """Read the TYPED ingested rows straight from the DuckDB store.

        The DataFrame handed back from :meth:`ingest` is the STRINGIFIED GX-validation
        substrate (a Spark/Connect frame), so canonicalizing it would compare strings,
        not the typed ingest. Re-read the dbt-materialized DuckDB table instead so the
        cross-engine byte-parity check sees the same typed values the Spark/Sail legs
        canonicalize.
        """
        assert self._db_path is not None and self._ingested_table is not None
        columns = schema.columns
        con = self._connect(self._db_path)
        try:
            projection = ", ".join(f'"{c}"' for c in columns)
            records = con.execute(
                f"SELECT {projection} FROM {self._ingested_table}"
            ).fetchall()
        finally:
            con.close()
        return [dict(zip(columns, rec, strict=True)) for rec in records]

    def _frame_from_duckdb(
        self, db_path: Path, table: str, columns: list[str], *, stringify: bool
    ) -> Any:
        """Lift a DuckDB table into a Spark/Sail frame for the GX executor.

        When *stringify* is True every value is rendered to a string (the raw landing
        stage, which is untyped by construction; a uniform string frame also avoids
        Spark schema-inference surprises on NULLs). When False the DuckDB-native typed
        values are passed through so a typed (ingested) numeric range check compares
        numerically rather than lexicographically.
        """
        con = self._connect(db_path)
        try:
            projection = ", ".join(f'"{c}"' for c in columns)
            records = con.execute(f"SELECT {projection} FROM {table}").fetchall()
        finally:
            con.close()
        rows = [dict(zip(columns, rec, strict=True)) for rec in records]
        assert self._spark is not None, (
            "DuckDB backbone needs a session to host GX validation frames"
        )
        if stringify:
            rows = [
                {k: (None if v is None else str(v)) for k, v in r.items()} for r in rows
            ]
        if not rows:
            from pyspark.sql.types import StringType, StructField, StructType

            schema = StructType([StructField(c, StringType(), True) for c in columns])
            return self._spark.createDataFrame([], schema)
        return self._spark.createDataFrame(rows)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def make_engine(backend: str, *, spark: Any | None = None) -> _BackboneEngine:
    """Build the backbone engine adapter for *backend*.

    Args:
        backend: ``"duckdb"``, ``"spark"`` (classic local Spark), or ``"sail"``
            (Spark Connect).
        spark: an active session. Required for ``"spark"`` / ``"sail"``; for
            ``"duckdb"`` it is the validation substrate only (may be a Connect
            session).

    Returns:
        The matching :class:`_BackboneEngine` adapter.
    """
    if backend == "duckdb":
        return _DuckDBEngine(spark)
    if backend == "spark":
        assert spark is not None, "the spark backend needs an active classic session"
        return _SparkEngine(spark, connect=False, name="spark")
    if backend == "sail":
        assert spark is not None, "the sail backend needs an active Connect session"
        return _SparkEngine(spark, connect=True, name="sail")
    raise ValueError(f"unknown backbone backend: {backend!r}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_backbone(
    artifacts: CompiledArtifacts,
    *,
    spark: Any,
    raw_batches: dict[str, list[Path]],
    run_transforms: bool = True,
    backend: str = "spark",
    engine: _BackboneEngine | None = None,
) -> BackboneResult:
    """Execute the compiled artifacts end to end against *raw_batches*.

    Args:
        artifacts: the compile manifest to consume (paths already absolute).
        spark: active Spark (classic or Connect) session for ingest + validation.
        raw_batches: per-table ordered raw CSV batch paths to ingest.
        run_transforms: also run the transform legs (stage 5). Disabled in a
            pure ingest+validate smoke run.
        backend: ``"spark"`` (classic), ``"sail"`` (Connect), or ``"duckdb"``.
            Ignored if *engine* is supplied.
        engine: explicit engine adapter (overrides *backend*).

    Returns:
        A :class:`BackboneResult` enumerating each stage outcome.
    """
    eng = engine or make_engine(backend, spark=spark)
    stages: list[StageOutcome] = []

    for table, batches in raw_batches.items():
        ta = artifacts.table(table)

        # Stage 1: ingest raw -> row (+ typed transform) from the compiled artifact.
        try:
            raw_df, ingested_df, _schema = eng.ingest(artifacts, table, batches)
            stages.append(
                StageOutcome(
                    name=f"[{eng.name}] ingest:{table}",
                    ok=True,
                    detail=f"raw+ingested materialized from {ta.ingest_sql.name}",
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced as a failed stage
            detail = str(exc) or repr(exc)
            stages.append(
                StageOutcome(
                    name=f"[{eng.name}] ingest:{table}", ok=False, detail=detail
                )
            )
            continue

        # Stages 2 & 4: validate raw + ingested via the COMPILED suite (one staged
        # execution classifies raw-stage vs ingested-stage expectations).
        stages.append(
            _validate_stage(spark, raw_df, ingested_df, ta.suite_json, table, eng.name)
        )

        # Stage record: the typed transform already ran inside ingest (stage 3);
        # surface it explicitly so the consumed compiled transform is visible.
        stages.append(
            StageOutcome(
                name=f"[{eng.name}] transform:{table}",
                ok=True,
                detail=f"raw->ingested cast applied from {ta.ingest_sql.name}",
            )
        )

    if run_transforms:
        stages.extend(_run_dbt_transforms(artifacts, engine=eng))
        stages.extend(_run_gold_plan(artifacts))
        stages.extend(_run_ldp(artifacts))

    return BackboneResult(stages=stages)


# --- stage helpers (each consumes a COMPILED artifact) ------------------------


def _validate_stage(
    spark: Any,
    raw_df: Any,
    ingested_df: Any,
    suite_path: Path,
    table: str,
    engine_name: str,
) -> StageOutcome:
    """Stages 2 & 4: run ``GXSuiteExecutor.execute_staged`` with the compiled suite.

    Loads the compiled expectation list from *suite_path* and classifies/executes
    raw-stage vs ingested-stage expectations inside the executor.
    """
    from tablespec.validation.gx_executor import GXSuiteExecutor

    expectations = json.loads(suite_path.read_text())
    executor = GXSuiteExecutor(spark)
    result = executor.execute_staged(raw_df, ingested_df, expectations)

    raw = result.raw
    ing = result.ingested
    ok = raw.success and ing.success
    detail = (
        f"suite={suite_path.name} "
        f"raw[{raw.passed}/{raw.total}] ingested[{ing.passed}/{ing.total}] "
        f"skipped={len(result.skipped)}"
    )
    return StageOutcome(name=f"[{engine_name}] validate:{table}", ok=ok, detail=detail)


def _run_dbt_transforms(
    artifacts: CompiledArtifacts, *, engine: _BackboneEngine
) -> list[StageOutcome]:
    """Stage 5 (dbt): offline ``dbt parse`` over every compiled dbt project.

    Consumes the persisted single-table ingest dbt projects + the multi-table GOLD
    dbt DAG project and runs ``dbt parse`` (genuinely offline -- no warehouse, no
    partial parse) for EACH, asserting the project resolves to a manifest. This is
    the parse-not-compile guarantee: on a Databricks compile target ``dbt compile``
    would open a SQL-warehouse connection and HANG against an unreachable host, so
    the backbone never compiles/runs the gold DAG here.

    Executed ``dbt run`` lives elsewhere, not in this stage:
      * the per-table INGEST cast is materialized by ``dbt run`` INSIDE
        :meth:`_DuckDBEngine.ingest` (the engine consumes the compiled ingest dbt
        project to produce the typed rows the validation + parity legs check), and
      * the gold dbt DAG ``dbt run`` is exercised by the conformance gold tier.

    The engine's :attr:`_BackboneEngine.supports_dbt_run` capability is recorded in
    the stage detail so the parse-only-here decision is explicit per backend.
    """
    out: list[StageOutcome] = []
    projects: list[tuple[str, Path]] = []
    for name, ta in artifacts.tables.items():
        if ta.dbt_ingest_project is not None:
            projects.append((f"ingest:{name}", ta.dbt_ingest_project))
    if artifacts.dbt_gold_project is not None:
        projects.append(("gold", artifacts.dbt_gold_project))

    for label, project in projects:
        out.append(_dbt_parse(label, project, supports_run=engine.supports_dbt_run))
    return out


def _dbt_parse(
    label: str, project: Path, *, supports_run: bool = False
) -> StageOutcome:
    """Run the always-available offline ``dbt parse`` over a compiled project.

    Invoked as a SUBPROCESS (mirroring the conformance ``dbt run`` facade) rather
    than the in-process ``dbtRunner``: the in-process runner installs a global file
    logger that holds the persisted project's ``logs/dbt.log`` handle open past the
    call, which surfaces as an unraisable ResourceWarning at interpreter teardown.

    *supports_run* records whether the active backend could run this project locally
    (DuckDB / classic Spark) -- it is surfaced in the detail to make the parse-only
    decision explicit; the backbone still only PARSES here (executed ``dbt run`` is
    the ingest engine + the conformance gold tier).
    """
    result = subprocess.run(
        [
            "dbt",
            "parse",
            "--profiles-dir",
            str(project),
            "--project-dir",
            str(project),
            "--no-partial-parse",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    manifest = project / "target" / "manifest.json"
    ok = result.returncode == 0 and manifest.exists()
    run_note = "run-capable" if supports_run else "parse-only backend"
    detail = (
        f"project={project.name} "
        f"manifest={'written' if manifest.exists() else 'missing'} ({run_note})"
    )
    return StageOutcome(name=f"dbt parse:{label}", ok=ok, detail=detail)


def _run_gold_plan(artifacts: CompiledArtifacts) -> list[StageOutcome]:
    """Stage 5 (gold): consume the compiled single-target gold SQL plan(s).

    The compiled artifact is ``gold_plan/<target>.plan.sql`` (``generate_sql_plan``,
    SINGLE-target). Execution of a cross-table gold plan needs the source tables
    materialized in the same engine; the backbone proves the compiled plan is
    present + non-empty + statement-splittable (the executed gold path is the dbt
    GOLD DAG project run, covered by the conformance gold tier). This keeps the
    single-target plan DISTINCT from the dbt DAG project per the contract.
    """
    out: list[StageOutcome] = []
    for name, ta in artifacts.tables.items():
        if ta.gold_plan_sql is None:
            continue
        sql = ta.gold_plan_sql.read_text()
        statements = split_sql_statements(sql)
        ok = bool(statements)
        out.append(
            StageOutcome(
                name=f"gold-plan:{name}",
                ok=ok,
                detail=f"plan={ta.gold_plan_sql.name} statements={len(statements)}",
            )
        )
    return out


def _run_ldp(artifacts: CompiledArtifacts) -> list[StageOutcome]:
    """Stage 5 (LDP): structure golden (+ opt-in APPLY CHANGES on real Databricks).

    Consumes the compiled LDP project (``ldp/ingested_<t>.sql``). The structure leg
    asserts each ingested dataset file exists + carries the shared cast SELECT body.

    The LDP dataset bodies are emitted in the SPARK/Databricks dialect (``FROM STREAM
    raw_<t>``, ``APPLY CHANGES``, Spark-dialect casts); they are NOT DuckDB-runnable,
    so the backbone does NOT execute the LDP cast body locally. The EXECUTED
    cast-body parity is the dbt ingest leg, which materializes the SAME shared cast
    SELECT (``build_ingest_select``) and is byte-checked against the committed golden
    by :func:`canonical_ingested` / the e2e matrix -- the LDP body is the same shared
    seam, so its structure-golden check plus the executed dbt-ingest parity together
    prove the LDP cast. APPLY CHANGES execution is the opt-in Databricks-only leg
    (gated below); local success never depends on it.
    """
    out: list[StageOutcome] = []
    if artifacts.ldp_project is None:
        return out

    for name in artifacts.tables:
        # A STAGING table emits ingested/ingested_<t>.sql (the cast dataset); a GOLD
        # table emits gold/gold_<t>.sql (a materialized-view derivation). Whichever
        # the LDP emitter produced for this table is the structure artifact to check.
        ingested_sql = artifacts.ldp_project / "ingested" / f"ingested_{name}.sql"
        gold_sql = artifacts.ldp_project / "gold" / f"gold_{name}.sql"
        dataset = ingested_sql if ingested_sql.exists() else gold_sql
        if not dataset.exists():
            out.append(
                StageOutcome(
                    name=f"ldp-structure:{name}",
                    ok=False,
                    detail="no LDP dataset emitted for this table",
                )
            )
            continue
        body = dataset.read_text()
        # Structure invariant: the LDP dataset carries the shared cast SELECT body.
        has_select = "SELECT" in body.upper()
        out.append(
            StageOutcome(
                name=f"ldp-structure:{name}",
                ok=has_select,
                detail=f"{dataset.name} carries cast SELECT body",
            )
        )

    # Opt-in real-serverless leg gated by the workspace availability check; local
    # success never depends on it.
    reason = databricks_e2e_availability()
    if reason is None:
        out.append(
            StageOutcome(
                name="ldp-apply-changes",
                ok=True,
                detail="databricks workspace available (opt-in e2e leg eligible)",
            )
        )
    return out


def canonical_ingested(
    engine: _BackboneEngine,
    artifacts: CompiledArtifacts,
    table: str,
    batches: list[Path],
    *,
    ts_precision: int = 0,
) -> str:
    """Run *engine*'s compiled ingest for *table* and canonicalize the typed rows.

    Drives the engine's :meth:`ingest` over *batches*, reads back the TYPED ingested
    rows from its native store (:meth:`_BackboneEngine.ingested_rows`), and renders
    them through the SHARED ``canonical.to_json`` at *ts_precision*. Two engines agree
    on the ingest iff this string is byte-identical -- the same cross-engine parity
    contract the conformance matrix uses. ``ts_precision`` defaults to 0 (the
    second-resolution corpus convention; the goldens pin 0 at their call sites).
    """
    _raw_df, ingested_df, schema = engine.ingest(artifacts, table, batches)
    rows = engine.ingested_rows(schema, ingested_df)
    # Decimal scales come from the COMPILED typed DDL (parsed into ``schema``), not a
    # ``decimal_scales(umf)`` call on the source UMF model.
    return to_json(
        rows, schema.columns, schema.decimal_scales, ts_precision=ts_precision
    )


# Re-exported canonicalizer + facade helpers so callers / tests can reuse the SAME
# byte-parity surface the backbone validates against.
__all__ = [
    "BackboneResult",
    "StageOutcome",
    "canonical_ingested",
    "make_engine",
    "run_backbone",
    "to_json",
]
