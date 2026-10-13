"""Test type mapping utilities."""

# @covers US-004-AC1
# @covers US-004-AC2
# @covers US-004-AC3
# @covers US-004-AC4
# @covers US-004-AC5
# @covers US-004-AC6

from __future__ import annotations

import importlib.util

import pytest

from tablespec.type_mappings import (
    VALID_PYSPARK_TYPES,
    map_pyspark_to_sql_type,
    map_to_gx_spark_type,
    map_to_json_type,
    map_to_pyspark_type,
)

try:
    from tablespec.type_mappings import map_to_pyspark_type_obj
except ImportError:
    map_to_pyspark_type_obj = None

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestGXSparkTypeMapping:
    """Test UMF to GX Spark type mapping."""

    def test_string_types(self):
        """Test STRING maps to StringType."""
        assert map_to_gx_spark_type("STRING") == "StringType"
        assert map_to_gx_spark_type("string") == "StringType"

    def test_integer_types(self):
        """Test various integer types map correctly."""
        assert map_to_gx_spark_type("INTEGER") == "IntegerType"
        assert map_to_gx_spark_type("BIGINT") == "LongType"
        assert map_to_gx_spark_type("SMALLINT") == "ShortType"
        assert map_to_gx_spark_type("TINYINT") == "ByteType"

    def test_numeric_types(self):
        """Test decimal and floating point types."""
        assert map_to_gx_spark_type("DECIMAL") == "DecimalType"
        assert map_to_gx_spark_type("FLOAT") == "FloatType"
        assert map_to_gx_spark_type("DOUBLE") == "DoubleType"

    def test_boolean_type(self):
        """Test BOOLEAN maps to BooleanType."""
        assert map_to_gx_spark_type("BOOLEAN") == "BooleanType"

    def test_date_type(self):
        """Test DATE maps to StringType (dates stored as YYYYMMDD strings per ADR-001)."""
        assert map_to_gx_spark_type("DATE") == "StringType"

    def test_timestamp_type(self):
        """Test TIMESTAMP maps to TimestampType."""
        assert map_to_gx_spark_type("TIMESTAMP") == "TimestampType"

    def test_case_insensitive(self):
        """Test that type mapping is case-insensitive."""
        assert map_to_gx_spark_type("integer") == "IntegerType"
        assert map_to_gx_spark_type("Integer") == "IntegerType"
        assert map_to_gx_spark_type("INTEGER") == "IntegerType"

    def test_unknown_type_defaults_to_string(self):
        """Test unknown types default to StringType."""
        assert map_to_gx_spark_type("UNKNOWN_TYPE") == "StringType"
        assert map_to_gx_spark_type("CUSTOM") == "StringType"
        assert map_to_gx_spark_type("") == "StringType"
        assert map_to_gx_spark_type("EMBEDDING") == "ArrayType"

    @pytest.mark.parametrize(
        ("umf_type", "expected_gx_type"),
        [
            ("STRING", "StringType"),
            ("INTEGER", "IntegerType"),
            ("BIGINT", "LongType"),
            ("SMALLINT", "ShortType"),
            ("TINYINT", "ByteType"),
            ("DECIMAL", "DecimalType"),
            ("FLOAT", "FloatType"),
            ("DOUBLE", "DoubleType"),
            ("BOOLEAN", "BooleanType"),
            ("DATE", "StringType"),
            ("DATETIME", "TimestampType"),
            ("TIMESTAMP", "TimestampType"),
            ("EMBEDDING", "ArrayType"),
        ],
    )
    def test_all_supported_mappings(self, umf_type: str, expected_gx_type: str):
        """Test all supported type mappings."""
        assert map_to_gx_spark_type(umf_type) == expected_gx_type


@pytest.mark.skipif(
    not importlib.util.find_spec("pyspark"),
    reason="PySpark not installed",
)
class TestMapToPysparkTypeObj:
    """Test map_to_pyspark_type_obj returns actual PySpark DataType objects."""

    def test_string_types(self):
        """Test STRING maps to StringType instance."""
        from pyspark.sql.types import StringType

        result = map_to_pyspark_type_obj("STRING")
        assert isinstance(result, StringType)

        result = map_to_pyspark_type_obj("StringType")
        assert isinstance(result, StringType)

    def test_integer_types(self):
        """Test integer type mappings return correct instances."""
        from pyspark.sql.types import ByteType, IntegerType, LongType, ShortType

        assert isinstance(map_to_pyspark_type_obj("INTEGER"), IntegerType)
        assert isinstance(map_to_pyspark_type_obj("IntegerType"), IntegerType)
        assert isinstance(map_to_pyspark_type_obj("BIGINT"), LongType)
        assert isinstance(map_to_pyspark_type_obj("LongType"), LongType)
        assert isinstance(map_to_pyspark_type_obj("SMALLINT"), ShortType)
        assert isinstance(map_to_pyspark_type_obj("TINYINT"), ByteType)

    def test_numeric_types(self):
        """Test decimal and floating point type mappings."""
        from pyspark.sql.types import ArrayType, DecimalType, DoubleType, FloatType

        assert isinstance(map_to_pyspark_type_obj("DECIMAL"), DecimalType)
        assert isinstance(map_to_pyspark_type_obj("DecimalType"), DecimalType)
        assert isinstance(map_to_pyspark_type_obj("FLOAT"), FloatType)
        assert isinstance(map_to_pyspark_type_obj("DOUBLE"), DoubleType)
        assert isinstance(map_to_pyspark_type_obj("EMBEDDING"), ArrayType)

    def test_date_and_timestamp_types(self):
        """Test date/timestamp type mappings."""
        from pyspark.sql.types import DateType, TimestampType

        assert isinstance(map_to_pyspark_type_obj("DATE"), DateType)
        assert isinstance(map_to_pyspark_type_obj("DateType"), DateType)
        assert isinstance(map_to_pyspark_type_obj("TIMESTAMP"), TimestampType)
        assert isinstance(map_to_pyspark_type_obj("TimestampType"), TimestampType)

    def test_boolean_type(self):
        """Test boolean type mapping."""
        from pyspark.sql.types import BooleanType

        assert isinstance(map_to_pyspark_type_obj("BOOLEAN"), BooleanType)
        assert isinstance(map_to_pyspark_type_obj("BooleanType"), BooleanType)

    def test_handles_parentheses(self):
        """Test type names with parentheses are handled."""
        from pyspark.sql.types import StringType

        assert isinstance(map_to_pyspark_type_obj("StringType()"), StringType)

    def test_case_insensitive(self):
        """Test type mapping is case-insensitive."""
        from pyspark.sql.types import IntegerType

        assert isinstance(map_to_pyspark_type_obj("integer"), IntegerType)
        assert isinstance(map_to_pyspark_type_obj("Integer"), IntegerType)
        assert isinstance(map_to_pyspark_type_obj("INTEGER"), IntegerType)

    def test_unknown_type_defaults_to_string(self):
        """Test unknown types default to StringType."""
        from pyspark.sql.types import StringType

        assert isinstance(map_to_pyspark_type_obj("UNKNOWN_TYPE"), StringType)
        assert isinstance(map_to_pyspark_type_obj(""), StringType)


class TestMapPysparkToSqlType:
    """Test PySpark type name to SQL type name conversion."""

    @pytest.mark.parametrize(
        ("pyspark_type", "expected_sql"),
        [
            ("StringType", "STRING"),
            ("IntegerType", "INTEGER"),
            ("LongType", "BIGINT"),
            ("ShortType", "SMALLINT"),
            ("ByteType", "TINYINT"),
            ("DecimalType", "DECIMAL"),
            ("FloatType", "FLOAT"),
            ("DoubleType", "DOUBLE"),
            ("BooleanType", "BOOLEAN"),
            ("DateType", "DATE"),
            ("TimestampType", "TIMESTAMP"),
        ],
    )
    def test_pyspark_to_sql_mapping(self, pyspark_type: str, expected_sql: str):
        """Test all PySpark to SQL type conversions."""
        assert map_pyspark_to_sql_type(pyspark_type) == expected_sql

    def test_with_parentheses(self):
        """Test PySpark type names with parentheses are stripped."""
        assert map_pyspark_to_sql_type("StringType()") == "STRING"
        assert map_pyspark_to_sql_type("IntegerType()") == "INTEGER"
        assert map_pyspark_to_sql_type("DecimalType()") == "DECIMAL"

    def test_sql_type_passthrough(self):
        """Test uppercase SQL types pass through unchanged."""
        assert map_pyspark_to_sql_type("STRING") == "STRING"
        assert map_pyspark_to_sql_type("INTEGER") == "INTEGER"
        assert map_pyspark_to_sql_type("DATE") == "DATE"
        assert map_pyspark_to_sql_type("EMBEDDING") == "ARRAY<FLOAT>"

    def test_unknown_type_defaults_to_string(self):
        """Test unrecognized lowercase types default to STRING."""
        assert map_pyspark_to_sql_type("unknown") == "STRING"
        assert map_pyspark_to_sql_type("custom_type") == "STRING"


class TestMapToPysparkType:
    """Test UMF type to PySpark type string (with parentheses) conversion."""

    @pytest.mark.parametrize(
        ("umf_type", "expected"),
        [
            ("VARCHAR", "StringType()"),
            ("STRING", "StringType()"),
            ("INTEGER", "IntegerType()"),
            ("INT", "IntegerType()"),
            ("BIGINT", "LongType()"),
            ("SMALLINT", "ShortType()"),
            ("TINYINT", "ByteType()"),
            ("DECIMAL", "DecimalType()"),
            ("FLOAT", "FloatType()"),
            ("DOUBLE", "DoubleType()"),
            ("BOOLEAN", "BooleanType()"),
            ("DATE", "StringType()"),
            ("DATETIME", "TimestampType()"),
            ("TIMESTAMP", "TimestampType()"),
            ("EMBEDDING", "ArrayType(FloatType())"),
        ],
    )
    def test_sql_style_mappings(self, umf_type: str, expected: str):
        """Test SQL-style UMF type mappings."""
        assert map_to_pyspark_type(umf_type) == expected

    def test_pyspark_type_passthrough(self):
        """Test PySpark type names get parentheses appended."""
        assert map_to_pyspark_type("StringType") == "StringType()"
        assert map_to_pyspark_type("IntegerType") == "IntegerType()"
        assert map_to_pyspark_type("BooleanType") == "BooleanType()"

    def test_pyspark_type_with_parentheses(self):
        """Test PySpark type names already with parentheses are normalized."""
        assert map_to_pyspark_type("StringType()") == "StringType()"
        assert map_to_pyspark_type("IntegerType()") == "IntegerType()"

    def test_case_insensitive_sql(self):
        """Test SQL types are case-insensitive."""
        assert map_to_pyspark_type("varchar") == "StringType()"
        assert map_to_pyspark_type("integer") == "IntegerType()"
        assert map_to_pyspark_type("Integer") == "IntegerType()"

    def test_unknown_defaults_to_string(self):
        """Test unknown types default to StringType()."""
        assert map_to_pyspark_type("UNKNOWN") == "StringType()"
        assert map_to_pyspark_type("") == "StringType()"


class TestGxSparkTypePysparkInput:
    """Test map_to_gx_spark_type with PySpark-style inputs."""

    def test_valid_pyspark_type_passthrough(self):
        """Test valid PySpark type names are returned as-is."""
        assert map_to_gx_spark_type("StringType") == "StringType"
        assert map_to_gx_spark_type("IntegerType") == "IntegerType"
        assert map_to_gx_spark_type("LongType") == "LongType"
        assert map_to_gx_spark_type("DecimalType") == "DecimalType"
        assert map_to_gx_spark_type("BooleanType") == "BooleanType"
        assert map_to_gx_spark_type("TimestampType") == "TimestampType"

    def test_pyspark_type_with_parentheses(self):
        """Test PySpark type names with parentheses are stripped."""
        assert map_to_gx_spark_type("StringType()") == "StringType"
        assert map_to_gx_spark_type("IntegerType()") == "IntegerType"
        assert map_to_gx_spark_type("DateType()") == "DateType"

    def test_varchar_maps_to_string(self):
        """Test VARCHAR maps to StringType."""
        assert map_to_gx_spark_type("VARCHAR") == "StringType"

    def test_int_alias(self):
        """Test INT alias maps to IntegerType."""
        assert map_to_gx_spark_type("INT") == "IntegerType"


class TestValidPysparkTypes:
    """Test the VALID_PYSPARK_TYPES constant."""

    def test_is_frozenset(self):
        """Test VALID_PYSPARK_TYPES is a frozenset."""
        assert isinstance(VALID_PYSPARK_TYPES, frozenset)

    def test_contains_expected_types(self):
        """Test all expected PySpark types are present."""
        expected = {
            "StringType",
            "IntegerType",
            "LongType",
            "ShortType",
            "ByteType",
            "DecimalType",
            "FloatType",
            "DoubleType",
            "BooleanType",
            "DateType",
            "TimestampType",
        }
        assert VALID_PYSPARK_TYPES == expected

    def test_membership(self):
        """Test membership check works."""
        assert "StringType" in VALID_PYSPARK_TYPES
        assert "UnknownType" not in VALID_PYSPARK_TYPES


class TestMapToJsonType:
    """Test UMF to JSON schema type mapping."""

    @pytest.mark.parametrize(
        ("umf_type", "expected"),
        [
            ("VARCHAR", "string"),
            ("STRING", "string"),
            ("INTEGER", "integer"),
            ("INT", "integer"),
            ("BIGINT", "integer"),
            ("DECIMAL", "number"),
            ("FLOAT", "number"),
            ("DOUBLE", "number"),
            ("BOOLEAN", "boolean"),
            ("DATE", "string"),
            ("DATETIME", "string"),
            ("TIMESTAMP", "string"),
            ("EMBEDDING", "array"),
        ],
    )
    def test_all_mappings(self, umf_type: str, expected: str):
        """Test all JSON type mappings."""
        assert map_to_json_type(umf_type) == expected

    def test_case_insensitive(self):
        """Test JSON type mapping is case-insensitive."""
        assert map_to_json_type("integer") == "integer"
        assert map_to_json_type("Boolean") == "boolean"

    def test_unknown_defaults_to_string(self):
        """Test unknown types default to string."""
        assert map_to_json_type("UNKNOWN") == "string"
        assert map_to_json_type("") == "string"
