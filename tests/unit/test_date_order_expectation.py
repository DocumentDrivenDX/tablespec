"""Tests for ExpectColumnPairDateOrder custom GX expectation.

Uses the standalone validate_column_pair_date_order() function to test
date ordering validation logic. Requires a Spark/Sail session since the
function operates on PySpark DataFrames.
"""

from __future__ import annotations

import warnings

import pytest

try:
    from pysail.spark import SparkConnectServer

    # Use the Spark CONNECT builder (not the top-level remote().getOrCreate(),
    # which raises SESSION_ALREADY_EXIST when a classic JVM session is active in
    # the same process, e.g. during the full `make test` run).
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False

pytestmark = [
    pytest.mark.no_spark,  # Sail needs no JVM/JAVA_HOME; skip classic-Spark setup.
    pytest.mark.skipif(not _HAS_SAIL, reason="pysail not available"),
]


@pytest.fixture(scope="module")
def spark():
    """Create a lightweight Sail (Spark Connect) session for testing."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address
        session = (
            RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
            .appName("test-date-order")
            .create()
        )
        yield session
        session.stop()
        server.stop()


from tablespec.validation.custom_gx_expectations import validate_column_pair_date_order  # noqa: E402


class TestDateOrderValid:
    """Tests for valid date ordering (end_date >= start_date)."""

    def test_end_after_start(self, spark):
        """End dates after start dates should pass."""
        df = spark.createDataFrame(
            [
                ("2024-01-01", "2024-01-31"),
                ("2024-03-15", "2024-04-15"),
                ("2024-06-01", "2024-12-31"),
            ],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert result["success"]
        assert result["result"]["unexpected_count"] == 0

    def test_equal_dates_pass_with_or_equal(self, spark):
        """Equal dates should pass when or_equal=True (default)."""
        df = spark.createDataFrame(
            [("2024-01-01", "2024-01-01"), ("2024-06-15", "2024-06-15")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(
            df, "end_date", "start_date", or_equal=True
        )
        assert result["success"]
        assert result["result"]["unexpected_count"] == 0

    def test_equal_dates_fail_without_or_equal(self, spark):
        """Equal dates should fail when or_equal=False (strict >)."""
        df = spark.createDataFrame(
            [("2024-01-01", "2024-01-01")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(
            df, "end_date", "start_date", or_equal=False
        )
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 1


class TestDateOrderViolations:
    """Tests for violated date ordering."""

    def test_end_before_start_fails(self, spark):
        """End date before start date should fail."""
        df = spark.createDataFrame(
            [("2024-06-01", "2024-01-01")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 1

    def test_mixed_valid_and_invalid(self, spark):
        """Mix of valid and invalid orderings should fail."""
        df = spark.createDataFrame(
            [
                ("2024-01-01", "2024-12-31"),
                ("2024-06-01", "2024-01-01"),
                ("2024-03-01", "2024-09-30"),
            ],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 1

    def test_all_violations(self, spark):
        """All rows violated should report all as unexpected."""
        df = spark.createDataFrame(
            [("2024-12-01", "2024-01-01"), ("2024-06-15", "2024-01-01")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 2

    def test_unexpected_values_in_result(self, spark):
        """Partial unexpected list mirrors GX add_spark: a list of [A, B] string pairs.

        The native column-pair validator renders each offending row as a
        ``[value_column, reference_column]`` (= ``[column_A, column_B]``) pair of
        stringified values so the Connect path is byte-equal with GX's classic
        ``add_spark`` ``partial_unexpected_list`` (cross-engine parity, see
        ``tests/unit/test_custom_gx_parity.py``).
        """
        df = spark.createDataFrame(
            [("2024-06-01", "2024-01-01")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        pul = result["result"]["partial_unexpected_list"]
        assert len(pul) == 1
        # value_column=end_date="2024-01-01", reference_column=start_date="2024-06-01"
        assert pul[0] == ["2024-01-01", "2024-06-01"]


class TestDateOrderNulls:
    """Tests for NULL handling in date ordering."""

    def test_null_end_date_skipped(self, spark):
        """Rows with NULL end_date should be skipped (valid)."""
        df = spark.createDataFrame(
            [("2024-01-01", None), ("2024-03-01", "2024-06-01")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert result["success"]
        assert result["result"]["element_count"] == 1

    def test_null_start_date_skipped(self, spark):
        """Rows with NULL start_date should be skipped (valid)."""
        df = spark.createDataFrame(
            [(None, "2024-06-01"), ("2024-01-01", "2024-12-31")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert result["success"]
        assert result["result"]["element_count"] == 1

    def test_both_null_skipped(self, spark):
        """Rows with both dates NULL should be skipped."""
        # Explicit schema: Spark Connect's createDataFrame cannot infer types
        # from all-None rows (CANNOT_DETERMINE_TYPE), so name the columns.
        df = spark.createDataFrame(
            [(None, None), (None, None)],
            "start_date string, end_date string",
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert result["success"]
        assert result["result"]["element_count"] == 0

    def test_all_null_column(self, spark):
        """All-null columns should pass (nothing to validate)."""
        # Explicit schema: Spark Connect's createDataFrame cannot infer types
        # from all-None rows (CANNOT_DETERMINE_TYPE), so name the columns.
        df = spark.createDataFrame(
            [(None, None), (None, None), (None, None)],
            "start_date string, end_date string",
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert result["success"]
        assert result["result"]["element_count"] == 0


class TestDateOrderMostly:
    """Tests for the 'mostly' threshold parameter."""

    def test_mostly_threshold_passes(self, spark):
        """Should pass when enough pairs satisfy the ordering."""
        # 2 out of 3 valid = 66.7%
        df = spark.createDataFrame(
            [
                ("2024-01-01", "2024-12-31"),
                ("2024-06-01", "2024-01-01"),
                ("2024-03-01", "2024-09-30"),
            ],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(
            df, "end_date", "start_date", mostly=0.6
        )
        assert result["success"]

    def test_mostly_threshold_fails(self, spark):
        """Should fail when not enough pairs satisfy the ordering."""
        # 1 out of 3 valid = 33.3%
        df = spark.createDataFrame(
            [
                ("2024-01-01", "2024-12-31"),
                ("2024-06-01", "2024-01-01"),
                ("2024-09-01", "2024-03-01"),
            ],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(
            df, "end_date", "start_date", mostly=0.5
        )
        assert not result["success"]


class TestDateOrderEdgeCases:
    """Tests for edge cases."""

    def test_result_structure(self, spark):
        """Result should contain standard GX result keys."""
        df = spark.createDataFrame(
            [("2024-01-01", "2024-12-31")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert "success" in result
        assert "result" in result
        inner = result["result"]
        assert "element_count" in inner
        assert "unexpected_count" in inner
        assert "unexpected_percent" in inner
        assert "partial_unexpected_list" in inner
        assert "observed_value" in inner

    def test_observed_value_contains_column_names(self, spark):
        """Observed value should reference column names."""
        df = spark.createDataFrame(
            [("2024-01-01", "2024-12-31")],
            ["start_date", "end_date"],
        )
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert "end_date" in result["result"]["observed_value"]
        assert "start_date" in result["result"]["observed_value"]

    def test_unexpected_values_limited_to_10(self, spark):
        """Partial unexpected list should be limited to 10 items."""
        rows = [(f"2024-12-{i + 1:02d}", f"2024-01-{i + 1:02d}") for i in range(20)]
        df = spark.createDataFrame(rows, ["start_date", "end_date"])
        result = validate_column_pair_date_order(df, "end_date", "start_date")
        assert not result["success"]
        assert len(result["result"]["partial_unexpected_list"]) <= 10
