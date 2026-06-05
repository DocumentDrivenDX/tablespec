"""EXECUTED orphan-FK relationships enforcement for ``gold_fk_integrity``.

FK referential integrity is NOT a canonical-row comparison: ``generate_sql_plan``
uses FK metadata only for join planning and never emits an orphan check, so the
row-parity matrix (``test_engine_matrix.py``) deliberately SKIPS this case with an
explicit reason. The contract is instead enforced at the dbt ``relationships``
schema-test tier -- and THAT tier is what this module EXECUTES (it is the executed
"engine" that promotes ``gold_fk_integrity`` out of ``pending``).

The promotion is a REAL, gating, two-sided dbt run on BOTH backends:

  * **DuckDB** (``dbt build`` via the CLI, JVM-free) -- the full FK fixtures with
    their PK + NOT-NULL contracts materialize, and the relationships test is asserted
    PASS on ``claims.clean.csv`` / FAIL on ``claims.orphan.csv``.
  * **Spark session** (``dbt build`` in-process via :class:`dbtRunner`, where
    applicable) -- the SAME relationships test runs against a local Delta Spark
    session, again asserted PASS on clean / FAIL on the orphan.

In BOTH cases the assertion is on the ``relationships_claims_member_id`` node's
status (and ``failures`` count) in ``target/run_results.json`` -- not a stdout
string and not a generator text check. The clean leg requires ``status == "pass"``
with zero failures; the orphan leg requires ``status == "fail"`` with exactly ONE
failure (the injected ``member_id=7`` orphan). A test ERROR (a broken/erroring
relationships node) therefore cannot satisfy either leg.

Both legs build the SAME generated project; only the raw ``claims`` rows differ.

Two SQLPlanGenerator/dbt-emitter facts make the Spark leg work:

  1. ``_model_config`` now pins ``file_format='delta'`` for the spark/databricks
     dialects on an incremental ``merge`` model (dbt-spark REJECTS ``merge`` on the
     default ``parquet`` format, which had SKIPPED every downstream test); and
  2. the Spark leg relaxes ONLY the NOT-NULL column contract (it keeps the PK / merge
     ``unique_key`` and the FK) because ``ALTER COLUMN ... SET NOT NULL`` on a freshly
     created MANAGED Delta table is unsupported by the local dbt-spark session. That
     NOT-NULL contract is a real Databricks-runtime feature; it is covered on the real
     runtime by the dbt-databricks compile tier and the LDP databricks_e2e tier, not
     by this local session. The FK relationships test -- the actual unit under test --
     is a dialect-agnostic dbt generic test and runs UNCHANGED on both backends.

Run::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=.../openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/conformance/test_fk_orphan_enforcement.py
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from tablespec.models.umf import UMF
from tablespec.schemas.dbt_generator import generate_dbt_project
from tests.conformance.corpus.registry import gold_cases

pytestmark = [pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for the orphan-FK tier")
pytest.importorskip("dbt", reason="dbt-core required for the orphan-FK tier")
pytest.importorskip(
    "dbt.adapters.duckdb", reason="dbt-duckdb adapter required for the orphan-FK tier"
)
if shutil.which("dbt") is None:  # pragma: no cover - env guard
    pytest.skip("dbt CLI not on PATH", allow_module_level=True)

_FK_CASE = next(c for c in gold_cases() if c.id == "gold_fk_integrity")

# The dbt node id of the FK relationships test (substring-matched in run_results).
_REL_NODE = "relationships_claims_member_id"


def _fk_dir() -> Path:
    assert _FK_CASE.gold_dir is not None and _FK_CASE.gold_dir.is_dir()
    return _FK_CASE.gold_dir


def _claims_raw() -> dict[str, Any]:
    return yaml.safe_load((_fk_dir() / "claims.umf.yaml").read_text())


def _member_umf() -> UMF:
    return UMF(**yaml.safe_load((_fk_dir() / "member.umf.yaml").read_text()))


def _run_results(project: Path) -> dict[str, dict]:
    """Map ``run_results.json`` -> {node_unique_id: result}. dbt writes it on FAIL too."""
    data = json.loads((project / "target" / "run_results.json").read_text())
    return {r["unique_id"]: r for r in data["results"]}


def _rel_result(project: Path) -> dict:
    """Return the single ``relationships_claims_member_id`` node's run-result."""
    results = _run_results(project)
    matches = [r for uid, r in results.items() if _REL_NODE in uid]
    assert matches, (
        f"the FK relationships test ({_REL_NODE!r}) did not run -- "
        f"no matching node in run_results.json: {sorted(results)}"
    )
    assert len(matches) == 1, f"ambiguous {_REL_NODE!r} match: {sorted(results)}"
    return matches[0]


def _assert_clean_passes(project: Path) -> None:
    rel = _rel_result(project)
    assert rel["status"] == "pass", (
        f"relationships test must PASS on clean FK data (every member_id resolves); "
        f"got node result {rel}"
    )
    assert rel.get("failures", 0) == 0, f"clean data must report zero orphans: {rel}"


def _assert_orphan_fails(project: Path) -> None:
    rel = _rel_result(project)
    # A FAIL (not an ERROR) proves the relationships test RAN and DETECTED the orphan
    # row. exactly ONE failure pins it to the single injected orphan (member_id=7).
    assert rel["status"] == "fail", (
        f"relationships test must FAIL on the orphan FK (member_id=7 has no member "
        f"row), not error/pass; got node result {rel}"
    )
    assert rel.get("failures", 0) == 1, (
        f"the orphan-FK negative must detect EXACTLY the one injected orphan "
        f"(member_id=7); got node result {rel}"
    )


# ---------------------------------------------------------------------------
# Wiring guard
# ---------------------------------------------------------------------------


def test_orphan_fk_tier_is_wired_here() -> None:
    """Guard: the executed orphan-FK tier is wired (fixtures + relationships emitted)."""
    d = _fk_dir()
    assert (d / "claims.clean.csv").exists() and (d / "claims.orphan.csv").exists()
    files = generate_dbt_project(
        _claims_raw(), dialect="duckdb", target="duckdb", related=[_member_umf()]
    )
    assert "relationships:" in files["models/schema.yml"], (
        "the orphan-FK tier is not wired: no relationships test emitted for the FK"
    )


# ---------------------------------------------------------------------------
# DuckDB leg (CLI dbt build; full PK + NOT-NULL contract)
# ---------------------------------------------------------------------------


def _load_raw_duckdb(con, table: str, csv: Path, cols: list[str]) -> None:
    """Create ``main.raw_<table>`` with the provenance columns the ingest model reads."""
    con.execute("CREATE SCHEMA IF NOT EXISTS main")
    con.execute(f"DROP TABLE IF EXISTS main.raw_{table}")
    coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
    con.execute(
        f"CREATE TABLE main.raw_{table} "
        f'({coldefs}, "_source_file" VARCHAR, "_load_ts" TIMESTAMP)'
    )
    proj = ", ".join(f'"{c}"' for c in cols)
    con.execute(
        f"INSERT INTO main.raw_{table} SELECT {proj}, "
        f"'{table}.csv', TIMESTAMP '2026-01-01 00:00:00' "
        f"FROM read_csv_auto('{csv}', header=true, all_varchar=true)"
    )


def _build_duckdb(claims_csv_name: str) -> Path:
    """Generate the FK project, load member + the chosen claims CSV, run ``dbt build``.

    Returns the project dir (NOT cleaned up) so the caller can read run_results.json.
    """
    project = Path(tempfile.mkdtemp(prefix="fk_orphan_duckdb_"))
    generate_dbt_project(
        _claims_raw(),
        dialect="duckdb",
        target="duckdb",
        related=[_member_umf()],
        out_dir=project,
    )
    assert "relationships:" in (project / "models" / "schema.yml").read_text()

    d = _fk_dir()
    db_path = project / "fk.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        _load_raw_duckdb(
            con, "member", d / "member.raw.csv", ["member_id", "member_name"]
        )
        _load_raw_duckdb(con, "claims", d / claims_csv_name, ["claim_id", "member_id"])
    finally:
        con.close()

    env = dict(os.environ, DBT_DUCKDB_PATH=str(db_path))
    subprocess.run(
        ["dbt", "build", "--profiles-dir", str(project), "--project-dir", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return project


def test_duckdb_relationships_passes_on_clean_data() -> None:
    """DuckDB: the relationships node PASSES on clean FK data (run_results status)."""
    project = _build_duckdb("claims.clean.csv")
    try:
        _assert_clean_passes(project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_duckdb_relationships_fails_on_orphan_fk() -> None:
    """DuckDB: the relationships node FAILS on the injected orphan (run_results status)."""
    project = _build_duckdb("claims.orphan.csv")
    try:
        _assert_orphan_fails(project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# Spark-session leg (in-process dbtRunner; relationships test on local Delta)
# ---------------------------------------------------------------------------

_spark_reason: str | None = None
try:  # pragma: no cover - import availability gate
    import pyspark  # noqa: F401
    import dbt.adapters.spark  # noqa: F401
except Exception as exc:  # pragma: no cover - env guard
    _spark_reason = f"pyspark + dbt-spark required for the spark FK leg: {exc}"


def _claims_raw_spark() -> dict[str, Any]:
    """The claims UMF with NOT-NULL contracts relaxed for the local Delta session.

    Keeps the PK (so the model still materializes via an incremental ``merge`` on the
    ``unique_key``) and the FK (so the relationships test is emitted); only drops the
    per-column NOT-NULL constraint, because ``ALTER COLUMN ... SET NOT NULL`` on a
    freshly created MANAGED Delta table is unsupported by the local dbt-spark session.
    """
    raw = copy.deepcopy(_claims_raw())
    for col in raw["columns"]:
        col["nullable"] = {"default": True}
    return raw


def _member_umf_spark() -> UMF:
    raw = yaml.safe_load((_fk_dir() / "member.umf.yaml").read_text())
    for col in raw["columns"]:
        col["nullable"] = {"default": True}
    return UMF(**raw)


def _load_raw_spark(spark, table: str, csv: Path, cols: list[str]) -> None:
    """Load ``main.raw_<table>`` into the Spark session with synthesized provenance."""
    from pyspark.sql.functions import lit, to_timestamp

    schema_ddl = ", ".join(f"`{c}` string" for c in cols)
    df = spark.read.option("header", True).schema(schema_ddl).csv(str(csv))
    df = df.withColumn("_source_file", lit(f"{table}.csv")).withColumn(
        "_load_ts", to_timestamp(lit("2026-01-01 00:00:00"), "yyyy-MM-dd HH:mm:ss")
    )
    spark.sql("CREATE DATABASE IF NOT EXISTS main")
    spark.sql(f"DROP TABLE IF EXISTS main.raw_{table}")
    df.write.format("delta").mode("overwrite").saveAsTable(f"main.raw_{table}")


def _build_spark(spark, claims_csv_name: str) -> Path:
    """Generate the spark FK project, load raw, run ``dbt build`` in-process."""
    from dbt.cli.main import dbtRunner

    # Drop any models left from a prior leg so each build is a fresh full-refresh.
    for t in ("claims", "member"):
        spark.sql(f"DROP TABLE IF EXISTS main.{t}")

    project = Path(tempfile.mkdtemp(prefix="fk_orphan_spark_"))
    generate_dbt_project(
        _claims_raw_spark(),
        dialect="spark",
        target="spark",
        related=[_member_umf_spark()],
        out_dir=project,
    )
    assert "relationships:" in (project / "models" / "schema.yml").read_text()
    assert "file_format='delta'" in (project / "models" / "claims.sql").read_text(), (
        "the spark incremental-merge model must pin file_format='delta' "
        "(else dbt-spark rejects the merge strategy and skips the FK test)"
    )

    d = _fk_dir()
    _load_raw_spark(spark, "member", d / "member.raw.csv", ["member_id", "member_name"])
    _load_raw_spark(spark, "claims", d / claims_csv_name, ["claim_id", "member_id"])

    os.environ["DBT_SPARK_SCHEMA"] = "main"
    dbtRunner().invoke(
        [
            "build",
            "--profiles-dir",
            str(project),
            "--project-dir",
            str(project),
            "--target",
            "dev",
        ]
    )
    return project


@pytest.mark.spark_only
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_spark_relationships_passes_then_fails() -> None:
    """Spark session: the relationships node PASSES on clean and FAILS on the orphan.

    Both legs run in-process via ``dbtRunner`` against one shared local Delta session
    (a second JVM/subprocess would deadlock the Derby metastore), and assert on the
    ``run_results.json`` node status -- the SAME contract proven on DuckDB.
    """
    if _spark_reason is not None:
        pytest.skip(_spark_reason)

    from tests.conformance.engines import (
        get_shared_spark_session,
        stop_shared_spark_session,
    )

    spark = get_shared_spark_session()
    try:
        clean = _build_spark(spark, "claims.clean.csv")
        try:
            _assert_clean_passes(clean)
        finally:
            shutil.rmtree(clean, ignore_errors=True)

        orphan = _build_spark(spark, "claims.orphan.csv")
        try:
            _assert_orphan_fails(orphan)
        finally:
            shutil.rmtree(orphan, ignore_errors=True)
    finally:
        for t in ("claims", "member", "raw_claims", "raw_member"):
            try:
                spark.sql(f"DROP TABLE IF EXISTS main.{t}")
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        stop_shared_spark_session()
