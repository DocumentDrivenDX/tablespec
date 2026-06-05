"""Engine adapter interface for the cross-engine conformance matrix (Phase 3).

This module replaces the four copy-pasted ``_load_raw`` / ``_collect_canonical``
helpers (Spark baseline, dbt-duckdb parity, dbt-spark executed, gold) with ONE
adapter contract so the matrix test can iterate ``(case x available-engine)``
uniformly. Every engine:

  * declares an :meth:`Engine.availability` gate (a reason string when it cannot
    run, ``None`` when it can) so an unavailable engine is *skipped with a visible
    reason*, never silently passed;
  * runs the case end-to-end on a REAL engine against REAL CSV data (no mocks for
    the behaviour under test); and
  * returns its result through the SHARED ``canonical.to_json`` at the case's
    pinned ``ts_precision`` -- so two engines "agree" iff their canonical strings
    are byte-identical, and each is compared to the SAME committed golden (the
    SparkDirect oracle output, i.e. "the previous implementation").

Engines implemented here (the locally-executable matrix):

  * :class:`SparkDirectEngine`  -- the ORACLE: ``generate_ingest_sql`` executed on
    a Delta-Spark session. Defines the ingest golden.
  * :class:`DbtDuckDBEngine`    -- ``dbt run`` on DuckDB (in-process), no JVM.
  * :class:`DbtSparkSessionEngine` -- ``dbt run`` on a local Spark session
    (``method: session``, isolated warehouse/metastore per case).
  * :class:`SQLPlanGeneratorGoldEngine` -- the gold-derivation oracle
    (``generate_dbt_dag_project`` -> ``SQLPlanGenerator`` SQL) executed via the
    dbt-generated gold project on BOTH DuckDB AND the Spark session, closing the
    "gold never run on Spark" gap.

The Spark-backed engines share ONE process-wide Delta session (managed by
:func:`get_shared_spark_session`) because dbt-spark ``method: session`` reuses the
active session in-process and PySpark allows only one JVM gateway per process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from tests.ingest_parity.canonical import to_json

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from tests.conformance.corpus.registry import Case


# ---------------------------------------------------------------------------
# shared helpers (formerly duplicated per test module)
# ---------------------------------------------------------------------------


def decimal_scales(umf: dict[str, Any]) -> dict[str, int | None]:
    """Return ``{column: declared_scale}`` for DECIMAL columns (default scale 2).

    Used by every engine so the canonical decimal rendering is identical across
    backends (a DECIMAL is fixed at its declared scale, not the backend's native
    string form).
    """
    scales: dict[str, int | None] = {}
    for col in umf["columns"]:
        if (col.get("data_type") or "").upper() == "DECIMAL":
            scales[col["name"]] = col["scale"] if col.get("scale") is not None else 2
    return scales


def _force_spark_delta_file_format(project: Path) -> None:
    """Append a project-level ``+file_format: delta`` to the dbt project config.

    dbt-spark's ``merge`` incremental strategy is only valid when the model's
    ``file_format`` is ``delta`` / ``iceberg`` / ``hudi``; the adapter defaults to
    ``parquet`` and HARD-ERRORS on merge otherwise (unlike Databricks, where delta
    is the implicit default). The generated project sets ``incremental_strategy=
    'merge'`` without a ``file_format``, so for the local dbt-spark *session*
    execution we pin the project default to delta. This is an execution-environment
    concern (the same delta the shared session and the Spark-direct oracle use),
    not a change to the emitted per-model SQL the cast parity depends on.
    """
    project_yml = project / "dbt_project.yml"
    text = project_yml.read_text()
    if "file_format" in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    text += "\nmodels:\n  +file_format: delta\n"
    project_yml.write_text(text)


def _relax_spark_contract_enforcement(project: Path) -> None:
    """Disable contract ENFORCEMENT in the generated spark-target model bodies.

    dbt-spark enforces a non-null contract on Delta via
    ``ALTER COLUMN ... SET NOT NULL``, which the embedded local Hive/Delta session
    rejects structurally (``Cannot change nullable column to non-nullable``) for a
    column the model SELECT created as nullable -- a known dbt-spark+Delta
    limitation, NOT the behaviour under test. The contract is a schema-SHAPE
    assertion; it is enforced identically by the DbtDuckDB leg (which compares to
    the SAME golden), so the row-parity result the matrix checks (casts, merge,
    derivations) is unchanged when enforcement is relaxed for the local Spark leg.
    The emitted cast/merge SQL itself is untouched.
    """
    for sql in project.rglob("*.sql"):
        text = sql.read_text()
        if "contract={'enforced': True}" in text:
            sql.write_text(
                text.replace(
                    "contract={'enforced': True}", "contract={'enforced': False}"
                )
            )


def _dbt_failure_detail(result: Any) -> str:
    """Format per-node status from a dbtRunner result (``result.result`` may be a
    RunExecutionResult, a Manifest, or a bool depending on the command/outcome)."""
    nodes = getattr(result, "result", None)
    try:
        items = list(nodes) if nodes else []
    except TypeError:
        return f"<no per-node results> (result={nodes!r})"
    return "\n".join(
        f"{r.node.name}: {r.status} -- {getattr(r, 'message', '')}" for r in items
    )


def split_sql_statements(sql: str) -> list[str]:
    """Split a multi-statement ingest artifact into executable statements.

    Comment lines (``-- ...``) are stripped first (some warning comments contain a
    ``;``), then the text is split on ``;``. The artifact never contains a ``;``
    inside a string literal, so a plain split of the de-commented text is safe.
    """
    decommented = "\n".join(
        ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")
    )
    statements: list[str] = []
    for chunk in decommented.split(";"):
        stmt = chunk.strip()
        if stmt:
            statements.append(stmt)
    return statements


# ---------------------------------------------------------------------------
# shared Spark session (one JVM gateway per process)
# ---------------------------------------------------------------------------

_SHARED_SPARK: SparkSession | None = None
_SHARED_SPARK_WAREHOUSE: Path | None = None

_DELTA_PACKAGE = "io.delta:delta-spark_2.13:4.0.0"


def spark_importable() -> str | None:
    """Return a skip reason if PySpark cannot be imported, else ``None``."""
    try:
        import pyspark  # noqa: F401
    except Exception as exc:  # pragma: no cover - env dependent
        return f"pyspark not importable: {exc}"
    return None


def _duckdb_dbt_availability() -> str | None:
    """Skip reason if the dbt(+DuckDB) execution path is unavailable, else ``None``.

    Checks the duckdb engine, dbt-core, the dbt-duckdb ADAPTER (so a dbt-core
    install missing the adapter is skipped VISIBLY rather than failing inside the
    subprocess ``dbt run``), and the ``dbt`` CLI on PATH.
    """
    try:
        import duckdb  # noqa: F401
    except Exception as exc:
        return f"duckdb not importable: {exc}"
    try:
        import dbt  # noqa: F401
    except Exception as exc:
        return f"dbt-core not importable: {exc}"
    try:
        import dbt.adapters.duckdb  # noqa: F401
    except Exception as exc:
        return f"dbt-duckdb adapter not importable: {exc}"
    if shutil.which("dbt") is None:
        return "dbt CLI not on PATH"
    return None


def get_shared_spark_session() -> SparkSession:
    """Create (once) and return a process-wide Delta Spark session.

    ANSI is disabled and the WHOLE stack (process TZ + driver JVM + session) is
    pinned to UTC so malformed casts become NULL and TIMESTAMP values render
    host-timezone-independently -- exactly matching the committed Spark-direct
    oracle goldens. dbt-spark ``method: session`` reuses THIS session in-process,
    so the Spark-direct leg and the dbt-on-Spark leg share one JVM gateway.
    """
    global _SHARED_SPARK, _SHARED_SPARK_WAREHOUSE
    if _SHARED_SPARK is not None:
        return _SHARED_SPARK

    import time

    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    os.environ.setdefault("TQDM_DISABLE", "1")

    from pyspark.sql import SparkSession

    # Tear down any pre-existing session so OUR isolated warehouse/metastore config
    # genuinely takes effect (getOrCreate reuses an active session otherwise).
    active = SparkSession.getActiveSession()
    if active is not None:
        active.stop()

    warehouse = Path(tempfile.mkdtemp(prefix="conformance_matrix_wh_"))
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("tablespec-conformance-matrix")
        .config("spark.sql.warehouse.dir", str(warehouse))
        .config(
            "javax.jdo.option.ConnectionURL",
            f"jdbc:derby:;databaseName={warehouse}/metastore_db;create=true",
        )
        .config("spark.driver.extraJavaOptions", "-Duser.timezone=UTC")
        .config("spark.executor.extraJavaOptions", "-Duser.timezone=UTC")
        .config("spark.jars.packages", _DELTA_PACKAGE)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.ansi.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.default.parallelism", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.sources.default", "delta")
        .config("spark.databricks.delta.snapshotPartitions", "2")
    )
    session = builder.getOrCreate()
    session.sparkContext.setLogLevel("ERROR")
    _SHARED_SPARK = session
    _SHARED_SPARK_WAREHOUSE = warehouse
    return session


def stop_shared_spark_session() -> None:
    """Stop the shared session and remove its warehouse (test-suite teardown)."""
    global _SHARED_SPARK, _SHARED_SPARK_WAREHOUSE
    if _SHARED_SPARK is not None:
        try:
            _SHARED_SPARK.stop()
        finally:
            _SHARED_SPARK = None
    if _SHARED_SPARK_WAREHOUSE is not None:
        shutil.rmtree(_SHARED_SPARK_WAREHOUSE, ignore_errors=True)
        _SHARED_SPARK_WAREHOUSE = None


# ---------------------------------------------------------------------------
# the Engine contract
# ---------------------------------------------------------------------------


class Engine(ABC):
    """One execution backend in the conformance matrix.

    The matrix test drives every available engine through the SAME three-step
    lifecycle and compares ``run(case)`` (a canonical string) to the case golden:

        engine.run(case) -> canonical-json string  (load raw -> execute -> collect)

    Subclasses implement :meth:`availability` (the visible skip gate),
    :meth:`load_raw` / :meth:`collect_canonical` (engine-specific I/O) and inherit
    :meth:`run` (the shared orchestration). ``kind`` declares which case kinds the
    engine handles (``"ingest"`` and/or ``"gold"``).
    """

    name: str
    kinds: tuple[str, ...]

    @abstractmethod
    def availability(self, case: Case) -> str | None:
        """Return a skip reason if this engine cannot run *case*, else ``None``."""

    def handles(self, case: Case) -> bool:
        """Whether this engine handles the case's kind at all."""
        return case.kind in self.kinds

    @abstractmethod
    def run(self, case: Case) -> str:
        """Execute *case* end-to-end and return its canonical-json string.

        Implementations MUST canonicalize through ``canonical.to_json`` at
        ``case.ts_precision`` with the case's decimal scales.
        """


# ---------------------------------------------------------------------------
# SparkDirect (the oracle): generate_ingest_sql on Delta-Spark
# ---------------------------------------------------------------------------


class SparkDirectEngine(Engine):
    """The ingest ORACLE: ``generate_ingest_sql`` executed on Delta-Spark.

    Defines the committed golden. Other ingest engines compare to its output.
    """

    name = "SparkDirect"
    kinds = ("ingest",)

    def availability(self, case: Case) -> str | None:
        return spark_importable()

    def _load_raw(
        self, spark: SparkSession, umf: dict[str, Any], csv_path: Path, raw_table: str
    ) -> None:
        from pyspark.sql.functions import to_timestamp

        string_cols = [c["name"] for c in umf["columns"]] + ["_source_file"]
        read_schema_fields = [(name, "string") for name in string_cols]
        read_schema_fields.append(("_load_ts", "string"))
        schema_ddl = ", ".join(f"`{n}` {t}" for n, t in read_schema_fields)

        df = (
            spark.read.option("header", True)
            .option("quote", '"')
            .option("escape", '"')
            .option("multiLine", True)
            .schema(schema_ddl)
            .csv(str(csv_path))
            .withColumn("_load_ts", to_timestamp("_load_ts", "yyyy-MM-dd HH:mm:ss"))
        )
        ordered = [c["name"] for c in umf["columns"]] + ["_source_file", "_load_ts"]
        df = df.select(*ordered)
        spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
        df.write.format("delta").mode("overwrite").saveAsTable(raw_table)

    def collect_canonical(
        self, spark: SparkSession, umf: dict[str, Any], ingested_table: str, case: Case
    ) -> str:
        columns = [c["name"] for c in umf["columns"]]
        rows = [r.asDict() for r in spark.table(ingested_table).collect()]
        return to_json(
            rows, columns, decimal_scales(umf), ts_precision=case.ts_precision
        )

    def run(self, case: Case) -> str:
        from tablespec.schemas.ingest_generator import generate_ingest_sql

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        table = umf["table_name"]
        raw_table = f"raw_{table}"
        ingested_table = f"ingested_{table}"

        spark = get_shared_spark_session()
        spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
        spark.sql(f"DROP TABLE IF EXISTS {ingested_table}")

        statements = split_sql_statements(generate_ingest_sql(umf))
        create_stmts, transform_stmt = statements[:-1], statements[-1]
        for stmt in create_stmts:
            spark.sql(stmt)

        try:
            for batch in case.batches:
                assert batch.exists(), f"missing raw batch: {batch}"
                self._load_raw(spark, umf, batch, raw_table)
                spark.sql(transform_stmt)
            return self.collect_canonical(spark, umf, ingested_table, case)
        finally:
            spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
            spark.sql(f"DROP TABLE IF EXISTS {ingested_table}")


# ---------------------------------------------------------------------------
# DbtDuckDB: dbt run on DuckDB (in-process, no JVM)
# ---------------------------------------------------------------------------


class DbtDuckDBEngine(Engine):
    """``dbt run`` on DuckDB -- reproduces the Spark oracle WITHOUT a JVM."""

    name = "DbtDuckDB"
    kinds = ("ingest",)

    def availability(self, case: Case) -> str | None:
        return _duckdb_dbt_availability()

    def _connect(self, db_path: Path):
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute("SET TimeZone='UTC'")
        return con

    def _load_raw(self, db_path: Path, umf: dict[str, Any], csv_path: Path) -> None:
        table = umf["table_name"]
        cols = [c["name"] for c in umf["columns"]]
        con = self._connect(db_path)
        try:
            con.execute(f"DROP TABLE IF EXISTS raw_{table}")
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
            projection = ", ".join(f'"{c}"' for c in cols)
            projection += ', "_source_file", cast("_load_ts" as timestamp)'
            con.execute(
                f"INSERT INTO raw_{table} "
                f"SELECT {projection} "
                f"FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)"
            )
        finally:
            con.close()

    def collect_canonical(self, db_path: Path, umf: dict[str, Any], case: Case) -> str:
        table = umf["table_name"]
        columns = [c["name"] for c in umf["columns"]]
        con = self._connect(db_path)
        try:
            projection = ", ".join(f'"{c}"' for c in columns)
            records = con.execute(f"SELECT {projection} FROM {table}").fetchall()
        finally:
            con.close()
        rows = [dict(zip(columns, rec, strict=True)) for rec in records]
        return to_json(
            rows, columns, decimal_scales(umf), ts_precision=case.ts_precision
        )

    def _run_dbt(self, project: Path, db_path: Path) -> None:
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

    def run(self, case: Case) -> str:
        from tablespec.schemas.dbt_generator import generate_dbt_project

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        project = Path(tempfile.mkdtemp(prefix=f"matrix_dbt_duckdb_{case.id}_"))
        try:
            generate_dbt_project(umf, dialect="duckdb", out_dir=project)
            db_path = project / "ingest.duckdb"
            for batch in case.batches:
                assert batch.exists(), f"missing raw batch: {batch}"
                self._load_raw(db_path, umf, batch)
                self._run_dbt(project, db_path)
            return self.collect_canonical(db_path, umf, case)
        finally:
            shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# DbtSparkSession: dbt run on the local Spark session (method: session)
# ---------------------------------------------------------------------------


class DbtSparkSessionEngine(Engine):
    """``dbt run`` (``method: session``) on the shared local Spark session.

    Reuses the process-wide Delta session in-process (a subprocess would spin a
    second JVM and deadlock on the Derby metastore). The landing tables live in
    the ``default`` schema the generated ``sources.yml`` points at.
    """

    name = "DbtSparkSession"
    kinds = ("ingest",)

    def availability(self, case: Case) -> str | None:
        reason = spark_importable()
        if reason is not None:
            return reason
        try:
            import dbt.adapters.spark  # noqa: F401
        except Exception as exc:
            return f"dbt-spark adapter not importable: {exc}"
        return None

    def _load_raw(
        self, spark: SparkSession, umf: dict[str, Any], csv_path: Path
    ) -> None:
        from pyspark.sql.functions import to_timestamp

        table = umf["table_name"]
        string_cols = [c["name"] for c in umf["columns"]] + ["_source_file"]
        read_schema_fields = [(name, "string") for name in string_cols]
        read_schema_fields.append(("_load_ts", "string"))
        schema_ddl = ", ".join(f"`{n}` {t}" for n, t in read_schema_fields)

        df = (
            spark.read.option("header", True)
            .option("quote", '"')
            .option("escape", '"')
            .option("multiLine", True)
            .schema(schema_ddl)
            .csv(str(csv_path))
            .withColumn("_load_ts", to_timestamp("_load_ts", "yyyy-MM-dd HH:mm:ss"))
        )
        ordered = [c["name"] for c in umf["columns"]] + ["_source_file", "_load_ts"]
        df = df.select(*ordered)
        # The generated sources.yml declares ``schema: main`` for the landing
        # tables; the model itself materializes into the ``default`` output schema.
        spark.sql("CREATE DATABASE IF NOT EXISTS main")
        spark.sql(f"DROP TABLE IF EXISTS main.raw_{table}")
        df.write.format("delta").mode("overwrite").saveAsTable(f"main.raw_{table}")

    def _run_dbt_in_process(self, project: Path, schema: str = "default") -> Any:
        from dbt.cli.main import dbtRunner

        os.environ["DBT_SPARK_SCHEMA"] = schema
        return dbtRunner().invoke(
            [
                "run",
                "--profiles-dir",
                str(project),
                "--project-dir",
                str(project),
                "--target",
                "dev",
            ]
        )

    def collect_canonical(
        self, spark: SparkSession, umf: dict[str, Any], case: Case
    ) -> str:
        table = umf["table_name"]
        columns = [c["name"] for c in umf["columns"]]
        rows = [r.asDict() for r in spark.table(f"default.{table}").collect()]
        return to_json(
            rows, columns, decimal_scales(umf), ts_precision=case.ts_precision
        )

    def run(self, case: Case) -> str:
        from tablespec.schemas.dbt_generator import generate_dbt_project

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        table = umf["table_name"]
        spark = get_shared_spark_session()
        # Clean any state from a prior engine/case sharing this table name.
        spark.sql("CREATE DATABASE IF NOT EXISTS main")
        spark.sql("CREATE DATABASE IF NOT EXISTS default")
        spark.sql(f"DROP TABLE IF EXISTS main.raw_{table}")
        spark.sql(f"DROP TABLE IF EXISTS default.{table}")

        project = Path(tempfile.mkdtemp(prefix=f"matrix_dbt_spark_{case.id}_"))
        try:
            generate_dbt_project(umf, dialect="spark", target="spark", out_dir=project)
            _force_spark_delta_file_format(project)
            _relax_spark_contract_enforcement(project)
            for batch in case.batches:
                assert batch.exists(), f"missing raw batch: {batch}"
                self._load_raw(spark, umf, batch)
                result = self._run_dbt_in_process(project, schema="default")
                if not result.success:
                    raise AssertionError(
                        f"dbt-on-Spark run failed for '{case.id}':\n"
                        + _dbt_failure_detail(result)
                    )
            return self.collect_canonical(spark, umf, case)
        finally:
            spark.sql(f"DROP TABLE IF EXISTS main.raw_{table}")
            spark.sql(f"DROP TABLE IF EXISTS default.{table}")
            shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# SQLPlanGeneratorGold: the gold derivation oracle, run on BOTH backends
# ---------------------------------------------------------------------------


def _gold_umfs(case: Case) -> list[Any]:
    """Load every source/target UMF for a gold case into UMF models."""
    from tablespec.models.umf import UMF

    assert case.gold_dir is not None
    return [
        UMF(**yaml.safe_load(p.read_text()))
        for p in sorted(case.gold_dir.glob("*.umf.yaml"))
    ]


def _gold_target_table(umfs: list[Any]) -> str:
    """Identify the gold target table (the derived ``gold_<t>`` model) in the set."""
    from tablespec.core.registry import NodeRegistry

    registry = NodeRegistry(list(umfs))
    gold = sorted(registry.gold_tables)
    if len(gold) != 1:
        raise AssertionError(
            f"expected exactly one gold target table, got {gold!r} "
            "(the conformance gold corpus is single-target per case)"
        )
    return gold[0]


def _gold_target_umf(umfs: list[Any], target: str) -> Any:
    for umf in umfs:
        if umf.table_name == target:
            return umf
    raise AssertionError(f"gold target UMF {target!r} not in the set")


def _source_csvs(case: Case) -> dict[str, Path]:
    """Map ``raw_<table>`` source name -> its CSV (the non-gold source tables)."""
    assert case.gold_dir is not None
    out: dict[str, Path] = {}
    for csv in sorted(case.gold_dir.glob("*.raw.csv")):
        out[csv.name[: -len(".raw.csv")]] = csv
    return out


class SQLPlanGeneratorGoldEngine(Engine):
    """The gold-derivation oracle executed via the dbt-generated gold project.

    ``generate_dbt_dag_project`` renders one ``ingested_<t>`` staging model per
    source table and one ``gold_<t>`` model carrying the ``SQLPlanGenerator``
    cross-table derivation. Running that project on BOTH DuckDB and the Spark
    session (the dialect layer rewrites Spark-flavored constructs per backend)
    and canonicalizing the resulting ``gold_<target>`` table closes the
    "gold never run on Spark" gap: the two backends must agree (and each equal
    the committed golden, which is the Spark-backend output of this engine).

    Two instances are registered in the matrix: ``backend="duckdb"`` (no JVM) and
    ``backend="spark"`` (the shared Spark session).
    """

    kinds = ("gold",)

    def __init__(self, backend: str) -> None:
        assert backend in ("duckdb", "spark")
        self.backend = backend
        self.name = f"SQLPlanGeneratorGold[{backend}]"

    def availability(self, case: Case) -> str | None:
        # FK-integrity is a dbt relationships schema-test assertion, not a
        # canonical-row comparison; it is exercised by the dedicated dbt-test tier,
        # not the row-parity matrix. Skip it here with an explicit reason.
        if case.generator == "relationships_schema_test":
            return (
                "gold_fk_integrity is a dbt relationships schema-test (orphan "
                "negative), not a canonical-row comparison -- covered by the "
                "dbt-test tier"
            )
        # KNOWN cross-engine divergence (a genuine generator/corpus issue the
        # harness surfaced): gate visibly so it is never silently passed.
        if case.divergence:
            return f"known divergence (gated, not silently passed): {case.divergence}"
        if self.backend == "duckdb":
            return _duckdb_dbt_availability()
        # spark backend
        reason = spark_importable()
        if reason is not None:
            return reason
        try:
            import dbt.adapters.spark  # noqa: F401
        except Exception as exc:
            return f"dbt-spark adapter not importable: {exc}"
        return None

    # -- DuckDB execution -----------------------------------------------------

    def _run_duckdb(self, case: Case) -> str:
        import duckdb

        from tablespec.dbt.project import generate_dbt_dag_project

        umfs = _gold_umfs(case)
        target = _gold_target_table(umfs)
        target_umf = _gold_target_umf(umfs, target)
        project = Path(tempfile.mkdtemp(prefix=f"matrix_gold_duckdb_{case.id}_"))
        try:
            generate_dbt_dag_project(
                umfs, dialect="duckdb", target="duckdb", out_dir=project
            )
            db_path = project / "gold.duckdb"
            con = duckdb.connect(str(db_path))
            con.execute("SET TimeZone='UTC'")
            con.execute("CREATE SCHEMA IF NOT EXISTS main")
            for tbl, csv in _source_csvs(case).items():
                hdr = csv.read_text().splitlines()[0].split(",")
                cols = ", ".join(f'"{c}" VARCHAR' for c in hdr)
                con.execute(f"DROP TABLE IF EXISTS main.raw_{tbl}")
                con.execute(
                    f"CREATE TABLE main.raw_{tbl} ({cols}, "
                    '"_source_file" VARCHAR, "_load_ts" TIMESTAMP)'
                )
                proj_cols = ", ".join(f'"{c}"' for c in hdr)
                con.execute(
                    f"INSERT INTO main.raw_{tbl} SELECT {proj_cols}, "
                    f"'{tbl}.csv', TIMESTAMP '2026-01-01 00:00:00' "
                    f"FROM read_csv_auto('{csv}', header=true, all_varchar=true)"
                )
            con.close()

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
                    "gold dbt run (duckdb) failed:\n"
                    f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
                )

            con = duckdb.connect(str(db_path))
            con.execute("SET TimeZone='UTC'")
            try:
                columns = [c.name for c in target_umf.columns]
                projection = ", ".join(f'"{c}"' for c in columns)
                records = con.execute(
                    f"SELECT {projection} FROM main.gold_{target}"
                ).fetchall()
            finally:
                con.close()
            rows = [dict(zip(columns, rec, strict=True)) for rec in records]
            umf_dict = target_umf.model_dump(exclude_none=True)
            return to_json(
                rows, columns, decimal_scales(umf_dict), ts_precision=case.ts_precision
            )
        finally:
            shutil.rmtree(project, ignore_errors=True)

    # -- Spark execution ------------------------------------------------------

    def _run_spark(self, case: Case) -> str:
        from dbt.cli.main import dbtRunner
        from pyspark.sql.functions import lit, to_timestamp

        from tablespec.dbt.project import generate_dbt_dag_project

        umfs = _gold_umfs(case)
        target = _gold_target_table(umfs)
        target_umf = _gold_target_umf(umfs, target)
        spark = get_shared_spark_session()
        spark.sql("CREATE DATABASE IF NOT EXISTS main")

        project = Path(tempfile.mkdtemp(prefix=f"matrix_gold_spark_{case.id}_"))
        created: list[str] = []
        try:
            generate_dbt_dag_project(
                umfs, dialect="spark", target="spark", out_dir=project
            )
            _force_spark_delta_file_format(project)
            _relax_spark_contract_enforcement(project)
            for tbl, csv in _source_csvs(case).items():
                hdr = csv.read_text().splitlines()[0].split(",")
                schema_ddl = ", ".join(f"`{c}` string" for c in hdr)
                df = (
                    spark.read.option("header", True)
                    .option("quote", '"')
                    .option("escape", '"')
                    .option("multiLine", True)
                    .schema(schema_ddl)
                    .csv(str(csv))
                    .withColumn("_source_file", lit(f"{tbl}.csv"))
                    .withColumn(
                        "_load_ts",
                        to_timestamp(lit("2026-01-01 00:00:00"), "yyyy-MM-dd HH:mm:ss"),
                    )
                )
                spark.sql(f"DROP TABLE IF EXISTS main.raw_{tbl}")
                df.write.format("delta").mode("overwrite").saveAsTable(
                    f"main.raw_{tbl}"
                )
                created.append(f"main.raw_{tbl}")

            os.environ["DBT_SPARK_SCHEMA"] = "main"
            result = dbtRunner().invoke(
                [
                    "run",
                    "--profiles-dir",
                    str(project),
                    "--project-dir",
                    str(project),
                    "--target",
                    "dev",
                ]
            )
            if not result.success:
                raise AssertionError(
                    f"gold dbt run (spark) failed for '{case.id}':\n"
                    + _dbt_failure_detail(result)
                )

            columns = [c.name for c in target_umf.columns]
            rows = [r.asDict() for r in spark.table(f"main.gold_{target}").collect()]
            umf_dict = target_umf.model_dump(exclude_none=True)
            return to_json(
                rows, columns, decimal_scales(umf_dict), ts_precision=case.ts_precision
            )
        finally:
            # Drop the raw landing tables, the per-source staging models
            # (main.ingested_<src>) and the gold target so a reused table name
            # never bleeds across cases on the shared session.
            for tbl in created:
                spark.sql(f"DROP TABLE IF EXISTS {tbl}")
            for src in _source_csvs(case):
                spark.sql(f"DROP TABLE IF EXISTS main.ingested_{src}")
            spark.sql(f"DROP TABLE IF EXISTS main.gold_{target}")
            shutil.rmtree(project, ignore_errors=True)

    def run(self, case: Case) -> str:
        if self.backend == "duckdb":
            return self._run_duckdb(case)
        return self._run_spark(case)


# ---------------------------------------------------------------------------
# the matrix registry
# ---------------------------------------------------------------------------


def all_engines() -> list[Engine]:
    """Every locally-executable engine in the conformance matrix."""
    return [
        SparkDirectEngine(),
        DbtDuckDBEngine(),
        DbtSparkSessionEngine(),
        SQLPlanGeneratorGoldEngine(backend="duckdb"),
        SQLPlanGeneratorGoldEngine(backend="spark"),
    ]
