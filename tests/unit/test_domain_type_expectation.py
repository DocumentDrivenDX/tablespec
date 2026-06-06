"""Tests for ExpectColumnValuesToMatchDomainType custom GX expectation.

Uses the standalone validate_domain_type() function to test domain type
validation logic. Requires a Spark/Sail session since the function
operates on PySpark DataFrames.
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
            .appName("test-domain-type")
            .create()
        )
        yield session
        session.stop()
        server.stop()


from tablespec.validation.custom_gx_expectations import (  # noqa: E402
    validate_domain_type as _validate_domain_type_pandas,
)


# NOTE: validate_domain_type() is a PANDAS-based shim (it uses df[col].dropna(),
# .astype, .isin, etc.). It is NOT Spark-Connect-compatible: a Spark Connect
# DataFrame's df[col] returns a Column, not a pandas Series. The production GX
# custom-expectation path (ExpectColumnValuesToMatchDomainType._validate) already
# materializes the batch via toPandas() before calling this function, so we mirror
# that boundary here. Making the GX custom expectations run natively on Spark
# Connect (GX-on-serverless) is a separate, much larger effort and is future work.
def validate_domain_type(df, column, domain_type_name, mostly=1.0):
    """Materialize the Spark(/Sail) DataFrame to pandas, then validate.

    Mirrors the production toPandas() boundary in
    ExpectColumnValuesToMatchDomainType._validate so the standalone pandas shim
    receives the pandas frame it expects.
    """
    return _validate_domain_type_pandas(df.toPandas(), column, domain_type_name, mostly)


class TestDomainTypeExpectationValueSet:
    """Tests for domain types validated via value_set (e.g., us_state_code, gender)."""

    def test_valid_state_codes(self, spark):
        """All valid US state codes should pass."""
        df = spark.createDataFrame([("MD",), ("CA",), ("NY",), ("TX",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert result["success"]
        assert result["result"]["unexpected_count"] == 0

    def test_invalid_state_code(self, spark):
        """Invalid state code should fail."""
        df = spark.createDataFrame([("MD",), ("XX",), ("NY",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 1
        assert "XX" in result["result"]["partial_unexpected_list"]

    def test_all_invalid_state_codes(self, spark):
        """All invalid state codes should report all as unexpected."""
        df = spark.createDataFrame([("XX",), ("ZZ",), ("QQ",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 3

    def test_valid_gender_codes(self, spark):
        """Valid gender codes should pass."""
        df = spark.createDataFrame([("M",), ("F",), ("U",), ("N",)], ["gender"])
        result = validate_domain_type(df, "gender", "gender")
        assert result["success"]

    def test_invalid_gender_code(self, spark):
        """Invalid gender code should fail."""
        df = spark.createDataFrame([("M",), ("X",)], ["gender"])
        result = validate_domain_type(df, "gender", "gender")
        assert not result["success"]

    def test_valid_lob_codes(self, spark):
        """Valid line of business codes should pass."""
        df = spark.createDataFrame(
            [("MEDICAID",), ("MEDICARE",), ("MD",), ("ME",)], ["lob"]
        )
        result = validate_domain_type(df, "lob", "lob")
        assert result["success"]

    def test_valid_yes_no_flags(self, spark):
        """Valid Y/N flags should pass."""
        df = spark.createDataFrame([("Y",), ("N",), ("Y",), ("N",)], ["flag"])
        result = validate_domain_type(df, "flag", "yes_no_flag")
        assert result["success"]


class TestDomainTypeExpectationRegex:
    """Tests for domain types validated via regex (e.g., email, npi, zip_code)."""

    def test_valid_emails(self, spark):
        """Valid email addresses should pass."""
        df = spark.createDataFrame(
            [("user@example.com",), ("test@test.org",)], ["email"]
        )
        result = validate_domain_type(df, "email", "email")
        assert result["success"]

    def test_invalid_email(self, spark):
        """Invalid email should fail."""
        df = spark.createDataFrame(
            [("user@example.com",), ("not-an-email",)], ["email"]
        )
        result = validate_domain_type(df, "email", "email")
        assert not result["success"]
        assert result["result"]["unexpected_count"] == 1

    def test_valid_npi(self, spark):
        """Valid 10-digit NPIs should pass."""
        df = spark.createDataFrame([("1234567890",), ("9876543210",)], ["npi"])
        result = validate_domain_type(df, "npi", "npi")
        assert result["success"]

    def test_invalid_npi(self, spark):
        """Short NPI should fail."""
        df = spark.createDataFrame([("1234567890",), ("12345",)], ["npi"])
        result = validate_domain_type(df, "npi", "npi")
        assert not result["success"]

    def test_valid_zip_codes(self, spark):
        """Valid ZIP codes should pass."""
        df = spark.createDataFrame([("12345",), ("98765-4321",)], ["zip"])
        result = validate_domain_type(df, "zip", "zip_code")
        assert result["success"]

    def test_invalid_zip_code(self, spark):
        """Invalid ZIP code should fail."""
        df = spark.createDataFrame([("12345",), ("ABC",)], ["zip"])
        result = validate_domain_type(df, "zip", "zip_code")
        assert not result["success"]

    def test_valid_phone_numbers(self, spark):
        """Valid phone number formats should pass."""
        df = spark.createDataFrame(
            [("5551234567",), ("555-123-4567",), ("(555) 123-4567",)], ["phone"]
        )
        result = validate_domain_type(df, "phone", "phone_number")
        assert result["success"]


class TestDomainTypeExpectationLengthBased:
    """Tests for domain types validated via length constraints."""

    def test_valid_address(self, spark):
        """Valid address lengths should pass."""
        df = spark.createDataFrame([("123 Main St",), ("456 Oak Ave",)], ["addr"])
        result = validate_domain_type(df, "addr", "address_line_1")
        assert result["success"]

    def test_empty_address_fails(self, spark):
        """Empty string address should fail (min_value=1)."""
        df = spark.createDataFrame([("123 Main St",), ("",)], ["addr"])
        result = validate_domain_type(df, "addr", "address_line_1")
        assert not result["success"]


class TestDomainTypeExpectationMostly:
    """Tests for the 'mostly' threshold parameter."""

    def test_mostly_threshold_passes(self, spark):
        """Should pass when enough values match the mostly threshold."""
        # 3 out of 4 valid = 75%
        df = spark.createDataFrame([("MD",), ("CA",), ("NY",), ("XX",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code", mostly=0.7)
        assert result["success"]

    def test_mostly_threshold_fails(self, spark):
        """Should fail when not enough values match the mostly threshold."""
        # 1 out of 4 valid = 25%
        df = spark.createDataFrame([("MD",), ("XX",), ("ZZ",), ("QQ",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code", mostly=0.5)
        assert not result["success"]


class TestDomainTypeExpectationEdgeCases:
    """Tests for edge cases and error handling."""

    def test_all_null_column(self, spark):
        """Column with all nulls should pass (nothing to validate)."""
        # Explicit DDL schema: Spark Connect's createDataFrame cannot infer a
        # type from all-None rows (CANNOT_DETERMINE_TYPE), so declare it string.
        df = spark.createDataFrame([(None,), (None,), (None,)], "state string")
        result = validate_domain_type(df, "state", "us_state_code")
        assert result["success"]
        assert result["result"]["element_count"] == 0

    def test_mixed_nulls_and_valid(self, spark):
        """Nulls should be excluded from validation; valid values pass."""
        df = spark.createDataFrame([("MD",), (None,), ("CA",), (None,)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert result["success"]
        assert result["result"]["element_count"] == 2

    def test_unknown_domain_type(self, spark):
        """Unknown domain type should fail with descriptive message."""
        df = spark.createDataFrame([("a",), ("b",)], ["col"])
        result = validate_domain_type(df, "col", "nonexistent_domain_type")
        assert not result["success"]
        assert "not found" in result["result"]["observed_value"]

    def test_result_structure(self, spark):
        """Result should contain standard GX result keys."""
        df = spark.createDataFrame([("MD",)], ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert "success" in result
        assert "result" in result
        inner = result["result"]
        assert "element_count" in inner
        assert "unexpected_count" in inner
        assert "unexpected_percent" in inner
        assert "partial_unexpected_list" in inner
        assert "observed_value" in inner

    def test_unexpected_values_limited_to_10(self, spark):
        """Partial unexpected list should be limited to 10 items."""
        # Create 20 invalid values
        rows = [(f"X{i}",) for i in range(20)]
        df = spark.createDataFrame(rows, ["state"])
        result = validate_domain_type(df, "state", "us_state_code")
        assert not result["success"]
        assert len(result["result"]["partial_unexpected_list"]) <= 10


class TestDomainTypeExpectationMultipleValidations:
    """Tests for domain types with multiple validation rules."""

    def test_calendar_year_valid(self, spark):
        """Valid calendar years should pass both type and range checks."""
        df = spark.createDataFrame([(2020,), (2021,), (2025,)], ["year"])
        result = validate_domain_type(df, "year", "calendar_year")
        assert result["success"]

    def test_calendar_year_out_of_range(self, spark):
        """Calendar year outside 1900-2100 should fail."""
        df = spark.createDataFrame([(2020,), (1800,)], ["year"])
        result = validate_domain_type(df, "year", "calendar_year")
        assert not result["success"]
