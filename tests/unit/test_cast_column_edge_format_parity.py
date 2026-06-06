"""Cross-engine parity for the numeric date/time edge formats (epoch-ms, Excel-serial).

ADR-007 follow-up "cast-edge-formats": the runtime PySpark casters
(:func:`cast_timestamp_with_epoch_fallback`, :func:`convert_excel_serial_to_date`)
handle two numeric date/time encodings the committed-SQL seam
(:func:`cast_column_sql`) historically could not reproduce:

* **epoch milliseconds** -- 12+ digit / scientific values like ``1.75E+12``
* **Excel serial dates**  -- the day-count since ``1899-12-30``

This module proves the SQL seam now reaches byte-identical parity with the runtime
caster for those formats, gated to the SAME detection signal, across BOTH the
``spark`` and ``duckdb`` dialects.

Two layers:

1. :class:`TestEpochExcelDuckDBExec` / values feed (a) a Python oracle that mirrors
   the runtime arithmetic and (b) a live DuckDB execution of the duckdb-dialect
   ``cast_column_sql`` -- no JVM required, runs in the fast lane.
2. :class:`TestEpochExcelSparkVsDuckDB` (``spark_only``) runs the SAME raw values
   through the actual runtime PySpark caster AND the spark-dialect
   ``cast_column_sql`` executed on a real (UTC-pinned) Spark session AND DuckDB,
   and asserts all three render identical canonical strings.

Canonical comparison is by STRING rendering: a timestamp/date formatted as text is
timezone-independent on the wire, which is the byte-for-byte ingest contract the
artifact must honour (both engines are pinned to UTC so wall clocks coincide).

Run the spark layer with the Spark-compatible JDK::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/unit/test_cast_column_edge_format_parity.py
"""

from __future__ import annotations

import datetime as _dt

import pytest

from tablespec.casting_utils import (
    EPOCH_MS_FORMAT,
    EXCEL_SERIAL_FORMAT,
    cast_column_sql,
)

duckdb = pytest.importorskip("duckdb", reason="duckdb required for cast parity tests")


# Shared raw fixtures -- the SAME values flow through every engine/path below.
# Mix of: plain epoch ms, scientific notation, sub-second ms (truncated), a
# 12-digit boundary value, a non-epoch ISO string (falls through), and dirt.
_EPOCH_VALUES: list[str | None] = [
    "1750000000000",  # 2025-06-15 15:06:40 UTC
    "1.75E+12",  # scientific form of the same instant
    "1.75e12",  # lowercase scientific
    "1750000000999",  # sub-second ms -> truncated to :40
    "999999999999",  # 12-digit boundary (2001-09-09 ...)
    "1750000000000.0",  # decimal: NOT epoch-detected -> NULL (parity quirk)
    "2025-06-15 15:06:40",  # non-epoch ISO -> default timestamp parse
    "garbage",
    "",
    None,
]

_EXCEL_VALUES: list[str | None] = [
    "45141",  # 2023-08-03
    "45131",  # 2023-07-24
    "1",  # 1899-12-31
    "60",  # 1900-02-28 (Excel leap-year bug not compensated, matches runtime)
    "40000",  # 2009-07-06
    "garbage",
    "",
    None,
]


# ---------------------------------------------------------------------------
# Python oracle mirroring the runtime arithmetic (no Spark needed)
# ---------------------------------------------------------------------------


def _oracle_epoch(value: str | None) -> str | None:
    """Canonical string the runtime epoch caster produces for *value* (UTC)."""
    if value is None:
        return None
    # Detection identical to is_epoch_milliseconds.
    import re

    sci = re.fullmatch(r"[0-9]+\.?[0-9]*[Ee][+\-]?[0-9]+", value)
    big = re.fullmatch(r"[0-9]{12,}", value)
    if sci or big:
        secs = int(float(value) / 1000)  # from_unixtime truncates to whole seconds
        return _dt.datetime.fromtimestamp(secs, tz=_dt.UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    # Non-epoch -> default timestamp parse (only clean ISO succeeds here).
    try:
        return _dt.datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _oracle_excel(value: str | None) -> str | None:
    """Canonical string the runtime Excel-serial DATE caster produces for *value*."""
    if value is None:
        return None
    try:
        serial = int(value)
    except ValueError:
        return None
    return (_dt.date(1899, 12, 30) + _dt.timedelta(days=serial)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# DuckDB execution helpers
# ---------------------------------------------------------------------------


def _duck_eval(expr: str, values: list[str | None]) -> list[str | None]:
    """Run ``cast(expr as varchar)`` over *values* (one VARCHAR row each) in DuckDB."""
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute("CREATE TEMP TABLE t(i INTEGER, v VARCHAR)")
        con.executemany(
            "INSERT INTO t VALUES (?, ?)", [[i, v] for i, v in enumerate(values)]
        )
        rows = con.execute(
            f"SELECT i, cast(({expr}) as varchar) FROM t ORDER BY i"
        ).fetchall()
    finally:
        con.close()
    return [r[1] for r in rows]


# ---------------------------------------------------------------------------
# Layer 1: DuckDB-exec parity (no JVM) vs the Python oracle
# ---------------------------------------------------------------------------


@pytest.mark.no_spark
@pytest.mark.fast
class TestEpochExcelDuckDBExec:
    """Executable DuckDB SQL matches the runtime arithmetic (Python oracle)."""

    def test_epoch_ms_timestamp_duckdb_matches_oracle(self):
        expr = cast_column_sql("v", "TIMESTAMP", EPOCH_MS_FORMAT, dialect="duckdb")
        actual = _duck_eval(expr, _EPOCH_VALUES)
        expected = [_oracle_epoch(v) for v in _EPOCH_VALUES]
        assert actual == expected

    def test_epoch_ms_date_duckdb_truncates_to_date(self):
        expr = cast_column_sql("v", "DATE", EPOCH_MS_FORMAT, dialect="duckdb")
        actual = _duck_eval(expr, _EPOCH_VALUES)
        expected = [
            None if (ts := _oracle_epoch(v)) is None else ts[:10] for v in _EPOCH_VALUES
        ]
        assert actual == expected

    def test_excel_serial_date_duckdb_matches_oracle(self):
        expr = cast_column_sql("v", "DATE", EXCEL_SERIAL_FORMAT, dialect="duckdb")
        actual = _duck_eval(expr, _EXCEL_VALUES)
        expected = [_oracle_excel(v) for v in _EXCEL_VALUES]
        assert actual == expected

    def test_excel_serial_rejected_for_timestamp(self):
        """Excel-serial is DATE-only; timestamp target raises (symmetric guard)."""
        with pytest.raises(ValueError, match="only supported for DATE"):
            cast_column_sql("v", "TIMESTAMP", EXCEL_SERIAL_FORMAT, dialect="duckdb")
        with pytest.raises(ValueError, match="only supported for DATE"):
            cast_column_sql("v", "TIMESTAMP", EXCEL_SERIAL_FORMAT, dialect="spark")

    def test_edge_formats_bypass_registry_guard_both_dialects(self):
        """The sentinels are accepted by both dialects (not rejected as off-registry)."""
        for dialect in ("spark", "duckdb"):
            assert cast_column_sql("v", "TIMESTAMP", EPOCH_MS_FORMAT, dialect=dialect)
            assert cast_column_sql("v", "DATE", EXCEL_SERIAL_FORMAT, dialect=dialect)


# ---------------------------------------------------------------------------
# Layer 2: runtime PySpark caster == spark-dialect SQL == duckdb SQL
# ---------------------------------------------------------------------------


@pytest.mark.spark_only
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestEpochExcelSparkVsDuckDB:
    """The runtime caster, spark-dialect SQL, and duckdb SQL all agree (UTC)."""

    @pytest.fixture(scope="class")
    def utc_spark(self):
        pyspark = pytest.importorskip("pyspark")  # noqa: F841
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder.master("local[1]")
            .appName("edge-format-parity")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.ansi.enabled", "false")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        yield spark
        spark.stop()

    @staticmethod
    def _spark_runtime_epoch(spark, values):
        from pyspark.sql import functions as F

        from tablespec.casting_utils import cast_timestamp_with_epoch_fallback

        df = spark.createDataFrame([(i, v) for i, v in enumerate(values)], ["i", "v"])
        df = df.withColumn("out", cast_timestamp_with_epoch_fallback(F.col("v")))
        rows = df.selectExpr("i", "cast(out as string) as s").orderBy("i").collect()
        return [r["s"] for r in rows]

    @staticmethod
    def _spark_runtime_excel(spark, values):
        from pyspark.sql import functions as F

        from tablespec.casting_utils import convert_excel_serial_to_date

        df = spark.createDataFrame([(i, v) for i, v in enumerate(values)], ["i", "v"])
        df = df.withColumn("out", convert_excel_serial_to_date(F.col("v")))
        rows = df.selectExpr("i", "cast(out as string) as s").orderBy("i").collect()
        return [r["s"] for r in rows]

    @staticmethod
    def _spark_sql_eval(spark, expr, values):
        df = spark.createDataFrame([(i, v) for i, v in enumerate(values)], ["i", "v"])
        df.createOrReplaceTempView("edge_t")
        rows = spark.sql(
            f"SELECT i, cast(({expr}) as string) s FROM edge_t ORDER BY i"
        ).collect()
        return [r["s"] for r in rows]

    def test_epoch_ms_timestamp_three_way_parity(self, utc_spark):
        runtime = self._spark_runtime_epoch(utc_spark, _EPOCH_VALUES)
        spark_sql_expr = cast_column_sql(
            "v", "TIMESTAMP", EPOCH_MS_FORMAT, dialect="spark"
        )
        spark_sql = self._spark_sql_eval(utc_spark, spark_sql_expr, _EPOCH_VALUES)
        duck_sql = _duck_eval(
            cast_column_sql("v", "TIMESTAMP", EPOCH_MS_FORMAT, dialect="duckdb"),
            _EPOCH_VALUES,
        )
        oracle = [_oracle_epoch(v) for v in _EPOCH_VALUES]
        assert runtime == oracle, f"runtime drifted from oracle: {runtime} != {oracle}"
        assert spark_sql == runtime, (
            f"spark SQL != runtime caster: {spark_sql} != {runtime}"
        )
        assert duck_sql == runtime, (
            f"duckdb SQL != runtime caster: {duck_sql} != {runtime}"
        )

    def test_excel_serial_date_three_way_parity(self, utc_spark):
        runtime = self._spark_runtime_excel(utc_spark, _EXCEL_VALUES)
        spark_sql = self._spark_sql_eval(
            utc_spark,
            cast_column_sql("v", "DATE", EXCEL_SERIAL_FORMAT, dialect="spark"),
            _EXCEL_VALUES,
        )
        duck_sql = _duck_eval(
            cast_column_sql("v", "DATE", EXCEL_SERIAL_FORMAT, dialect="duckdb"),
            _EXCEL_VALUES,
        )
        oracle = [_oracle_excel(v) for v in _EXCEL_VALUES]
        assert runtime == oracle, f"runtime drifted from oracle: {runtime} != {oracle}"
        assert spark_sql == runtime, (
            f"spark SQL != runtime caster: {spark_sql} != {runtime}"
        )
        assert duck_sql == runtime, (
            f"duckdb SQL != runtime caster: {duck_sql} != {runtime}"
        )


# ---------------------------------------------------------------------------
# Layer 3: spark-dialect SQL on Spark Connect (Sail, no JVM) == oracle
# ---------------------------------------------------------------------------


try:
    from pysail.spark import SparkConnectServer
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False


@pytest.mark.no_spark  # Sail needs no JVM/JAVA_HOME.
@pytest.mark.skipif(not _HAS_SAIL, reason="pysail not available")
@pytest.mark.filterwarnings("ignore::ResourceWarning")
class TestEpochExcelSailConnect:
    """The spark-dialect edge-format SQL also runs identically on Spark Connect.

    The committed artifact's Spark SQL is engine-only (``from_unixtime``, ``rlike``,
    ``date_add``) -- no JVM-specific Column API -- so it must execute the same on a
    Connect backend. Sail is a JVM-free Connect server, so this proves the SQL is
    portable across classic Spark and Connect without a JAVA_HOME.
    """

    @pytest.fixture(scope="class")
    def sail_spark(self):
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ResourceWarning)
            server = SparkConnectServer()
            server.start()
            host, port = server.listening_address
            session = (
                RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
                .appName("edge-format-parity-sail")
                .config("spark.sql.session.timeZone", "UTC")
                .create()
            )
            yield session
            session.stop()
            server.stop()

    @staticmethod
    def _sql_eval(spark, expr, values):
        df = spark.createDataFrame([(i, v) for i, v in enumerate(values)], ["i", "v"])
        df.createOrReplaceTempView("edge_sail_t")
        rows = spark.sql(
            f"SELECT i, cast(({expr}) as string) s FROM edge_sail_t ORDER BY i"
        ).collect()
        return [r["s"] for r in rows]

    def test_epoch_ms_sql_on_sail_matches_oracle(self, sail_spark):
        expr = cast_column_sql("v", "TIMESTAMP", EPOCH_MS_FORMAT, dialect="spark")
        actual = self._sql_eval(sail_spark, expr, _EPOCH_VALUES)
        assert actual == [_oracle_epoch(v) for v in _EPOCH_VALUES]

    def test_excel_serial_sql_on_sail_matches_oracle(self, sail_spark):
        expr = cast_column_sql("v", "DATE", EXCEL_SERIAL_FORMAT, dialect="spark")
        actual = self._sql_eval(sail_spark, expr, _EXCEL_VALUES)
        assert actual == [_oracle_excel(v) for v in _EXCEL_VALUES]
