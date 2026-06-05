"""Phase 1 Spark baseline for raw->ingest parity.

For each committed fixture under ``tests/fixtures/ingest/`` this test:

  1. loads the UMF spec and the raw all-STRING CSV(s),
  2. runs the EXISTING ``tablespec.generate_ingest_sql(umf)`` to produce the SQL,
  3. executes that SQL on a real Spark (Delta) session against a ``raw_<table>``
     landing table (for incremental+pk it runs an initial load then a second
     batch to exercise dedup-latest + MERGE upsert),
  4. canonicalizes the resulting ``ingested_<table>`` (see ``canonical.py``), and
  5. asserts it equals the committed golden file under
     ``tests/golden/ingest_parity/<fixture>.spark.expected.json``.

This Spark output is the source of truth that the later dbt path is checked
against. Tests are skipped unless a Delta-capable Spark session is available.

Baseline assumption (IMPORTANT for parity): the session runs with
``spark.sql.ansi.enabled=false`` so that malformed numeric/boolean/date inputs
become NULL instead of aborting the job. ``cast_column_sql`` emits plain
``cast(...)`` (not ``try_cast``), so this is the contract the committed artifact
relies on: it must be executed with ANSI casting disabled (the Databricks default
for this pipeline). The dbt/duckdb parity path must reproduce the same
NULL-on-failure behavior to match these goldens.

Run with the Spark-compatible JDK, e.g.::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 \
      uv run pytest tests/ingest_parity/test_spark_baseline.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from tablespec.schemas.ingest_generator import generate_ingest_sql

from tests.conformance.corpus.registry import Case, ingest_cases

from .canonical import to_json

pyspark = pytest.importorskip("pyspark", reason="PySpark required for Spark baseline")

# Spark's py4j gateway leaves sockets to be GC'd; under the repo-wide
# ``filterwarnings = error`` policy the resulting ResourceWarning would be
# escalated into a spurious failure. These are transport-cleanup artifacts, not
# defects in the ingest logic under test, so suppress them for this module only.
# This module REQUIRES a JVM-backed Delta Spark session; it is the source-of-truth
# baseline. Marked spark_only so the JVM-free fast lane (``-m no_spark``) skips it.
pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

# Ivy coordinate for Delta matching the pinned Spark 4.0 line.
_DELTA_PACKAGE = "io.delta:delta-spark_2.13:4.0.0"

# The fixture corpus (UMF + ordered raw batches + per-case ts_precision + the
# committed golden) is now declared in tests/conformance/corpus/cases.yaml and
# loaded via the registry. Multi-batch cases simply list >1 batch there; the
# dedup-latest window + MERGE upsert (incremental+pk) or blind-INSERT append
# (keyless incremental) is exercised by replaying the batches in order.


@pytest.fixture(scope="session")
def spark():
    """Delta-capable Spark session with ANSI cast disabled.

    ANSI is disabled so that malformed numeric/boolean/date inputs become NULL
    (matching the documented intent of cast_column_sql / cast_column_with_format)
    rather than aborting the job. This mirrors how the committed artifact is meant
    to run when ingesting raw, untyped landing data.
    """
    try:
        from pyspark.sql import SparkSession
    except ImportError:  # pragma: no cover
        pytest.skip("PySpark not available")

    os.environ.setdefault("TQDM_DISABLE", "1")

    # Pin the WHOLE stack (Python process, driver JVM, Spark session) to UTC.
    # pyspark's collect() converts TIMESTAMP values to the *Python* local time, so
    # a session-only timezone is not enough: the driver JVM and the Python process
    # must agree, otherwise the canonical strings would be host-TZ dependent.
    os.environ["TZ"] = "UTC"
    import time as _time

    if hasattr(_time, "tzset"):
        _time.tzset()

    import tempfile

    warehouse = tempfile.mkdtemp(prefix="tablespec_baseline_wh_")

    builder = (
        SparkSession.builder.master("local[2]")
        .appName("tablespec-ingest-baseline")
        .config("spark.sql.warehouse.dir", warehouse)
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
        # Pin the session timezone so TIMESTAMP values render identically here and
        # in the future dbt/duckdb parity path (no implicit host-TZ dependence).
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.default.parallelism", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.databricks.delta.snapshotPartitions", "2")
    )
    try:
        session = builder.getOrCreate()
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Could not start Delta Spark session: {exc}")
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()
    import shutil

    shutil.rmtree(warehouse, ignore_errors=True)


def _split_statements(sql: str) -> list[str]:
    """Split the multi-statement artifact into executable statements.

    Comment lines (-- ...) are stripped *first* (some warning comments contain a
    ';'), then the remaining SQL is split on ';'. The artifact never contains ';'
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


def _load_raw(spark, umf: dict[str, Any], csv_path: Path, raw_table: str) -> None:
    """(Re)create the raw landing Delta table from an all-STRING CSV batch."""
    from pyspark.sql.functions import to_timestamp

    string_cols = [c["name"] for c in umf["columns"]] + ["_source_file"]
    # Read every field as a string; cast _load_ts explicitly to a timestamp.
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
    # Conform to the canonical raw schema column order.
    ordered = [c["name"] for c in umf["columns"]] + ["_source_file", "_load_ts"]
    df = df.select(*ordered)
    spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
    df.write.format("delta").mode("overwrite").saveAsTable(raw_table)


def _decimal_scales(umf: dict[str, Any]) -> dict[str, int | None]:
    scales: dict[str, int | None] = {}
    for col in umf["columns"]:
        if (col.get("data_type") or "").upper() == "DECIMAL":
            scales[col["name"]] = col["scale"] if col.get("scale") is not None else 2
    return scales


def _collect_canonical(
    spark, umf: dict[str, Any], ingested_table: str, ts_precision: int
) -> str:
    columns = [c["name"] for c in umf["columns"]]
    rows = [r.asDict() for r in spark.table(ingested_table).collect()]
    # Each corpus case pins its own ts_precision: the second-resolution fixtures
    # pin 0 (their committed goldens stay byte-for-byte); the sub-second/tz case
    # pins 6 (microsecond) so fractional-second values are visible in the golden.
    return to_json(rows, columns, _decimal_scales(umf), ts_precision=ts_precision)


_INGEST_CASES = ingest_cases()


@pytest.mark.slow
@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_spark_ingest_baseline(spark, case: Case, request) -> None:
    assert case.umf is not None and case.golden is not None
    umf = yaml.safe_load(case.umf.read_text())
    table = umf["table_name"]
    raw_table = f"raw_{table}"
    ingested_table = f"ingested_{table}"

    # Clean any state from a previous run / fixture sharing this table name.
    spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
    spark.sql(f"DROP TABLE IF EXISTS {ingested_table}")

    sql = generate_ingest_sql(umf)
    statements = _split_statements(sql)
    # The artifact is: CREATE raw, CREATE ingested, then the transform.
    create_stmts = statements[:-1]
    transform_stmt = statements[-1]

    for stmt in create_stmts:
        spark.sql(stmt)

    for batch in case.batches:
        assert batch.exists(), f"missing raw batch: {batch}"
        _load_raw(spark, umf, batch, raw_table)
        spark.sql(transform_stmt)

    actual = _collect_canonical(spark, umf, ingested_table, case.ts_precision)

    golden = case.golden
    if request.config.getoption("--update-golden", default=False):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)

    assert golden.exists(), (
        f"golden missing for '{case.id}': {golden}. Regenerate with --update-golden."
    )
    expected = golden.read_text()
    assert actual == expected, (
        f"Spark baseline mismatch for '{case.id}'.\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{actual}"
    )

    # Clean up so reused table names don't bleed across fixtures.
    spark.sql(f"DROP TABLE IF EXISTS {raw_table}")
    spark.sql(f"DROP TABLE IF EXISTS {ingested_table}")
