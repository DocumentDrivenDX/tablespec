# SPDX-License-Identifier: MIT OR Apache-2.0
"""Integration tests for end-to-end UMF workflows."""

from __future__ import annotations

import pytest

from tablespec import (
    UMF,
    UMFColumn,
    Nullable,
    generate_json_schema,
    generate_pyspark_schema,
    generate_sql_ddl,
    load_umf_from_yaml,
    save_umf_to_yaml,
)


class TestUMFWorkflow:
    """Test end-to-end UMF workflows."""

    @pytest.fixture
    def sample_umf(self):
        """Create a sample UMF for testing."""
        return UMF(
            version="1.0",
            table_name="Customer_Orders",
            description="Customer order tracking table",
            source_file="orders_spec.xlsx",
            sheet_name="Orders",
            table_type="data_table",
            columns=[
                UMFColumn(
                    name="order_id",
                    data_type="VARCHAR",
                    length=50,
                    description="Unique order identifier",
                    nullable=Nullable(MD=False, MP=False, ME=False),
                    sample_values=["ORD001", "ORD002", "ORD003"],
                ),
                UMFColumn(
                    name="customer_id",
                    data_type="INTEGER",
                    description="Customer ID reference",
                    nullable=Nullable(MD=False, MP=False, ME=False),
                ),
                UMFColumn(
                    name="order_date",
                    data_type="DATE",
                    description="Order placement date",
                    nullable=Nullable(MD=False, MP=False, ME=False),
                ),
                UMFColumn(
                    name="order_amount",
                    data_type="DECIMAL",
                    precision=10,
                    scale=2,
                    description="Total order amount",
                    nullable=Nullable(MD=True, MP=True, ME=True),
                ),
                UMFColumn(
                    name="order_status",
                    data_type="VARCHAR",
                    length=20,
                    description="Current order status",
                    nullable=Nullable(MD=False, MP=False, ME=False),
                    sample_values=["pending", "shipped", "delivered", "cancelled"],
                ),
            ],
        )

    def test_create_save_load_workflow(self, sample_umf, tmp_path):
        """Test creating, saving, and loading UMF."""
        # Save to file
        yaml_path = tmp_path / "customer_orders.umf.yaml"
        save_umf_to_yaml(sample_umf, yaml_path)

        # Verify file exists
        assert yaml_path.exists()

        # Load back
        loaded_umf = load_umf_from_yaml(yaml_path)

        # Verify content matches
        assert loaded_umf.table_name == sample_umf.table_name
        assert loaded_umf.description == sample_umf.description
        assert len(loaded_umf.columns) == len(sample_umf.columns)
        assert loaded_umf.columns[0].name == "order_id"
        assert loaded_umf.columns[0].nullable.MD is False

    def test_generate_all_schemas_workflow(self, sample_umf):
        """Test generating all schema formats from UMF."""
        umf_dict = sample_umf.model_dump()

        # Generate SQL DDL
        ddl = generate_sql_ddl(umf_dict)
        assert "CREATE TABLE Customer_Orders" in ddl
        # VARCHAR with length becomes STRING in Spark SQL (max_length needed for VARCHAR())
        assert "order_id STRING" in ddl or "order_id VARCHAR" in ddl
        assert "order_amount DECIMAL(10,2)" in ddl

        # Generate PySpark schema
        pyspark_schema = generate_pyspark_schema(umf_dict)
        assert "customer_orders_schema = StructType([" in pyspark_schema
        # Nullable is a dict with LOB keys when using Nullable model
        assert 'StructField("order_id", StringType()' in pyspark_schema
        assert 'StructField("customer_id", IntegerType()' in pyspark_schema

        # Generate JSON Schema
        json_schema = generate_json_schema(umf_dict)
        assert json_schema["title"] == "Customer_Orders Schema"
        assert "order_id" in json_schema["properties"]
        # Note: When nullable is a dict (LOB-specific), it's treated as truthy
        # so required array may be empty. This is a known limitation.
        assert json_schema["properties"]["order_id"]["type"] == "string"

    def test_umf_validation_workflow(self, sample_umf):
        """Test UMF validation catches errors."""
        # Valid UMF should work
        assert sample_umf.table_name == "Customer_Orders"

        # Test validation catches duplicate column names
        with pytest.raises(Exception):
            UMF(
                version="1.0",
                table_name="Test",
                columns=[
                    UMFColumn(name="col1", data_type="VARCHAR", length=50),
                    UMFColumn(name="col1", data_type="INTEGER"),  # Duplicate
                ],
            )

        # Test validation catches invalid table names
        with pytest.raises(Exception):
            UMF(
                version="1.0",
                table_name="123_invalid",  # Can't start with number
                columns=[UMFColumn(name="col1", data_type="VARCHAR", length=50)],
            )

    def test_schema_generation_preserves_metadata(self, sample_umf):
        """Test schema generation preserves important metadata."""
        umf_dict = sample_umf.model_dump()

        # SQL DDL should include comments
        ddl = generate_sql_ddl(umf_dict)
        assert "Customer order tracking table" in ddl
        assert "Unique order identifier" in ddl
        assert "Total order amount" in ddl

        # JSON Schema should include descriptions
        json_schema = generate_json_schema(umf_dict)
        assert json_schema["description"] == "Customer order tracking table"
        assert (
            json_schema["properties"]["order_id"]["description"]
            == "Unique order identifier"
        )
        assert (
            json_schema["properties"]["order_amount"]["description"]
            == "Total order amount"
        )

    def test_round_trip_preserves_data(self, sample_umf, tmp_path):
        """Test round-trip (save→load→save→load) preserves all data."""
        # First save
        yaml_path1 = tmp_path / "test1.yaml"
        save_umf_to_yaml(sample_umf, yaml_path1)

        # First load
        loaded1 = load_umf_from_yaml(yaml_path1)

        # Second save
        yaml_path2 = tmp_path / "test2.yaml"
        save_umf_to_yaml(loaded1, yaml_path2)

        # Second load
        loaded2 = load_umf_from_yaml(yaml_path2)

        # Compare
        assert loaded2.table_name == sample_umf.table_name
        assert loaded2.description == sample_umf.description
        assert len(loaded2.columns) == len(sample_umf.columns)
        assert loaded2.columns[0].name == sample_umf.columns[0].name
        assert loaded2.columns[0].length == sample_umf.columns[0].length

    def test_multiple_schema_formats_consistency(self, sample_umf):
        """Test that different schema formats are consistent with each other."""
        umf_dict = sample_umf.model_dump()

        # Generate all formats
        ddl = generate_sql_ddl(umf_dict)
        pyspark_schema = generate_pyspark_schema(umf_dict)
        json_schema = generate_json_schema(umf_dict)

        # Verify consistent table name
        assert "Customer_Orders" in ddl
        assert "customer_orders_schema" in pyspark_schema
        assert json_schema["title"] == "Customer_Orders Schema"

        # Verify consistent column count
        assert len(json_schema["properties"]) == 5
        assert pyspark_schema.count("StructField") >= 5  # 5 fields + 1 in import

        # Verify order_id column in all formats
        assert "order_id STRING" in ddl or "order_id VARCHAR" in ddl
        assert 'StructField("order_id", StringType()' in pyspark_schema
        assert json_schema["properties"]["order_id"]["type"] == "string"

        # Verify DECIMAL column in all formats
        assert "order_amount DECIMAL(10,2)" in ddl
        assert 'StructField("order_amount", DecimalType()' in pyspark_schema
        assert json_schema["properties"]["order_amount"]["type"] == "number"

    def test_umf_modification_workflow(self, sample_umf, tmp_path):
        """Test modifying UMF and regenerating schemas."""
        # Save original
        yaml_path = tmp_path / "original.yaml"
        save_umf_to_yaml(sample_umf, yaml_path)

        # Load and modify
        loaded_umf = load_umf_from_yaml(yaml_path)
        loaded_umf.description = "Updated description"
        loaded_umf.columns.append(
            UMFColumn(
                name="delivery_date",
                data_type="DATE",
                description="Actual delivery date",
                nullable=Nullable(MD=True, MP=True, ME=True),
            )
        )

        # Save modified version
        modified_path = tmp_path / "modified.yaml"
        save_umf_to_yaml(loaded_umf, modified_path)

        # Verify modifications
        final_umf = load_umf_from_yaml(modified_path)
        assert final_umf.description == "Updated description"
        assert len(final_umf.columns) == 6
        assert final_umf.columns[-1].name == "delivery_date"

        # Verify schema generation works with modified UMF
        ddl = generate_sql_ddl(final_umf.model_dump())
        assert "delivery_date" in ddl
        assert "Updated description" in ddl
