"""Unit tests for profiling mapper classes."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Check if PySpark is available
try:
    import pyspark  # noqa: F401

    PYSPARK_AVAILABLE = True
except ImportError:
    PYSPARK_AVAILABLE = False


@pytest.fixture
def mock_spark_field():
    """Create a mock Spark StructField."""
    field = MagicMock()
    field.name = "test_column"
    field.nullable = True
    return field


@pytest.fixture
def mock_dataframe():
    """Create a mock Spark DataFrame."""
    df = MagicMock()
    df.schema.fields = []
    return df


@pytest.fixture
def sample_column_profile():
    """Create a sample ColumnProfile for testing."""
    from tablespec.profiling import ColumnProfile

    return ColumnProfile(
        column_name="test_col",
        completeness=0.95,
        approximate_num_distinct=100,
        data_type="String",
        minimum="A",
        maximum="Z",
        mean=50.5,
        standard_deviation=10.2,
    )


@pytest.fixture
def sample_dataframe_profile(sample_column_profile):
    """Create a sample DataFrameProfile for testing."""
    from tablespec.profiling import DataFrameProfile

    return DataFrameProfile(
        num_records=1000,
        columns={"test_col": sample_column_profile},
    )


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
class TestSparkToUmfMapper:
    """Test SparkToUmfMapper class."""

    def test_map_string_type_to_umf(self):
        """Test mapping StringType to UMF VARCHAR."""
        from tablespec.profiling import SparkToUmfMapper

        mapper = SparkToUmfMapper()

        # Mock StringType
        mock_type = MagicMock()
        mock_type.__class__.__name__ = "StringType"

        result = mapper._map_spark_type(mock_type)
        assert result == "VARCHAR"

    def test_map_integer_type_to_umf(self):
        """Test mapping IntegerType to UMF INTEGER."""
        from tablespec.profiling import SparkToUmfMapper

        mapper = SparkToUmfMapper()

        mock_type = MagicMock()
        mock_type.__class__.__name__ = "IntegerType"

        result = mapper._map_spark_type(mock_type)
        assert result == "INTEGER"

    def test_map_decimal_type_with_precision_scale(self):
        """Test mapping DecimalType includes precision and scale."""
        from tablespec.profiling import SparkToUmfMapper

        mapper = SparkToUmfMapper()

        # Mock DecimalType with precision and scale
        from pyspark.sql.types import DecimalType

        mock_field = MagicMock()
        mock_field.name = "price"
        mock_field.nullable = False
        mock_field.dataType = DecimalType(10, 2)

        result = mapper._map_field_to_column(mock_field)

        assert result["name"] == "price"
        assert result["data_type"] == "DECIMAL"
        assert result["precision"] == 10
        assert result["scale"] == 2
        assert result["nullable"] is False

    def test_map_nullable_field(self):
        """Test mapping nullable field preserves nullable flag."""
        from tablespec.profiling import SparkToUmfMapper

        mapper = SparkToUmfMapper()

        mock_field = MagicMock()
        mock_field.name = "optional_col"
        mock_field.nullable = True
        mock_field.dataType = MagicMock(__class__=type("StringType", (), {}))

        result = mapper._map_field_to_column(mock_field)

        assert result["nullable"] is True

    def test_unknown_spark_type_defaults_to_varchar(self):
        """Test unknown Spark types default to VARCHAR."""
        from tablespec.profiling import SparkToUmfMapper

        mapper = SparkToUmfMapper()

        # Mock unknown type
        mock_type = MagicMock()
        mock_type.__class__.__name__ = "UnknownCustomType"

        result = mapper._map_spark_type(mock_type)
        assert result == "VARCHAR"

    def test_map_dataframe_to_umf_structure(self, mock_dataframe):
        """Test complete DataFrame to UMF conversion structure."""
        from tablespec.profiling import SparkToUmfMapper

        # Mock schema with multiple fields
        field1 = MagicMock()
        field1.name = "id"
        field1.nullable = False
        field1.dataType = MagicMock(__class__=type("IntegerType", (), {}))

        field2 = MagicMock()
        field2.name = "name"
        field2.nullable = True
        field2.dataType = MagicMock(__class__=type("StringType", (), {}))

        mock_dataframe.schema.fields = [field1, field2]

        mapper = SparkToUmfMapper()
        result = mapper.map_dataframe_to_umf(mock_dataframe, "test_table", "source")

        assert result["table_name"] == "test_table"
        assert result["table_type"] == "source"
        assert len(result["columns"]) == 2
        assert result["columns"][0]["name"] == "id"
        assert result["columns"][1]["name"] == "name"
