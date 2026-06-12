"""Shared helpers to run a generated dbt project on a LOCAL Spark session.

The dbt-spark ``method: session`` adapter calls
``SparkSession.builder.getOrCreate()`` internally and gets back whatever session
is already active in THIS process. So the harness must:

  1. build a single Delta-capable Spark session with an ISOLATED warehouse dir +
     Derby metastore (so parallel/serial runs never collide on the metastore lock),
  2. load the all-string ``raw_<table>`` landing table(s) into that session (in the
     ``main`` schema the generated ``sources.yml`` points at),
  3. invoke dbt IN-PROCESS via :class:`dbt.cli.main.dbtRunner` (NOT a subprocess --
     a subprocess would spin a second JVM and deadlock on the Derby metastore), and
  4. read the resulting model table back from the same session.

Delta is required because the emitted contracts use ``ALTER COLUMN ... SET NOT
NULL``, which only Delta (the Databricks runtime format) supports; this also makes
the local session faithful to the Databricks target the casts are written for.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

# Ivy coordinate for Delta matching the pinned Spark 4.0 line (same as conftest).
_DELTA_PACKAGE = "io.delta:delta-spark_2.13:4.0.0"


def make_isolated_delta_session(app_name: str, work_dir: Path) -> SparkSession:
    """Create a Delta Spark session with a warehouse + metastore isolated to *work_dir*.

    Isolation is mandatory: dbt-spark's embedded Hive uses a Derby metastore that
    takes an exclusive file lock, so two runs sharing a metastore dir collide.

    The whole stack is pinned to UTC -- the SPARK session timezone AND the process
    TZ -- so that ``collect()`` materialises naive Python ``datetime``s in UTC and
    the canonical TIMESTAMP rendering is byte-identical to the Spark-direct oracle
    golden (which was generated under UTC). Without the process TZ pin, PySpark's
    timestamp->datetime conversion shifts to the host local zone on collect.
    """
    import os
    import time

    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()

    from pyspark.sql import SparkSession
    from tablespec.spark_factory import create_delta_spark_session

    # CRITICAL isolation guard: create_delta_spark_session (and Spark's
    # getOrCreate) REUSE any already-active session, which would silently ignore
    # the isolated warehouse/metastore config below and run against a shared
    # warehouse from an earlier spark_only test. Tear down any active session
    # first so OUR warehouse + Derby metastore config genuinely takes effect.
    active = SparkSession.getActiveSession()
    if active is not None:
        active.stop()

    warehouse = work_dir / "warehouse"
    metastore = work_dir / "metastore_db"
    config = {
        "spark.master": "local[1]",
        "spark.ui.enabled": "false",
        "spark.jars.packages": _DELTA_PACKAGE,
        "spark.sql.warehouse.dir": str(warehouse),
        "javax.jdo.option.ConnectionURL": (
            f"jdbc:derby:;databaseName={metastore};create=true"
        ),
        # ANSI off + UTC: match the Spark ingest baseline (NULL-on-failure casts,
        # host-timezone-independent TIMESTAMP rendering).
        "spark.sql.ansi.enabled": "false",
        "spark.sql.session.timeZone": "UTC",
        # Delta default so dbt's `create table ... as select` and the contract's
        # SET NOT NULL land on a Delta relation (matches the Databricks runtime).
        "spark.sql.sources.default": "delta",
    }
    spark = create_delta_spark_session(app_name, config)

    # Verify the isolation actually took (fail loud, never run against a stale
    # shared warehouse): the active warehouse dir must be the one we asked for.
    actual_warehouse = spark.conf.get("spark.sql.warehouse.dir", "")
    assert actual_warehouse and str(warehouse) in actual_warehouse, (
        "isolated warehouse config was not applied -- a pre-existing Spark session "
        f"was reused (warehouse={actual_warehouse!r}, expected {str(warehouse)!r})"
    )
    return spark


def load_raw_table(spark: SparkSession, umf: dict[str, Any], csv_path: Path) -> None:
    """(Re)create ``main.raw_<table>`` from a batch, preserving typed raw where needed.

    Delimited fixtures mirror the Spark-direct baseline's all-string landing table
    exactly; typed sources (including JSON) land through Spark's native reader and
    then receive the standard provenance columns.
    """
    from pyspark.sql.functions import lit, to_timestamp

    table = umf["table_name"]
    source = umf.get("source") or {}
    kind = source.get("kind")
    business_cols = [c["name"] for c in umf["columns"]]
    source_suffix = (csv_path.suffix or ".jsonl") if kind == "json" else ".csv"

    if kind == "json":
        from tablespec.ingestion import get_reader
        from tablespec.models.umf import JsonSource

        source_spec = JsonSource.model_validate(source).model_copy(
            update={"path": str(csv_path)}
        )
        df = get_reader(source_spec).read(source_spec, spark)
    else:
        string_cols = business_cols + ["_source_file"]
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

    if "_load_ts" in df.columns:
        df = df.withColumn("_load_ts", to_timestamp("_load_ts", "yyyy-MM-dd HH:mm:ss"))
    else:
        df = df.withColumn(
            "_load_ts",
            to_timestamp(lit("2026-01-01 00:00:00"), "yyyy-MM-dd HH:mm:ss"),
        )
    if "_source_file" not in df.columns:
        df = df.withColumn("_source_file", lit(f"{table}{source_suffix}"))
    ordered = business_cols + ["_source_file", "_load_ts"]
    df = df.select(*ordered)
    spark.sql("CREATE DATABASE IF NOT EXISTS main")
    spark.sql(f"DROP TABLE IF EXISTS main.raw_{table}")
    df.write.format("delta").mode("overwrite").saveAsTable(f"main.raw_{table}")


def run_dbt_in_process(project_dir: Path, *, schema: str = "default") -> Any:
    """Run ``dbt run`` in-process against the active Spark session.

    Returns the :class:`dbt.contracts.results.RunExecutionResult` so the caller can
    assert ``.success`` and inspect per-node status. Uses ``dbtRunner`` (NOT a
    subprocess) so the dbt-spark session adapter reuses THIS process's session.
    """
    from dbt.cli.main import dbtRunner

    os.environ["DBT_SPARK_SCHEMA"] = schema
    return dbtRunner().invoke(
        [
            "run",
            "--profiles-dir",
            str(project_dir),
            "--project-dir",
            str(project_dir),
            "--target",
            "dev",
        ]
    )
