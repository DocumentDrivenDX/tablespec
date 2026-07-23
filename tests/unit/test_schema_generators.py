"""Unit tests for schema generators."""

# @covers US-003-AC1
# @covers US-003-AC2
# @covers US-003-AC3
# @covers US-003-AC4

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings

from tablespec.schemas.generators import (
    generate_json_schema,
    generate_pyspark_schema,
    generate_sql_ddl,
)
from tests.strategies import umf_dict

pytestmark = pytest.mark.no_spark


class TestGenerateSQLDDL:
    """Test SQL DDL generation from UMF."""

    @pytest.fixture
    def minimal_umf(self):
        """Minimal UMF data for testing."""
        return {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {
                    "name": "name",
                    "data_type": "STRING",
                    "max_length": 100,
                    "nullable": True,
                },
            ],
        }

    @pytest.fixture
    def full_umf(self):
        """Full UMF data with all features."""
        return {
            "table_name": "customer_table",
            "description": "Customer information table",
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "INTEGER",
                    "nullable": False,
                    "description": "Unique customer identifier",
                },
                {
                    "name": "customer_name",
                    "data_type": "STRING",
                    "max_length": 255,
                    "nullable": False,
                    "description": "Customer's full name",
                },
                {
                    "name": "balance",
                    "data_type": "DECIMAL",
                    "precision": 10,
                    "scale": 2,
                    "nullable": True,
                    "description": "Account balance",
                },
                {
                    "name": "created_at",
                    "data_type": "TimestampType",
                    "nullable": False,
                },
            ],
            "relationships": {
                "suggested_indexes": [
                    {"name": "idx_customer_name", "columns": ["customer_name"]},
                    {"name": "idx_created_at", "columns": ["created_at"]},
                ]
            },
        }

    def test_generates_basic_ddl(self, minimal_umf):
        """Test basic DDL generation."""
        ddl = generate_sql_ddl(minimal_umf)

        assert "CREATE TABLE test_table" in ddl
        assert "id INTEGER NOT NULL" in ddl
        assert "name STRING" in ddl
        assert ddl.endswith(";")

    def test_includes_table_name(self, minimal_umf):
        """Test table name is included."""
        ddl = generate_sql_ddl(minimal_umf)
        assert "test_table" in ddl

    def test_includes_comments(self, minimal_umf):
        """Test DDL includes header comments."""
        ddl = generate_sql_ddl(minimal_umf)
        assert "-- DDL for test_table" in ddl
        assert "-- Generated from UMF specification" in ddl

    def test_without_source_file_modified_is_deterministic(self):
        """Test repeated renders stay byte-identical without source file metadata."""
        umf = {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {"name": "name", "data_type": "STRING", "nullable": True},
            ],
        }

        ddl1 = generate_sql_ddl(umf)
        ddl2 = generate_sql_ddl(umf)

        assert ddl1 == ddl2
        assert "-- Source file modified:" not in ddl1

    def test_handles_nullable_columns(self, minimal_umf):
        """Test nullable vs NOT NULL columns."""
        ddl = generate_sql_ddl(minimal_umf)
        assert "id INTEGER NOT NULL" in ddl
        # name is nullable, should not have NOT NULL
        assert "name STRING NOT NULL" not in ddl

    def test_string_without_length_defaults_to_string(self):
        """Test STRING column renders as STRING when no length provided."""
        umf = {
            "table_name": "test",
            "columns": [{"name": "text_col", "data_type": "STRING"}],
        }
        ddl = generate_sql_ddl(umf)
        assert "text_col STRING" in ddl

    def test_decimal_with_precision_scale(self, full_umf):
        """Test DECIMAL includes precision and scale."""
        ddl = generate_sql_ddl(full_umf)
        assert "balance DECIMAL(10,2)" in ddl

    def test_column_comments(self, full_umf):
        """Test column descriptions become COMMENT clauses."""
        ddl = generate_sql_ddl(full_umf)
        assert "COMMENT 'Unique customer identifier'" in ddl
        assert "COMMENT 'Customer''s full name'" in ddl  # Check single quote escaping

    def test_table_comment(self, full_umf):
        """Test table description becomes table COMMENT."""
        ddl = generate_sql_ddl(full_umf)
        assert "COMMENT 'Customer information table'" in ddl

    def test_suggested_indexes(self, full_umf):
        """Test suggested indexes are generated."""
        ddl = generate_sql_ddl(full_umf)
        assert "-- Suggested Indexes" in ddl
        assert (
            "CREATE INDEX idx_customer_name ON customer_table (customer_name);" in ddl
        )
        assert "CREATE INDEX idx_created_at ON customer_table (created_at);" in ddl

    def test_no_indexes_when_not_present(self, minimal_umf):
        """Test no index section when indexes not specified."""
        ddl = generate_sql_ddl(minimal_umf)
        assert "CREATE INDEX" not in ddl

    def test_escapes_single_quotes_in_descriptions(self):
        """Test single quotes in descriptions are escaped."""
        umf = {
            "table_name": "test",
            "description": "Table with 'quoted' text",
            "columns": [
                {
                    "name": "col1",
                    "data_type": "STRING",
                    "max_length": 50,
                    "description": "Column with 'quotes'",
                }
            ],
        }
        ddl = generate_sql_ddl(umf)
        assert "Table with ''quoted'' text" in ddl
        assert "Column with ''quotes''" in ddl

    def test_ddl_is_valid_sql(self):
        """Test that generated DDL uses correct UMF types."""
        umf = {
            "table_name": "test_types",
            "description": "Test all UMF type mappings to SQL",
            "columns": [
                {"name": "str_col", "data_type": "VARCHAR", "nullable": False},
                {"name": "int_col", "data_type": "INTEGER", "nullable": True},
                {"name": "datetime_col", "data_type": "DATETIME", "nullable": False},
                {"name": "date_col", "data_type": "DATE", "nullable": True},
                {"name": "bool_col", "data_type": "BOOLEAN", "nullable": True},
                {"name": "float_col", "data_type": "FLOAT", "nullable": True},
                {
                    "name": "decimal_col",
                    "data_type": "DECIMAL",
                    "precision": 10,
                    "scale": 2,
                },
            ],
        }
        ddl = generate_sql_ddl(umf)

        # Verify correct SQL types are present
        assert "STRING" in ddl, f"Expected STRING type in DDL (from VARCHAR): {ddl}"
        assert "INTEGER" in ddl, f"Expected INTEGER type in DDL: {ddl}"
        assert "DATETIME" in ddl, f"Expected DATETIME type in DDL: {ddl}"
        assert "DATE" in ddl, f"Expected DATE type in DDL: {ddl}"
        assert "DECIMAL(10,2)" in ddl, f"Expected DECIMAL(10,2) in DDL: {ddl}"

    def test_ddl_is_parseable_by_sqlglot(self):
        """Test that generated DDL is parseable by sqlglot."""
        sqlglot = pytest.importorskip("sqlglot")

        umf = {
            "table_name": "test_types",
            "description": "Test all UMF type mappings to SQL",
            "columns": [
                {"name": "str_col", "data_type": "VARCHAR", "nullable": False},
                {"name": "int_col", "data_type": "INTEGER", "nullable": True},
                {"name": "datetime_col", "data_type": "DATETIME", "nullable": False},
                {"name": "date_col", "data_type": "DATE", "nullable": True},
                {"name": "bool_col", "data_type": "BOOLEAN", "nullable": True},
                {"name": "float_col", "data_type": "FLOAT", "nullable": True},
                {
                    "name": "decimal_col",
                    "data_type": "DECIMAL",
                    "precision": 10,
                    "scale": 2,
                },
            ],
        }
        ddl = generate_sql_ddl(umf)
        parsed = sqlglot.parse(ddl, read="databricks")
        assert len(parsed) >= 1, "DDL should parse to at least one statement"
        assert parsed[0] is not None, "Parsed statement should not be None"


class TestGeneratePySparkSchema:
    """Test PySpark schema generation from UMF."""

    @pytest.fixture
    def minimal_umf(self):
        """Minimal UMF data for testing."""
        return {
            "table_name": "test_table",
            "canonical_name": "TestTable",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {"name": "name", "data_type": "STRING", "nullable": True},
            ],
        }

    @pytest.fixture
    def full_umf(self):
        """UMF with all data types."""
        return {
            "table_name": "all_types",
            "canonical_name": "AllTypes",
            "columns": [
                {"name": "str_col", "data_type": "STRING"},
                {"name": "int_col", "data_type": "INTEGER"},
                {"name": "long_col", "data_type": "BIGINT"},
                {"name": "float_col", "data_type": "FLOAT"},
                {"name": "double_col", "data_type": "DOUBLE"},
                {"name": "decimal_col", "data_type": "DECIMAL"},
                {"name": "bool_col", "data_type": "BOOLEAN"},
                {"name": "date_col", "data_type": "DateType"},
                {"name": "timestamp_col", "data_type": "TimestampType"},
            ],
        }

    def test_generates_pyspark_schema(self, minimal_umf):
        """Test basic PySpark schema generation."""
        schema = generate_pyspark_schema(minimal_umf)

        assert "from pyspark.sql.types import StructType, StructField" in schema
        assert "test_table_schema = StructType([" in schema
        assert 'StructField("id", IntegerType(), False)' in schema
        assert 'StructField("name", StringType(), True)' in schema

    def test_includes_header_comments(self, minimal_umf):
        """Test schema includes header comments."""
        schema = generate_pyspark_schema(minimal_umf)
        assert "# PySpark Schema for TestTable" in schema
        assert "# Generated from UMF specification" in schema

    def test_without_source_file_modified_is_deterministic(self):
        """Repeated renders stay byte-identical without source file metadata."""
        umf = {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {"name": "name", "data_type": "STRING", "nullable": True},
            ],
        }

        schema1 = generate_pyspark_schema(umf)
        schema2 = generate_pyspark_schema(umf)

        assert schema1 == schema2
        assert "# Source file modified:" not in schema1

    def test_imports_all_types(self, minimal_umf):
        """Test all PySpark type imports are included."""
        schema = generate_pyspark_schema(minimal_umf)
        assert (
            "from pyspark.sql.types import StringType, IntegerType, LongType, DecimalType"
            in schema
        )
        assert (
            "from pyspark.sql.types import FloatType, DoubleType, BooleanType, DateType, TimestampType"
            in schema
        )

    def test_schema_variable_name(self, minimal_umf):
        """Test schema variable name is lowercase table name."""
        schema = generate_pyspark_schema(minimal_umf)
        assert "test_table_schema = StructType([" in schema

    def test_handles_nullable_correctly(self, minimal_umf):
        """Test nullable flag is correctly set."""
        schema = generate_pyspark_schema(minimal_umf)
        assert 'StructField("id", IntegerType(), False)' in schema
        assert 'StructField("name", StringType(), True)' in schema

    def test_all_data_types_mapped(self, full_umf):
        """Test all UMF data types are mapped correctly."""
        schema = generate_pyspark_schema(full_umf)

        assert "StringType()" in schema
        assert "IntegerType()" in schema
        assert "LongType()" in schema
        assert "FloatType()" in schema
        assert "DoubleType()" in schema
        assert "DecimalType()" in schema
        assert "BooleanType()" in schema
        # DATE maps to StringType in PySpark (YYYYMMDD format)
        # We already checked StringType above
        assert "TimestampType()" in schema

    def test_multiple_columns(self, full_umf):
        """Test schema with multiple columns."""
        schema = generate_pyspark_schema(full_umf)

        # Should have 9 StructField definitions in fields + 1 in import = 10
        # Just check that we have the right number of field definitions (9)
        lines = [
            line
            for line in schema.split("\n")
            if line.strip().startswith('StructField("')
        ]
        assert len(lines) == 9

    def test_proper_formatting(self, minimal_umf):
        """Test output is properly formatted Python code."""
        schema = generate_pyspark_schema(minimal_umf)

        # Check indentation
        assert "    StructField" in schema
        # Check closing bracket
        assert "])" in schema
        # Should be valid Python (no syntax errors)
        assert "StructType([" in schema

    def test_embedding_maps_to_array_type(self):
        """Test EMBEDDING columns map to ArrayType(FloatType())."""
        umf = {
            "table_name": "embeddings",
            "canonical_name": "Embeddings",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {
                    "name": "embedding",
                    "data_type": "EMBEDDING",
                    "dimension": 1024,
                    "nullable": False,
                },
            ],
        }

        schema = generate_pyspark_schema(umf)
        assert "ArrayType" in schema
        assert 'StructField("embedding", ArrayType(FloatType()), False)' in schema


class TestGenerateJSONSchema:
    """Test JSON Schema generation from UMF."""

    @pytest.fixture
    def minimal_umf(self):
        """Minimal UMF data for testing."""
        return {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {"name": "name", "data_type": "STRING", "nullable": True},
            ],
        }

    @pytest.fixture
    def full_umf(self):
        """Full UMF with all features."""
        return {
            "table_name": "customer_table",
            "description": "Customer data schema",
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "INTEGER",
                    "nullable": False,
                    "description": "Unique customer ID",
                },
                {
                    "name": "email",
                    "data_type": "STRING",
                    "max_length": 255,
                    "nullable": True,
                    "description": "Customer email address",
                    "sample_values": [
                        "user1@example.com",
                        "user2@example.com",
                        "user3@example.com",
                    ],
                },
                {
                    "name": "balance",
                    "data_type": "DECIMAL",
                    "nullable": True,
                },
            ],
        }

    def test_generates_json_schema(self, minimal_umf):
        """Test basic JSON Schema generation."""
        schema = generate_json_schema(minimal_umf)

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["title"] == "test_table Schema"
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert "name" in schema["properties"]

    def test_uses_table_description(self, full_umf):
        """Test table description is used in schema."""
        schema = generate_json_schema(full_umf)
        assert schema["description"] == "Customer data schema"

    def test_default_description_when_missing(self, minimal_umf):
        """Test default description when not provided."""
        schema = generate_json_schema(minimal_umf)
        assert schema["description"] == "Schema for test_table table"

    def test_column_properties(self, minimal_umf):
        """Test column properties are mapped correctly."""
        schema = generate_json_schema(minimal_umf)

        assert schema["properties"]["id"]["type"] == "integer"
        assert schema["properties"]["name"]["type"] == "string"

    def test_column_descriptions(self, full_umf):
        """Test column descriptions are included."""
        schema = generate_json_schema(full_umf)

        assert (
            schema["properties"]["customer_id"]["description"] == "Unique customer ID"
        )
        assert schema["properties"]["email"]["description"] == "Customer email address"

    def test_required_fields(self, full_umf):
        """Test required fields based on nullable."""
        schema = generate_json_schema(full_umf)

        assert "customer_id" in schema["required"]
        assert "email" not in schema["required"]
        assert "balance" not in schema["required"]

    def test_max_length_constraint(self, full_umf):
        """Test max_length is mapped to maxLength."""
        schema = generate_json_schema(full_umf)

        assert schema["properties"]["email"]["maxLength"] == 255

    def test_sample_values_as_examples(self, full_umf):
        """Test sample_values become examples (limited to 3)."""
        schema = generate_json_schema(full_umf)

        examples = schema["properties"]["email"]["examples"]
        assert len(examples) == 3
        assert "user1@example.com" in examples
        assert "user2@example.com" in examples
        assert "user3@example.com" in examples

    def test_json_schema_is_serializable(self, full_umf):
        """Test generated schema can be serialized to JSON."""
        schema = generate_json_schema(full_umf)

        # Should not raise exception
        json_str = json.dumps(schema, indent=2)
        assert json_str is not None

        # Should be deserializable
        parsed = json.loads(json_str)
        assert parsed["title"] == "customer_table Schema"

    def test_all_data_types_mapped(self):
        """Test all UMF data types map to JSON types."""
        umf = {
            "table_name": "types_test",
            "columns": [
                {"name": "str_col", "data_type": "STRING"},
                {"name": "int_col", "data_type": "INTEGER"},
                {"name": "decimal_col", "data_type": "DECIMAL"},
                {"name": "float_col", "data_type": "FLOAT"},
                {"name": "bool_col", "data_type": "BOOLEAN"},
                {"name": "date_col", "data_type": "DateType"},
            ],
        }

        schema = generate_json_schema(umf)

        assert schema["properties"]["str_col"]["type"] == "string"
        assert schema["properties"]["int_col"]["type"] == "integer"
        assert schema["properties"]["decimal_col"]["type"] == "number"
        assert schema["properties"]["float_col"]["type"] == "number"
        assert schema["properties"]["bool_col"]["type"] == "boolean"
        assert schema["properties"]["date_col"]["type"] == "string"

    def test_empty_required_when_all_nullable(self):
        """Test required array is empty when all columns nullable."""
        umf = {
            "table_name": "test",
            "columns": [
                {"name": "col1", "data_type": "STRING", "nullable": True},
                {"name": "col2", "data_type": "INTEGER", "nullable": True},
            ],
        }

        schema = generate_json_schema(umf)
        assert schema["required"] == []

    def test_embedding_json_schema_dimension(self):
        """Test EMBEDDING columns render array schema with pinned dimension."""
        umf = {
            "table_name": "embeddings",
            "columns": [
                {
                    "name": "embedding",
                    "data_type": "EMBEDDING",
                    "dimension": 1024,
                    "nullable": False,
                }
            ],
        }

        schema = generate_json_schema(umf)
        prop = schema["properties"]["embedding"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "number"}
        assert prop["minItems"] == 1024
        assert prop["maxItems"] == 1024
        assert "embedding" in schema["required"]


class TestPropertyBasedGeneratorsEmbedding:
    """Property-based tests for schema generators using Hypothesis."""

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_sql_ddl_never_crashes_and_returns_nonempty(self, data):
        """Any valid UMF dict produces non-empty SQL DDL without crashing."""
        result = generate_sql_ddl(data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "CREATE TABLE" in result

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_pyspark_schema_never_crashes_and_returns_nonempty(self, data):
        """Any valid UMF dict produces non-empty PySpark schema without crashing."""
        result = generate_pyspark_schema(data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "StructType" in result

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_json_schema_never_crashes_and_returns_valid_json(self, data):
        """Any valid UMF dict produces valid JSON Schema that serializes correctly."""
        result = generate_json_schema(data)
        assert isinstance(result, dict)
        assert "properties" in result
        assert len(result["properties"]) > 0
        # Must be JSON-serializable
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed == result


class TestPropertyBasedGenerators:
    """Property-based tests for schema generators using Hypothesis."""

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_sql_ddl_never_crashes_and_returns_nonempty(self, data):
        """Any valid UMF dict produces non-empty SQL DDL without crashing."""
        result = generate_sql_ddl(data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "CREATE TABLE" in result

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_pyspark_schema_never_crashes_and_returns_nonempty(self, data):
        """Any valid UMF dict produces non-empty PySpark schema without crashing."""
        result = generate_pyspark_schema(data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "StructType" in result

    @given(data=umf_dict())
    @settings(max_examples=50, deadline=None)
    def test_json_schema_never_crashes_and_returns_valid_json(self, data):
        """Any valid UMF dict produces valid JSON Schema that serializes correctly."""
        result = generate_json_schema(data)
        assert isinstance(result, dict)
        assert "properties" in result
        assert len(result["properties"]) > 0
        # Must be JSON-serializable
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed == result
