"""Integration test proving the local ``spark_session`` fixture EXECUTES.

The Spark truth-gate for this repo relies on a real, Delta-capable Spark
session being available locally via pip-bundled PySpark (no separate
``.local/spark`` install) and a resolved, Spark-compatible JDK. These tests
USE the session-scoped ``spark_session`` fixture (defined in ``tests/conftest``)
and assert on real Spark/Delta behaviour, so they only pass when the session was
actually created -- they must RUN (not skip) in an environment with a compatible
JDK (e.g. ``JAVA_HOME=.../openjdk@17``).

In this repo's verified environment PySpark 4.0 is pip-bundled, so the ONLY
expected local skip condition is "no Spark-compatible JDK could be resolved".
(The ``importorskip("pyspark")`` guard below -- matching the convention in
``tests/ingest_parity/test_spark_baseline.py`` -- additionally tolerates the
optional ``[spark]`` extra being entirely uninstalled; it never triggers when
PySpark is present, as it is here.)
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("pyspark", reason="PySpark required for the Spark session gate")

# This module specifically proves the LOCAL (pip-bundled PySpark + resolved JDK)
# path. The Databricks active-session-reuse path is a different contract (and a
# cluster session has no access to driver-local ``tmp_path``), so skip there.
pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.skipif(
        "DATABRICKS_RUNTIME_VERSION" in os.environ,
        reason="Local Spark gate; the Databricks runtime-session path is covered separately.",
    ),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def test_spark_session_runs_real_query(spark_session) -> None:
    """The fixture yields a working SparkSession that can execute a query."""
    rows = spark_session.range(5).collect()
    assert [r["id"] for r in rows] == [0, 1, 2, 3, 4]


def test_spark_session_is_delta_capable(spark_session, tmp_path) -> None:
    """The local fixture session must be genuinely Delta-capable.

    Creating, reading back, and updating a Delta table exercises the Delta
    catalog/extensions wired up by the fixture (via the Ivy ``delta-spark``
    package), not just vanilla Spark. This is what makes the session a valid
    stand-in for the Databricks runtime in the parity gate.
    """
    table_dir = tmp_path / "delta_people"
    df = spark_session.createDataFrame([(1, "Alice"), (2, "Bob")], ["id", "name"])
    df.write.format("delta").mode("overwrite").save(str(table_dir))

    loaded = spark_session.read.format("delta").load(str(table_dir))
    names = {r["name"] for r in loaded.collect()}
    assert names == {"Alice", "Bob"}

    # A Delta-only operation: in-place upsert/merge via SQL DELETE proves the
    # Delta SQL extensions are active (vanilla Parquet cannot DELETE in place).
    spark_session.sql(
        f"DELETE FROM delta.`{table_dir}` WHERE id = 1"  # noqa: S608 -- path is a trusted tmp_path
    )
    after_delete = spark_session.read.format("delta").load(str(table_dir))
    remaining = {r["name"] for r in after_delete.collect()}
    assert remaining == {"Bob"}
