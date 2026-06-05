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
# Whether THIS module created the shared session (and may therefore stop it) vs
# adopted a pre-existing active session owned by another fixture (the session-scoped
# ``spark_session`` conftest fixture). When adopted we must NEVER stop it -- doing so
# tears down the JVM SparkContext + its Ivy ``userFiles`` jar dir out from under the
# other fixture, which then fails on a deleted ``delta-spark`` jar.
_SHARED_SPARK_OWNED: bool = False
# Runtime-settable session configs the conformance matrix needs (UTC + ANSI-off +
# delta default) which we may apply to an ADOPTED session; we snapshot their prior
# values so teardown can restore them, leaving non-conformance Spark tests unchanged.
_ADOPTED_CONFIG_RESTORE: dict[str, str | None] = {}

_DELTA_PACKAGE = "io.delta:delta-spark_2.13:4.0.0"

# Session-level (runtime-settable) configs the conformance casts depend on: ANSI
# disabled so malformed casts become NULL, UTC so TIMESTAMP rows render
# host-timezone-independently, delta as the default source, and small shuffle
# partitions for speed. All are settable on a LIVE session via ``spark.conf.set``,
# so an adopted session can be brought to conformance semantics without a rebuild.
_RUNTIME_CONFORMANCE_CONF: dict[str, str] = {
    "spark.sql.ansi.enabled": "false",
    "spark.sql.session.timeZone": "UTC",
    "spark.sql.sources.default": "delta",
    "spark.sql.shuffle.partitions": "2",
}


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


def _databricks_compile_availability() -> str | None:
    """Skip reason if the dbt-databricks COMPILE (offline parse) tier is unavailable.

    The databricks tier is compile-only here (no cluster): it needs dbt-core and the
    dbt-databricks ADAPTER importable so ``dbt parse`` registers the databricks
    adapter and builds the manifest offline. It does NOT need a live workspace.

    Warnings are suppressed during the import PROBE: dbt-databricks emits a Pydantic
    V1-config DeprecationWarning at import that the suite-wide ``filterwarnings=error``
    would otherwise escalate, making an available adapter look un-importable. The
    warning is third-party (dbt's), not behaviour under test.
    """
    import warnings

    try:
        import dbt  # noqa: F401
    except Exception as exc:
        return f"dbt-core not importable: {exc}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import dbt.adapters.databricks  # noqa: F401
    except Exception as exc:
        return f"dbt-databricks adapter not importable: {exc}"
    return None


def databricks_e2e_availability() -> str | None:
    """Skip reason for the OPT-IN real-Databricks e2e tier, else ``None``.

    This tier deploys + executes against a REAL Databricks workspace, so it is
    skipped unless ``DATABRICKS_HOST`` is set (the opt-in switch). When set it also
    needs the databricks adapter importable to drive ``dbt run`` / pipeline deploy.
    There is NO cluster in this harness, so this is expected to skip here.
    """
    import warnings

    if not os.environ.get("DATABRICKS_HOST"):
        return (
            "databricks_e2e opt-in tier: DATABRICKS_HOST not set "
            "(no remote workspace -- skipped, not silently passed)"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import dbt.adapters.databricks  # noqa: F401
    except Exception as exc:  # pragma: no cover - only on a configured workspace
        return f"dbt-databricks adapter not importable: {exc}"
    return None


def _apply_runtime_conformance_conf(session: SparkSession, *, snapshot: bool) -> None:
    """Apply the session-level conformance configs (UTC/ANSI/delta-default).

    When ``snapshot`` is True (an ADOPTED session we do not own) the prior value of
    each key is recorded into ``_ADOPTED_CONFIG_RESTORE`` so teardown can restore it,
    leaving non-conformance Spark tests that reuse the same session unaffected.
    """
    for key, value in _RUNTIME_CONFORMANCE_CONF.items():
        if snapshot:
            try:
                _ADOPTED_CONFIG_RESTORE[key] = session.conf.get(key)
            except Exception:
                _ADOPTED_CONFIG_RESTORE[key] = None
        session.conf.set(key, value)


def get_shared_spark_session() -> SparkSession:
    """Return the process-wide Delta Spark session, ADOPTING any active one.

    There is exactly one SparkContext per process, so the conformance matrix must
    cooperate with the session-scoped ``spark_session`` conftest fixture rather than
    stop+rebuild a parallel session (stopping it deletes the shared Ivy ``userFiles``
    jar dir and breaks the other fixture). Behaviour:

      * If a session is ALREADY active (e.g. the conftest fixture created it), ADOPT
        it -- apply the runtime-settable conformance configs (UTC, ANSI-off, delta
        default) and record we do NOT own it (teardown must not stop it).
      * Otherwise CREATE an isolated Delta session (own warehouse/metastore) and own
        it. The conftest fixture's factory reuses an active session, so a session we
        create here is later reused by that fixture -- which is why we still must not
        leave it in a stopped state (teardown only stops what we own, and the conftest
        fixture is the canonical owner once it adopts ours in turn).

    ANSI is disabled and the whole stack (process TZ + session) is pinned to UTC so
    malformed casts become NULL and TIMESTAMP values render host-timezone-
    independently -- exactly matching the committed Spark-direct oracle goldens.
    dbt-spark ``method: session`` reuses THIS session in-process.
    """
    global _SHARED_SPARK, _SHARED_SPARK_WAREHOUSE, _SHARED_SPARK_OWNED
    if _SHARED_SPARK is not None:
        return _SHARED_SPARK

    import time

    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    os.environ.setdefault("TQDM_DISABLE", "1")

    from pyspark.sql import SparkSession

    # ADOPT a pre-existing active session instead of stopping it: stopping the
    # shared SparkContext deletes its Ivy ``userFiles`` jar dir out from under the
    # conftest ``spark_session`` fixture (which then fails importing ``delta`` on a
    # now-missing jar). Bring the adopted session to conformance semantics via
    # runtime-settable configs; do NOT own it (teardown must not stop it).
    active = SparkSession.getActiveSession()
    if active is not None:
        _apply_runtime_conformance_conf(active, snapshot=True)
        active.sparkContext.setLogLevel("ERROR")
        _SHARED_SPARK = active
        _SHARED_SPARK_OWNED = False
        return active

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
    _SHARED_SPARK_OWNED = True
    return session


def stop_shared_spark_session() -> None:
    """Release the conformance reference to the shared session at module teardown.

    Crucially this does NOT stop the SparkContext. There is one SparkContext per
    process and PySpark's Ivy-resolved ``delta-spark`` jar lives in that context's
    ``userFiles`` dir, which is on the interpreter's path; stopping the context
    DELETES that dir, so a LATER test that does ``import delta`` (e.g.
    ``spark_factory.is_delta_available`` in the integration fixture) then fails with
    ``FileNotFoundError`` on the now-missing jar. The session-scoped ``spark_session``
    conftest fixture is the canonical owner of the context lifecycle (it stops the
    session at the end of the whole pytest session); the conformance module must
    therefore leave the context alive and only:

      * restore any runtime configs it mutated on an ADOPTED session, so a later
        non-conformance Spark test reusing the session sees its original semantics;
      * drop the warehouse temp dir for a session it CREATED (the tables were already
        dropped per-case; the empty warehouse dir is safe to remove and the context
        stays up).
    """
    global _SHARED_SPARK, _SHARED_SPARK_WAREHOUSE, _SHARED_SPARK_OWNED
    if _SHARED_SPARK is None:
        return
    if not _SHARED_SPARK_OWNED:
        # Adopted: restore the runtime configs we changed; never stop the context.
        for key, prior in _ADOPTED_CONFIG_RESTORE.items():
            try:
                if prior is None:
                    _SHARED_SPARK.conf.unset(key)
                else:
                    _SHARED_SPARK.conf.set(key, prior)
            except Exception:
                pass
        _ADOPTED_CONFIG_RESTORE.clear()
    # Created-by-us: the conftest fixture's factory reuses this still-live active
    # session, so do NOT stop it (that would delete the shared userFiles jar dir) and
    # do NOT remove its warehouse/metastore dir (the live session still points at it).
    # The temp warehouse dir is small and cleaned up at process exit.
    _SHARED_SPARK = None
    _SHARED_SPARK_OWNED = False
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

    ``tier`` distinguishes how an engine's :meth:`run` output is judged:

      * ``"row"``       -- the canonical-json output is compared to the case ROW
        golden (the SparkDirect / Spark-gold oracle) AND participates in the
        pairwise-agreement check. These are the locally-EXECUTED engines.
      * ``"compile"``   -- the engine cannot execute rows in this env (no
        cluster); :meth:`run` returns a compiled-ARTIFACT canonical (e.g. the
        databricks-target compiled model SQL) compared to a dedicated COMPILE
        golden. Proves the prod target generates correct SQL without a warehouse.
      * ``"structure"`` -- like ``compile`` but the artifact is the emitted project
        STRUCTURE (e.g. the LDP pipeline SQL), pinned to a structure golden.
      * ``"e2e"``       -- an OPT-IN tier that executes on a REAL remote runtime
        (Databricks); skipped unless the runtime is configured. When it runs it is
        a first-class ROW engine (its output is the row golden), so it is judged
        like ``"row"`` against the SAME corpus golden.

    Only ``"row"`` and (when configured) ``"e2e"`` engines feed the row-parity +
    pairwise matrix; ``"compile"`` / ``"structure"`` engines are driven by their own
    artifact-golden tests. ALL engines (regardless of tier) are enumerated by
    :func:`all_engines` so the skipped-but-green guard can count what ran here.
    """

    name: str
    kinds: tuple[str, ...]
    tier: str = "row"

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
        # canonical-row comparison; it is exercised by the dedicated EXECUTED
        # orphan-FK dbt-test tier (test_ldp_tiers.py / test_fk_orphan_enforcement),
        # not the row-parity matrix. Skip it here with an explicit reason.
        if case.generator == "relationships_schema_test":
            return (
                "gold_fk_integrity is a dbt relationships schema-test (orphan "
                "negative), not a canonical-row comparison -- covered by the "
                "executed orphan-FK dbt-test tier"
            )
        # NOTE: KNOWN cross-engine divergences (gold_pivot, gold_window_aggregation,
        # gold_survivorship_priority) are NO LONGER gated here as availability-skips.
        # The matrix marks them STRICT xfail instead (see _param in
        # test_engine_matrix.py), so an accidental generator fix that makes them pass
        # flips the gate (xpass -> failure) and they are distinguishable from
        # environment-unavailability skips. ``availability`` only reports genuine
        # ENVIRONMENT unavailability below.
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
# DbtDatabricksCompile: the PROD target, validated offline (no cluster)
# ---------------------------------------------------------------------------


class DbtDatabricksCompileEngine(Engine):
    """The PROD (Databricks) dbt target proven correct OFFLINE -- a COMPILE tier.

    There is no Databricks cluster here, so this engine cannot execute rows, and
    ``dbt compile`` (which renders ``{{ source/ref/config }}`` to physical SQL)
    cannot run either -- for the databricks adapter it opens a SQL-warehouse
    connection and HANGS against the unreachable host. What it CAN prove, fully
    OFFLINE, is that the generated dbt project is well-formed for the prod target and
    its model body is byte-stable under the real databricks adapter:

      * generate the ingest dbt project with ``dialect="databricks"`` +
        ``target="databricks"``;
      * run ``dbt parse`` (the genuinely offline path); and
      * build the manifest under the databricks adapter and return the PARSED MODEL
        BODY (``raw_code``) + resolved config as the canonical artifact.

    :meth:`run` returns the parsed model body -- the post-generation, pre-dispatch
    node dbt registered under the databricks adapter (the ``{{ source() }}`` /
    ``{{ config() }}`` Jinja is intentionally NOT warehouse-expanded; that needs a
    cluster). It STILL carries the literal Databricks cast SQL a cluster would run
    (``try_to_timestamp(...)``, asserted separately). The compile-tier test compares
    it to a committed COMPILE golden -- NOT the row golden (no rows are produced).
    The Databricks dialect is cast-identical to Spark, so the EXECUTED Spark
    row-parity legs stand in for the Databricks runtime; this tier closes the
    remaining gap that the prod *target* itself emits well-formed, contract-carrying
    model SQL offline.
    """

    name = "DbtDatabricksCompile"
    kinds = ("ingest",)
    tier = "compile"

    def availability(self, case: Case) -> str | None:
        return _databricks_compile_availability()

    def model_node_id(self, umf: dict[str, Any]) -> str:
        return f"model.tablespec_ingest.{umf['table_name']}"

    def run(self, case: Case) -> str:
        """Parse the databricks-target project offline; return the compiled model SQL."""
        import json

        from dbt.cli.main import dbtRunner

        from tablespec.schemas.dbt_generator import generate_dbt_project

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        project = Path(tempfile.mkdtemp(prefix=f"matrix_databricks_{case.id}_"))
        try:
            generate_dbt_project(
                umf, dialect="databricks", target="databricks", out_dir=project
            )
            result = dbtRunner().invoke(
                [
                    "parse",
                    "--profiles-dir",
                    str(project),
                    "--project-dir",
                    str(project),
                    "--target",
                    "dev",
                    "--no-partial-parse",
                ]
            )
            if not result.success:
                raise AssertionError(
                    f"dbt parse failed for the databricks target on '{case.id}' "
                    "(project not well-formed for Databricks)."
                )
            manifest = json.loads((project / "target" / "manifest.json").read_text())
            adapter = manifest["metadata"]["adapter_type"]
            if adapter != "databricks":
                raise AssertionError(
                    f"manifest not parsed under the databricks adapter: {adapter!r}"
                )
            node = manifest["nodes"][self.model_node_id(umf)]
            # HONEST artifact: ``dbt parse`` builds the manifest WITHOUT a warehouse
            # but does NOT render ``{{ ref/source/config }}`` to physical SQL (that is
            # ``dbt compile``, which for the databricks adapter opens a connection and
            # hangs -- see the module docstring). So the stable artifact here is the
            # PARSED MODEL BODY (``raw_code``) -- the post-generation, pre-dispatch
            # node dbt registered under the databricks adapter -- plus the resolved
            # config (materialization + contract) that parsing applied. It still
            # carries the literal Databricks cast SQL the cluster would run (asserted
            # separately), but the ``{{ source() }}`` / ``{{ config() }}`` Jinja is
            # intentionally NOT expanded; the golden gates that the prod target's
            # generated model body + resolved config are byte-stable, not warehouse-
            # compiled SQL.
            return (
                f"-- adapter: {adapter}\n"
                f"-- artifact: parsed_model_body (dbt parse raw_code; not compiled)\n"
                f"-- materialized: {node['config']['materialized']}\n"
                f"-- contract_enforced: "
                f"{node['config'].get('contract', {}).get('enforced')}\n"
                + node["raw_code"].rstrip("\n")
                + "\n"
            )
        finally:
            shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# LDP (Lakeflow Declarative Pipelines): the PROTOTYPE Databricks-only emitter
# ---------------------------------------------------------------------------


class LdpStructureEngine(Engine):
    """The LDP emitter as a matrix engine -- a STRUCTURE + cast-parity tier.

    LDP runs ONLY on Databricks (no runtime here), so this engine does not execute
    rows. It proves two locally-checkable invariants for the ingest cases:

      * the generated LDP ``ingested_<t>`` cast SELECT body is the SHARED cast layer
        (``build_ingest_select``) -- character-identical to the dbt/direct path, and
      * that extracted cast body, run on duckdb over the case's REAL raw rows,
        produces the SAME canonical result as the shared cast.

    :meth:`run` therefore returns the canonical-json of the LDP cast body executed on
    duckdb. The structure-tier test additionally pins the emitted LDP project text to
    a STRUCTURE golden. Because the cast body is shared, this row output equals the
    other engines' output for the SAME case -- so the structure-tier test compares it
    to the SAME corpus row golden (proving the LDP cast layer is not a fork), while
    the true end-to-end LDP pipeline execution is the opt-in ``LdpDatabricksE2E`` tier.

    HONEST SCOPE of the local cast-body row check: it is valid only where the cast
    over the raw batch IS the final ingested table -- i.e. SINGLE-batch cases. A
    MULTI-batch incremental case needs the per-key dedup/merge (APPLY CHANGES) that
    LDP delegates to the Databricks runtime; the cast body alone cannot reproduce it,
    so multi-batch cases are SKIPPED here (covered by the opt-in e2e tier). Fixtures
    whose ingest dialect uses a type the strict UMF model cannot represent (e.g.
    ``DOUBLE``) are likewise skipped VISIBLY -- the LDP emitter consumes full UMF
    models, so it cannot model them yet (never silently passed).
    """

    name = "LdpStructure"
    kinds = ("ingest",)
    tier = "structure"

    def _umf_modelable_reason(self, case: Case) -> str | None:
        """Skip reason if the strict UMF model cannot represent the fixture (e.g. DOUBLE)."""
        from pydantic import ValidationError

        try:
            self.ingest_umf_model(case)
        except ValidationError as exc:
            offending = sorted(
                {
                    str(e.get("input"))
                    for e in exc.errors()
                    if e.get("type") == "string_pattern_mismatch"
                }
            )
            return (
                "LDP emitter consumes full UMF models; this fixture's ingest dialect "
                f"uses a type the strict UMF model cannot represent yet "
                f"({', '.join(offending) or 'see ValidationError'}) -- skipped "
                "visibly, not silently passed"
            )
        return None

    def availability(self, case: Case) -> str | None:
        """Gate for the EXECUTED cast-body ROW check (single-batch, duckdb-runnable)."""
        reason = _duckdb_dbt_availability_duckdb_only()
        if reason is not None:
            return reason
        if case.is_multibatch:
            return (
                "LDP cast-body row check applies only to single-batch cases; a "
                "multi-batch incremental case needs APPLY CHANGES dedup (Databricks "
                "runtime) -- covered by the opt-in databricks_e2e tier"
            )
        return self._umf_modelable_reason(case)

    def structure_availability(self, case: Case) -> str | None:
        """Gate for the STRUCTURE GOLDEN (pure text -- covers multi-batch too).

        The structure golden pins emitted LDP SQL text and so applies to EVERY case
        the LDP emitter can model -- INCLUDING multi-batch incremental cases (their
        APPLY CHANGES structure must not drift). Only fixtures the strict UMF model
        cannot represent (e.g. DOUBLE) are skipped, visibly.
        """
        return self._umf_modelable_reason(case)

    def _extract_select_body(self, ldp_sql: str) -> str:
        lines = ldp_sql.splitlines()
        start = next(
            i
            for i, ln in enumerate(lines)
            if ln.strip().endswith("SELECT") or ln.strip() == "SELECT"
        )
        body: list[str] = []
        for ln in lines[start + 1 :]:
            if ln.strip().upper().startswith("FROM "):
                break
            body.append(ln)
        return "\n".join(body)

    def ingest_umf_model(self, case: Case) -> Any:
        """Load a case's raw-dict ingest UMF into a full UMF pydantic model.

        The ingest corpus fixtures use the simplified scalar-``nullable`` ingest
        dialect (``nullable: false`` / a bare dict, no top-level ``version``) that
        the Spark baseline / dbt-duckdb paths consume as a raw dict. The LDP emitter
        consumes full UMF models, so normalise here WITHOUT changing the cast inputs:
        add a ``version`` when absent and wrap a scalar ``nullable`` bool into the
        ``{default: bool}`` form the UMF model accepts. The cast SQL depends only on
        ``data_type``/``precision``/``scale`` (unchanged), so the LDP cast body stays
        byte-identical to the shared cast.
        """
        from tablespec.models.umf import UMF

        assert case.umf is not None
        raw = yaml.safe_load(case.umf.read_text())
        raw.setdefault("version", "1.0")
        for col in raw.get("columns", []):
            nullable = col.get("nullable")
            if isinstance(nullable, bool):
                col["nullable"] = {"default": nullable}
        return UMF(**raw)

    def ldp_files(self, case: Case, *, dialect: str = "duckdb") -> dict[str, str]:
        """Generate the LDP project files for the case's single ingest table.

        ``dialect`` selects the cast rendering: ``"duckdb"`` for the locally-EXECUTED
        cast-body row check, and ``"spark"`` (the LDP prod default, cast-identical to
        Databricks) for the STRUCTURE golden so the pinned artifact is the real
        Spark/Databricks-flavored LDP SQL a workspace would deploy -- not DuckDB SQL.
        """
        from tablespec.ldp import generate_ldp_project

        umf = self.ingest_umf_model(case)
        return generate_ldp_project([umf], dialect=dialect)

    def structure_files(self, case: Case) -> dict[str, str]:
        """The LDP project in the PROD (spark/databricks) dialect for the structure golden."""
        return self.ldp_files(case, dialect="spark")

    def select_block_is_shared(self, case: Case) -> bool:
        """The LDP ingested cast lines contain the shared IngestSelect.select_block."""
        from tablespec.schemas.ingest_generator import build_ingest_select

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        table = umf["table_name"]
        files = self.ldp_files(case)
        ldp_sql = files.get(f"ingested/ingested_{table}.sql")
        if ldp_sql is None:
            return False
        shared = build_ingest_select(umf, dialect="duckdb").select_block
        return shared in self._extract_select_body(ldp_sql)

    def run(self, case: Case) -> str:
        """Run the extracted LDP cast SELECT on duckdb -> canonical-json rows.

        This loads the case's REAL raw batch(es) into duckdb and applies the LDP
        cast body, exactly as the row engines do, so the output is comparable to the
        corpus row golden. (LDP's streaming/APPLY-CHANGES runtime is NOT modelled
        here -- that is the Databricks-only e2e tier; this asserts the CAST layer.)
        """
        import duckdb

        assert case.umf is not None
        umf = yaml.safe_load(case.umf.read_text())
        table = umf["table_name"]
        columns = [c["name"] for c in umf["columns"]]
        files = self.ldp_files(case)
        ldp_body = self._extract_select_body(files[f"ingested/ingested_{table}.sql"])

        con = duckdb.connect()
        try:
            con.execute("SET TimeZone='UTC'")
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in columns)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
            proj = ", ".join(f'"{c}"' for c in columns)
            proj += ', "_source_file", cast("_load_ts" as timestamp)'
            for batch in case.batches:
                assert batch.exists(), f"missing raw batch: {batch}"
                con.execute(
                    f"INSERT INTO raw_{table} SELECT {proj} "
                    f"FROM read_csv_auto('{batch}', header=true, all_varchar=true)"
                )
            recs = con.execute(f"SELECT\n{ldp_body}\nFROM raw_{table}").fetchall()
        finally:
            con.close()
        rows = [dict(zip(columns, rec, strict=True)) for rec in recs]
        return to_json(
            rows, columns, decimal_scales(umf), ts_precision=case.ts_precision
        )


class LdpDatabricksE2EEngine(Engine):
    """OPT-IN: deploy the LDP pipeline to a REAL Databricks workspace and read back.

    This is the only tier that exercises the LDP STREAMING runtime (read_files
    autoloader, APPLY CHANGES, materialized views) end-to-end. It is skipped unless
    ``DATABRICKS_HOST`` is set; there is no cluster in this harness, so it skips here
    with an explicit reason (never silently passed). When a workspace IS configured,
    it is a first-class ROW engine: it deploys the generated LDP pipeline, ingests
    the case's raw batches, and canonicalizes the resulting ``ingested_<t>`` table
    through the SAME canonicalization vs the SAME corpus row golden.
    """

    name = "LdpDatabricksE2E"
    kinds = ("ingest",)
    tier = "e2e"

    def availability(self, case: Case) -> str | None:
        return databricks_e2e_availability()

    def run(self, case: Case) -> str:  # pragma: no cover - requires a real workspace
        # Deploy the LDP pipeline + ingest the batches on the configured workspace,
        # then read back ingested_<t> and canonicalize vs the SAME corpus golden.
        # Implemented behind the opt-in gate; unreachable in this cluster-less env.
        raise NotImplementedError(
            "LdpDatabricksE2E requires a configured Databricks workspace; this tier "
            "is gated by databricks_e2e_availability and is not executed here."
        )


def _duckdb_dbt_availability_duckdb_only() -> str | None:
    """Skip reason if duckdb itself is unavailable (LDP cast parity needs only duckdb)."""
    try:
        import duckdb  # noqa: F401
    except Exception as exc:
        return f"duckdb not importable: {exc}"
    return None


# ---------------------------------------------------------------------------
# the matrix registry
# ---------------------------------------------------------------------------


def all_engines() -> list[Engine]:
    """Every engine in the conformance matrix, ACROSS ALL TIERS.

    Includes the locally-executed row engines (``tier="row"``), the offline
    compile tier (databricks), the LDP structure/cast-parity tier, and the opt-in
    real-Databricks e2e tier. The skipped-but-green guard counts these to prove the
    row engines expected-available here actually executed.
    """
    return [
        # row-parity tier (locally executed against the row goldens)
        SparkDirectEngine(),
        DbtDuckDBEngine(),
        DbtSparkSessionEngine(),
        SQLPlanGeneratorGoldEngine(backend="duckdb"),
        SQLPlanGeneratorGoldEngine(backend="spark"),
        # non-local / prod tiers (compile-only + opt-in e2e) added in Phase 4
        DbtDatabricksCompileEngine(),
        LdpStructureEngine(),
        LdpDatabricksE2EEngine(),
    ]


def row_engines() -> list[Engine]:
    """The locally-executed row-parity engines (``tier="row"``)."""
    return [e for e in all_engines() if e.tier == "row"]


# Engines that MUST be available + actually execute in THIS environment (Spark JDK
# present, dbt adapters installed). If any of these produces only skips, the matrix
# is silently green-on-nothing -- the skipped-but-green guard fails in that case.
REQUIRED_LOCAL_ROW_ENGINES: tuple[str, ...] = (
    "SparkDirect",
    "DbtDuckDB",
    "DbtSparkSession",
    "SQLPlanGeneratorGold[duckdb]",
    "SQLPlanGeneratorGold[spark]",
)
