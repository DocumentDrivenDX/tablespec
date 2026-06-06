"""Classic-Spark vs Sail-Connect PARITY for the four custom GX expectations.

The four tablespec custom expectations
(``expect_column_values_to_cast_to_type``,
``expect_column_values_to_match_domain_type``,
``expect_column_pair_values_a_to_be_greater_than_b``,
``expect_column_date_to_be_in_current_year``) are routed through GX's classic
``add_spark`` engine on classic Spark and through the Connect-safe native path
(``gx_executor._evaluate_custom_native`` -> ``custom_gx_expectations`` validators)
on Spark Connect. The two engines MUST agree.

This module drives ``GXSuiteExecutor.execute_suite`` for every custom on BOTH
engines and asserts the EXACT same verdict (``success``) and ``unexpected_count``.
The ``engine`` fixture is parametrized over:

* ``classic`` -- the conftest session-scoped classic-Spark session (real JVM;
  requires ``JAVA_HOME``); takes the GX ``add_spark`` path.
* ``connect`` -- a module-local Sail (pysail) Spark Connect session (no JVM);
  takes the native path. Built with the Spark CONNECT builder so it coexists with
  an active classic JVM session in the same pytest process (the top-level
  ``remote().getOrCreate()`` would raise SESSION_ALREADY_EXIST).

The domain-type custom in particular is driven THROUGH the executor here, so the
``df.select(col).toPandas()`` collect at ``gx_executor.py`` is exercised end to end
on Connect -- not just via the pandas shim.
"""

from __future__ import annotations

import datetime
import warnings
from typing import Any

import pytest

# Importing the module registers the GX custom Expectation classes used by the
# classic ``add_spark`` path.
import tablespec.validation.custom_gx_expectations  # noqa: F401

try:
    from pysail.spark import SparkConnectServer  # noqa: F401

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False


@pytest.fixture(autouse=True)
def _quiet_gx_resource_warnings():
    """Suppress the spurious ResourceWarning / unraisable warnings GX + Sail emit.

    ``pyproject`` sets ``filterwarnings = ["error", ...]``. GX's ephemeral docs
    temp-dir cleanup and Sail's GC raise ``ResourceWarning`` /
    ``PytestUnraisableExceptionWarning`` asynchronously, which pytest mis-attributes
    to whichever test is running -- false-failing unrelated lanes. The conftest
    ``gx_harness`` fixture filters these same two categories for the same reason.
    """
    original = warnings.filters[:]
    warnings.filterwarnings("ignore", category=pytest.PytestUnraisableExceptionWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)
    yield
    warnings.filters[:] = original


@pytest.fixture(scope="module")
def _sail_session():
    """Start a Sail Spark Connect server and yield a Connect SparkSession.

    Uses the Spark CONNECT builder directly (not ``remote().getOrCreate()``) so it
    leaves any active classic JVM session -- the conftest ``spark_session`` used by
    the ``classic`` lane in the same process -- untouched.
    """
    if not _HAS_SAIL:
        pytest.skip("pysail not available")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address
        session = (
            RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
            .appName("tablespec-custom-gx-parity")
            .create()
        )
        yield session
        session.stop()
        server.stop()


@pytest.fixture(params=["classic", "connect"])
def engine(request):
    """Yield a SparkSession for each engine lane (classic-Spark and Sail-Connect).

    The ``classic`` lane defers to the conftest session-scoped ``spark_session``
    (real JVM under JAVA_HOME); the ``connect`` lane uses the module-local Sail
    session. Each is resolved lazily so a missing JDK skips only the classic lane
    and a missing pysail skips only the connect lane.
    """
    if request.param == "classic":
        return request.getfixturevalue("spark_session")
    return request.getfixturevalue("_sail_session")


def _run(spark: Any, expectations: list[dict[str, Any]], data, schema):
    from tablespec.validation.gx_executor import GXSuiteExecutor

    df = spark.createDataFrame(data, schema)
    executor = GXSuiteExecutor(spark=spark)
    return executor.execute_suite(df, expectations)


def _by_type(result):
    return {r.expectation_type: r for r in result.results}


# ─────────────────────────────────────────────────────────────────────
# (a) date_in_current_year -- clean (2026) passes, prior-year dirty fails.
# ─────────────────────────────────────────────────────────────────────


def test_date_in_current_year_parity(engine):
    exp = [
        {
            "type": "expect_column_date_to_be_in_current_year",
            "kwargs": {"column": "d"},
        }
    ]
    schema = "d date"
    year = datetime.date.today().year

    clean = _by_type(
        _run(
            engine,
            exp,
            [(datetime.date(year, 1, 1),), (datetime.date(year, 6, 1),)],
            schema,
        )
    )
    rc = clean["expect_column_date_to_be_in_current_year"]
    assert rc.success is True
    assert rc.unexpected_count == 0

    dirty = _by_type(
        _run(
            engine,
            exp,
            [(datetime.date(year, 1, 1),), (datetime.date(year - 6, 5, 1),)],
            schema,
        )
    )
    rd = dirty["expect_column_date_to_be_in_current_year"]
    assert rd.success is False
    assert rd.unexpected_count == 1


# ─────────────────────────────────────────────────────────────────────
# (b) match_domain_type -- driven THROUGH the executor (toPandas collect path).
# ─────────────────────────────────────────────────────────────────────


def test_match_domain_type_parity(engine):
    exp = [
        {
            "type": "expect_column_values_to_match_domain_type",
            "kwargs": {"column": "state", "domain_type": "us_state_code"},
        }
    ]
    schema = "state string"

    clean = _by_type(_run(engine, exp, [("MD",), ("CA",), ("NY",)], schema))
    rc = clean["expect_column_values_to_match_domain_type"]
    assert rc.success is True
    assert rc.unexpected_count == 0

    dirty = _by_type(_run(engine, exp, [("MD",), ("XX",), ("NY",)], schema))
    rd = dirty["expect_column_values_to_match_domain_type"]
    assert rd.success is False
    assert rd.unexpected_count == 1
    assert "XX" in (rd.unexpected_values or [])


# ─────────────────────────────────────────────────────────────────────
# (c) cast_to_type -- date + integer, asserted identical on both engines.
# ─────────────────────────────────────────────────────────────────────


def test_cast_to_type_date_parity(engine):
    exp = [
        {
            "type": "expect_column_values_to_cast_to_type",
            "kwargs": {
                "column": "d",
                "target_type": "DATE",
                "format": "YYYY-MM-DD",
                "mostly": 1.0,
            },
        }
    ]
    schema = "d string"

    clean = _by_type(
        _run(engine, exp, [("2023-01-15",), ("2024-12-31",), (None,)], schema)
    )
    assert clean["expect_column_values_to_cast_to_type"].success is True
    assert clean["expect_column_values_to_cast_to_type"].unexpected_count == 0

    dirty = _by_type(
        _run(engine, exp, [("2023-01-15",), ("2023-02-30",), ("notadate",)], schema)
    )
    rd = dirty["expect_column_values_to_cast_to_type"]
    assert rd.success is False
    assert rd.unexpected_count == 2


def test_cast_to_type_integer_parity(engine):
    exp = [
        {
            "type": "expect_column_values_to_cast_to_type",
            "kwargs": {"column": "n", "target_type": "INTEGER", "mostly": 1.0},
        }
    ]
    schema = "n string"

    clean = _by_type(_run(engine, exp, [("5",), ("10",), (None,)], schema))
    assert clean["expect_column_values_to_cast_to_type"].success is True
    assert clean["expect_column_values_to_cast_to_type"].unexpected_count == 0

    dirty = _by_type(_run(engine, exp, [("5",), ("x",), ("3.5",)], schema))
    rd = dirty["expect_column_values_to_cast_to_type"]
    assert rd.success is False
    assert rd.unexpected_count == 2


# ─────────────────────────────────────────────────────────────────────
# (c) date-order pair -- asserted identical on both engines.
# ─────────────────────────────────────────────────────────────────────


def test_cross_column_date_order_parity(engine):
    exp = [
        {
            "type": "expect_column_pair_values_a_to_be_greater_than_b",
            "kwargs": {
                "column_A": "end_date",
                "column_B": "start_date",
                "or_equal": True,
            },
        }
    ]
    schema = "start_date date, end_date date"

    clean = _by_type(
        _run(
            engine,
            exp,
            [(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))],
            schema,
        )
    )
    rc = clean["expect_column_pair_values_a_to_be_greater_than_b"]
    assert rc.success is True
    assert rc.unexpected_count == 0

    dirty = _by_type(
        _run(
            engine,
            exp,
            [(datetime.date(2023, 6, 1), datetime.date(2023, 1, 1))],
            schema,
        )
    )
    rd = dirty["expect_column_pair_values_a_to_be_greater_than_b"]
    assert rd.success is False
    assert rd.unexpected_count == 1
    # Cross-engine VALUE parity: both the classic GX add_spark engine and the
    # native Connect path must render partial_unexpected_list as a list of
    # ``[column_A, column_B]`` string pairs (NOT a human-readable "a < b" string).
    # column_A=end_date, column_B=start_date -> the offending row is the single
    # dirty pair. Byte-equal on both engines after the native-path format fix.
    assert rd.unexpected_values == [["2023-01-01", "2023-06-01"]]
