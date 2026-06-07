"""End-to-end Spark Connect lane for the native profiler, using Sail.

This is the cheap LOCAL Spark-Connect lane the project wanted: pysail ships a
Rust-based Spark Connect server (no JVM, no JAVA_HOME required), so we can run
``NativeSparkProfiler`` against a genuine Spark Connect session and prove it is
Connect-safe.

The profiler is also exercised on real Databricks serverless (Python 3.12 /
Spark Connect); these assertions guard the same Connect compatibility locally
and for free. The two prod-neutral profiler fixes this lane locks in are:

* scalar ``percentile_approx`` per probe (DataFusion only accepts a scalar
  percentile), and
* type-aware exact ``count_distinct`` for float/double columns (DataFusion does
  not implement ``approx_distinct`` for Float64).
"""

from __future__ import annotations

import warnings

# @covers US-021-AC1
# @covers US-021-AC2
# @covers US-021-AC3
# @covers US-021-AC4
# @covers US-021-AC5

import pytest

try:
    from pysail.spark import SparkConnectServer

    # The Spark CONNECT builder (not the top-level pyspark.sql.SparkSession
    # builder) is used deliberately: the top-level remote().getOrCreate() raises
    # SESSION_ALREADY_EXIST if a regular JVM Spark session is already active in
    # the process, which is the case during the full `make test` run. The connect
    # builder has no such guard and leaves any classic session untouched.
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False

pytestmark = [
    pytest.mark.no_spark,  # Sail needs no JVM/JAVA_HOME; skip classic-Spark setup.
    pytest.mark.skipif(not _HAS_SAIL, reason="pysail not available"),
]


@pytest.fixture(scope="module")
def sail_spark():
    """Start a Sail Spark Connect server and yield a Connect SparkSession."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address
        session = (
            RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
            .appName("tablespec-profiler-connect-sail")
            .create()
        )
        yield session
        session.stop()
        server.stop()


def _mixed_dataframe(spark):
    """Build a mixed-type DataFrame: double, bigint, string, low-card double."""
    schema = "score double, id bigint, name string, bucket double"
    rows = [
        (1.5, 100, "alpha", 1.0),
        (2.5, 101, "bravo", 1.0),
        (3.5, 102, "charlie", 2.0),
        (4.5, 103, "delta", 2.0),
        (5.5, 104, "echo", 3.0),
        (6.5, 105, "foxtrot", 3.0),
        (7.5, 106, "golf", 1.0),
        (8.5, 107, "hotel", 2.0),
        (9.5, 108, "india", 3.0),
        (10.5, 109, "juliet", 1.0),
    ]
    return spark.createDataFrame(rows, schema)


def test_profiler_runs_end_to_end_on_spark_connect(sail_spark):
    """NativeSparkProfiler.profile() succeeds end-to-end on a Sail Connect session."""
    from tablespec.profiling import NativeSparkProfiler

    df = _mixed_dataframe(sail_spark)

    profiler = NativeSparkProfiler(sail_spark, low_cardinality_threshold=5)
    profile = profiler.profile(df)

    # --- Top-level shape ---
    assert profile.num_records == 10
    assert set(profile.columns) == {"score", "id", "name", "bucket"}

    # --- Double column: stats + quantiles (the scalar-percentile path) ---
    score = profile.columns["score"]
    assert score.completeness == 1.0
    assert score.minimum == pytest.approx(1.5)
    assert score.maximum == pytest.approx(10.5)
    assert score.mean == pytest.approx(6.0, abs=0.5)
    # Quantiles must be present and ordered (proves percentile_approx ran).
    assert score.quantiles is not None
    assert set(score.quantiles) == {"p5", "p25", "p50", "p75", "p95"}
    q = score.quantiles
    assert q["p5"] <= q["p25"] <= q["p50"] <= q["p75"] <= q["p95"]
    # All 10 distinct doubles -> exact count_distinct fallback (no approx on Float64).
    assert score.approximate_num_distinct == 10

    # --- Bigint column: distinct counts ---
    id_col = profile.columns["id"]
    assert id_col.completeness == 1.0
    assert id_col.approximate_num_distinct == 10

    # --- String column: length stats survive the scalar-median path ---
    name = profile.columns["name"]
    assert name.completeness == 1.0
    assert name.string_length_min is not None
    assert name.string_length_max is not None

    # --- Low-cardinality double: distinct values collected ---
    bucket = profile.columns["bucket"]
    assert bucket.approximate_num_distinct == 3
    assert bucket.distinct_values is not None
    assert len(bucket.distinct_values) == 3
