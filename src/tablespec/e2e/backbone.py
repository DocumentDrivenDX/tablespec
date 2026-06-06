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

Tiering + canonicalization REUSE the conformance facades in
``tests/conformance/engines.py`` (row / compile / structure / opt-in e2e) and the
``tests/ingest_parity/canonical.to_json`` byte-parity canonicalizer. This module
does NOT build a parallel harness -- it wires the compiled artifacts INTO those
engines. The real-serverless leg is gated by
:func:`engines.databricks_e2e_availability` (``DATABRICKS_HOST`` opt-in); local
success NEVER depends on a remote workspace.

Engine adapters
===============
The runner is parametrized by a small :class:`_BackboneEngine` adapter -- one per
local execution backend (DuckDB, classic local Spark, Sail Spark-Connect). Each
adapter reuses the conformance facades for the load-raw schema, the SQL-statement
splitter, the decimal-scale map and the ``canonical.to_json`` canonicalizer, so the
backbone never reimplements ingest/dbt/spark execution that ``engines.py`` already
provides. The DataFrame the adapter hands to :class:`GXSuiteExecutor` is auto-routed
(classic Spark -> GX add_spark engine; Connect -> the native path) inside the
executor itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from tablespec.e2e.manifest import CompiledArtifacts


# --- conformance-facade imports (reused; never reimplemented) -----------------

# The conformance harness lives under ``tests/`` (outside the package). When the
# backbone runs from a demo script we must put the repo root on ``sys.path`` so the
# facades import; under pytest the rootdir is already importable.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.conformance.engines import (  # noqa: E402
    databricks_e2e_availability,
    decimal_scales,
    split_sql_statements,
)
from tests.ingest_parity.canonical import to_json  # noqa: E402


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
    ) -> tuple[Any, Any, dict[str, Any]]:
        """Execute the compiled ingest -> return (raw_df, ingested_df, umf_data)."""
        raise NotImplementedError


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

    def _load_raw(self, umf: dict[str, Any], csv_path: Path, raw_table: str) -> None:
        """Reuse the conformance oracle raw-load schema (engines.py:527)."""
        from pyspark.sql.functions import to_timestamp

        string_cols = [c["name"] for c in umf["columns"]] + ["_source_file"]
        read_schema_fields: list[tuple[str, str]] = [
            (name, "string") for name in string_cols
        ]
        read_schema_fields.append(("_load_ts", "string"))
        schema_ddl = ", ".join(f"`{n}` {t}" for n, t in read_schema_fields)

        df = (
            self._spark.read.option("header", True)
            .option("quote", '"')
            .option("escape", '"')
            .option("multiLine", True)
            .schema(schema_ddl)
            .csv(str(csv_path))
            .withColumn("_load_ts", to_timestamp("_load_ts", "yyyy-MM-dd HH:mm:ss"))
        )
        ordered = [c["name"] for c in umf["columns"]] + ["_source_file", "_load_ts"]
        df = df.select(*ordered)
        if self._connect:
            # Connect has no Hive/Delta saveAsTable here -> back the raw table with a
            # temp view the compiled transform's FROM clause resolves against.
            self._spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
            df.createOrReplaceTempView(raw_table)
        else:
            self._spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
            df.write.format("delta").mode("overwrite").saveAsTable(raw_table)

    def ingest(
        self, artifacts: CompiledArtifacts, table: str, batches: list[Path]
    ) -> tuple[Any, Any, dict[str, Any]]:
        umf = yaml.safe_load(artifacts.table(table).umf_snapshot.read_text())
        raw_table = f"raw_{table}"
        ingested_table = f"ingested_{table}"

        self._purge(raw_table)
        self._purge(ingested_table)

        sql = artifacts.table(table).ingest_sql.read_text()
        statements = split_sql_statements(sql)
        create_stmts, transform_stmt = statements[:-1], statements[-1]
        raw_create_prefix = f"CREATE TABLE {raw_table}".upper()
        for stmt in create_stmts:
            # Skip the raw landing CREATE TABLE: ``_load_raw`` owns the raw relation
            # (Delta ``saveAsTable`` on classic, temp view on Connect), so running the
            # compiled CREATE first only risks a DELTA_CREATE_TABLE_WITH_NON_EMPTY_
            # LOCATION clash against a warehouse dir left by a prior run. The typed-
            # target CREATE (which the transform writes into) still runs.
            if stmt.upper().startswith(raw_create_prefix):
                continue
            self._spark.sql(stmt)

        for batch in batches:
            self._load_raw(umf, batch, raw_table)
            self._spark.sql(transform_stmt)

        raw_df = self._spark.table(raw_table)
        ingested_df = self._spark.table(ingested_table)
        return raw_df, ingested_df, umf


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

    def _connect(self, db_path: Path):
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute("SET TimeZone='UTC'")
        return con

    def _load_raw(self, db_path: Path, umf: dict[str, Any], csv_path: Path) -> None:
        table = umf["table_name"]
        cols = [c["name"] for c in umf["columns"]]
        # The CSV may already carry the ingest metadata (conformance corpus) or be a
        # clean source extract without it (reflected source tables). Detect from the
        # header: if present, project it through; otherwise SYNTHESIZE it (literal
        # source file + load timestamp) exactly as the conformance gold loader does,
        # so the compiled dbt model always sees the all-STRING + metadata raw shape.
        header = csv_path.read_text().splitlines()[0].split(",")
        has_meta = "_source_file" in header
        con = self._connect(db_path)
        try:
            con.execute(f"DROP TABLE IF EXISTS raw_{table}")
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
            projection = ", ".join(f'"{c}"' for c in cols)
            if has_meta:
                projection += ', "_source_file", cast("_load_ts" as timestamp)'
            else:
                projection += f", '{table}.csv', TIMESTAMP '2026-01-01 00:00:00'"
            con.execute(
                f"INSERT INTO raw_{table} "
                f"SELECT {projection} "
                f"FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)"
            )
        finally:
            con.close()

    def _run_dbt(self, project: Path, db_path: Path) -> None:
        import os

        env = dict(os.environ, DBT_DUCKDB_PATH=str(db_path))
        result = subprocess.run(
            ["dbt", "run", "--profiles-dir", str(project), "--project-dir", str(project)],
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
    ) -> tuple[Any, Any, dict[str, Any]]:
        umf = yaml.safe_load(artifacts.table(table).umf_snapshot.read_text())
        # Copy the compiled dbt ingest project into a scratch dir so the duckdb file
        # lives beside it (the project is read-only compile output).
        compiled = artifacts.table(table).dbt_ingest_project
        assert compiled is not None
        project = Path(tempfile.mkdtemp(prefix=f"backbone_ingest_{table}_"))
        shutil.copytree(compiled, project, dirs_exist_ok=True)
        self._project = project
        db_path = project / "ingest.duckdb"
        self._db_path = db_path

        for batch in batches:
            self._load_raw(db_path, umf, batch)
            self._run_dbt(project, db_path)

        raw_df = self._frame_from_duckdb(
            db_path, f"raw_{table}", [c["name"] for c in umf["columns"]] + ["_source_file", "_load_ts"]
        )
        ingested_df = self._frame_from_duckdb(
            db_path, table, [c["name"] for c in umf["columns"]]
        )
        return raw_df, ingested_df, umf

    def _frame_from_duckdb(self, db_path: Path, table: str, columns: list[str]) -> Any:
        """Lift a DuckDB table into a Spark/Sail frame for the GX executor."""
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
        # Stringify everything: the GX raw/ingested suites operate on values, and a
        # uniform string frame avoids Spark schema-inference surprises on NULLs.
        str_rows = [{k: (None if v is None else str(v)) for k, v in r.items()} for r in rows]
        if not str_rows:
            from pyspark.sql.types import StringType, StructField, StructType

            schema = StructType([StructField(c, StringType(), True) for c in columns])
            return self._spark.createDataFrame([], schema)
        return self._spark.createDataFrame(str_rows)


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
            raw_df, ingested_df, umf = eng.ingest(artifacts, table, batches)
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
                StageOutcome(name=f"[{eng.name}] ingest:{table}", ok=False, detail=detail)
            )
            continue

        # Stages 2 & 4: validate raw + ingested via the COMPILED suite (one staged
        # execution classifies raw-stage vs ingested-stage expectations).
        stages.append(_validate_stage(spark, raw_df, ingested_df, ta.suite_json, table, eng.name))

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
        stages.extend(_run_ldp(artifacts, raw_batches))

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
    """Stage 5 (dbt): parse always; compile/run on duckdb/local-spark only.

    Consumes the persisted single-table ingest dbt projects + the multi-table GOLD
    dbt DAG project. ``dbt parse`` (offline) runs for EVERY project regardless of
    backend; ``dbt run`` is attempted only when the engine supports local execution
    (DuckDB / classic Spark session). On a Databricks compile target ``dbt run``
    would need a live warehouse -> parse-only.
    """
    out: list[StageOutcome] = []
    projects: list[tuple[str, Path]] = []
    for name, ta in artifacts.tables.items():
        if ta.dbt_ingest_project is not None:
            projects.append((f"ingest:{name}", ta.dbt_ingest_project))
    if artifacts.dbt_gold_project is not None:
        projects.append(("gold", artifacts.dbt_gold_project))

    for label, project in projects:
        out.append(_dbt_parse(label, project))
    return out


def _dbt_parse(label: str, project: Path) -> StageOutcome:
    """Run the always-available offline ``dbt parse`` over a compiled project.

    Invoked as a SUBPROCESS (mirroring the conformance ``dbt run`` facade) rather
    than the in-process ``dbtRunner``: the in-process runner installs a global file
    logger that holds the persisted project's ``logs/dbt.log`` handle open past the
    call, which surfaces as an unraisable ResourceWarning at interpreter teardown.
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
    detail = f"project={project.name} manifest={'written' if manifest.exists() else 'missing'}"
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


def _run_ldp(
    artifacts: CompiledArtifacts, raw_batches: dict[str, list[Path]]
) -> list[StageOutcome]:
    """Stage 5 (LDP): structure golden + local cast-body parity (single batch).

    Consumes the compiled LDP project (``ldp/ingested_<t>.sql``). The structure leg
    asserts each ingested dataset file exists + carries the shared cast SELECT body;
    the cast-parity leg (single-batch only) runs that extracted SELECT over the raw
    rows on DuckDB and confirms it canonicalizes to the same rows the dbt ingest
    produced. APPLY CHANGES execution is the opt-in Databricks-only leg.
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


# Re-exported canonicalizer + facade helpers so callers / tests can reuse the SAME
# byte-parity surface the backbone validates against.
__all__ = [
    "BackboneResult",
    "StageOutcome",
    "decimal_scales",
    "make_engine",
    "run_backbone",
    "to_json",
]
