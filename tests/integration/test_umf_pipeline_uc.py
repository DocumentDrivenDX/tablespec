"""Integration tests: UMF import → sample data generation → validation pipeline.

Tests the full end-to-end pipeline using Unity Catalog sample tables:
  1. Infer UMF schema from a real Spark DataFrame
  2. Enrich with profiling stats and sample values
  3. Generate synthetic data from the UMF spec
  4. Validate the generated data matches the UMF contract

Requires:
    - Databricks runtime with access to `samples` catalog
    - tablespec[spark] installed

These tests validate that the pipeline generalizes across different
table structures (string-heavy, numeric, temporal, mixed).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# Skip entire module if not on Databricks with samples catalog access
pytestmark = pytest.mark.skipif(
    "DATABRICKS_RUNTIME_VERSION" not in os.environ,
    reason="Requires Databricks runtime with UC samples catalog",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def spark():
    """Get the active Databricks Spark session."""
    from tablespec.spark_factory import create_delta_spark_session

    return create_delta_spark_session("pipeline-test")


# Spark type -> UMF type mapping
SPARK_TO_UMF_TYPE = {
    "StringType": "VARCHAR",
    "IntegerType": "INTEGER",
    "LongType": "INTEGER",
    "ShortType": "INTEGER",
    "ByteType": "INTEGER",
    "DoubleType": "FLOAT",
    "FloatType": "FLOAT",
    "BooleanType": "BOOLEAN",
    "DateType": "DATE",
    "TimestampType": "TIMESTAMP",
    "TimestampNTZType": "TIMESTAMP",
    "DecimalType": "DECIMAL",
}


def spark_df_to_enriched_umf(df, table_name, spark_session, sample_size=5):
    """Convert a Spark DataFrame to a fully enriched UMF model object.

    Includes schema inference, sample values, and profiling statistics.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.types import DecimalType

    from tablespec import UMF, UMFColumn
    from tablespec.models.umf import Nullable

    num_records = df.count()
    columns = []

    for field in df.schema.fields:
        type_name = type(field.dataType).__name__
        umf_type = SPARK_TO_UMF_TYPE.get(type_name, "VARCHAR")

        # Sample values
        sample_rows = (
            df.select(F.col(f"`{field.name}`"))
            .where(F.col(f"`{field.name}`").isNotNull())
            .limit(sample_size)
            .collect()
        )
        sample_values = [str(row[0]) for row in sample_rows]

        # Profiling
        non_null = df.where(F.col(f"`{field.name}`").isNotNull()).count()
        completeness = non_null / num_records if num_records > 0 else 0.0
        approx_distinct = df.select(
            F.approx_count_distinct(F.col(f"`{field.name}`"))
        ).collect()[0][0]

        profiling_data: dict[str, Any] = {
            "completeness": completeness,
            "num_records": num_records,
            "approximate_num_distinct": approx_distinct,
        }

        if any(
            t in type_name.lower()
            for t in ["int", "long", "double", "decimal", "float", "short"]
        ):
            stats = df.select(
                F.min(F.col(f"`{field.name}`")).cast("double").alias("mn"),
                F.max(F.col(f"`{field.name}`")).cast("double").alias("mx"),
                F.avg(F.col(f"`{field.name}`").cast("double")).alias("av"),
                F.stddev(F.col(f"`{field.name}`").cast("double")).alias("sd"),
            ).collect()[0]
            profiling_data["statistics"] = {
                "min": stats["mn"],
                "max": stats["mx"],
                "mean": round(stats["av"], 4) if stats["av"] else None,
                "stddev": round(stats["sd"], 4) if stats["sd"] else None,
            }

        if "string" in type_name.lower():
            lens = df.select(
                F.min(F.length(F.col(f"`{field.name}`"))).alias("mn"),
                F.max(F.length(F.col(f"`{field.name}`"))).alias("mx"),
            ).collect()[0]
            profiling_data["string_lengths"] = {
                "min_length": lens["mn"],
                "max_length": lens["mx"],
            }

        col = UMFColumn(
            name=field.name,
            data_type=umf_type,
            description=f"{field.name} column",
            nullable=Nullable(source=field.nullable) if field.nullable else None,
            sample_values=sample_values,
            profiling=profiling_data,
        )

        if isinstance(field.dataType, DecimalType):
            col.precision = field.dataType.precision
            col.scale = field.dataType.scale

        columns.append(col)

    return UMF(
        version="1.0",
        table_name=table_name,
        description=f"Auto-profiled from Spark DataFrame ({num_records} rows)",
        columns=columns,
    )


def validate_generated_data(output_dir: Path, umf_specs: dict) -> dict[str, dict]:
    """Validate generated data against UMF specs.

    Returns a dict of {table_name: {check_name: bool}} results.
    """
    results = {}
    generated_files = [f for f in sorted(output_dir.rglob("*.txt")) if f.is_file()]

    for f in generated_files:
        table_name = f.stem
        if table_name not in umf_specs:
            continue

        lines = f.read_text().splitlines()
        header = lines[0].split("|")
        rows = [line.split("|") for line in lines[1:]]
        umf_obj = umf_specs[table_name]

        checks = {
            "has_rows": len(rows) > 0,
            "has_expected_row_count": len(rows) >= 50,  # config.num_members
            "columns_match": sorted(header) == sorted(c.name for c in umf_obj.columns),
            "rows_consistent_width": all(len(r) == len(header) for r in rows),
        }

        # Type validation
        type_errors = []
        for col_idx, col_name in enumerate(header):
            umf_col = next((c for c in umf_obj.columns if c.name == col_name), None)
            if not umf_col:
                continue
            col_values = [
                row[col_idx]
                for row in rows
                if col_idx < len(row) and row[col_idx].strip()
            ]
            if not col_values:
                continue

            if umf_col.data_type == "INTEGER":
                for v in col_values[:30]:
                    try:
                        int(v)
                    except ValueError:
                        type_errors.append(f"{col_name}: non-integer '{v}'")
                        break

            elif umf_col.data_type in ("FLOAT", "DECIMAL"):
                for v in col_values[:30]:
                    try:
                        float(v)
                    except ValueError:
                        type_errors.append(f"{col_name}: non-numeric '{v}'")
                        break

            elif umf_col.data_type == "DATE":
                for v in col_values[:30]:
                    try:
                        datetime.strptime(v, "%Y-%m-%d")
                    except ValueError:
                        type_errors.append(f"{col_name}: invalid date '{v}'")
                        break

            elif umf_col.data_type == "TIMESTAMP":
                for v in col_values[:30]:
                    try:
                        datetime.fromisoformat(v.replace(" ", "T"))
                    except ValueError:
                        type_errors.append(f"{col_name}: invalid timestamp '{v}'")
                        break

        checks["type_validation_pass"] = len(type_errors) == 0
        checks["type_errors"] = type_errors
        results[table_name] = checks

    return results


def run_pipeline(spark, tables: dict[str, str], num_members=100) -> dict:
    """Run the full UMF pipeline on a set of UC tables.

    Args:
        spark: SparkSession
        tables: {umf_name: "catalog.schema.table"} mapping
        num_members: Number of rows to generate

    Returns:
        Validation results dict
    """
    from tablespec import GenerationConfig, SampleDataGenerator
    from tablespec.umf_loader import UMFLoader

    # Step 1: Profile tables and build UMF specs
    umf_specs = {}
    for umf_name, table_ref in tables.items():
        df = spark.table(table_ref).limit(1000)
        umf_specs[umf_name] = spark_df_to_enriched_umf(df, umf_name, spark)

    # Step 2: Generate sample data
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "specs"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        loader = UMFLoader()
        for name, umf in umf_specs.items():
            loader.save(umf, input_dir / umf.table_name)

        config = GenerationConfig(
            num_members=num_members,
            relationship_density=0.8,
            temporal_range_days=365,
            random_seed=42,
        )

        generator = SampleDataGenerator(
            input_dir=input_dir,
            output_dir=output_dir,
            config=config,
            spark=spark,
        )

        success = generator.run_generation()
        assert success, "SampleDataGenerator.run_generation() returned False"

        # Step 3: Validate
        return validate_generated_data(output_dir, umf_specs)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


class TestPipelineTpchCustomer:
    """Test pipeline with TPC-H Customer table (string-heavy, mixed types)."""

    def test_customer_pipeline(self, spark):
        results = run_pipeline(spark, {"Customer": "samples.tpch.customer"})
        checks = results["Customer"]
        assert checks["has_rows"]
        assert checks["columns_match"]
        assert checks["rows_consistent_width"]
        assert checks["type_validation_pass"], f"Type errors: {checks['type_errors']}"


class TestPipelineTpchOrders:
    """Test pipeline with TPC-H Orders table (dates, decimals, strings)."""

    def test_orders_pipeline(self, spark):
        results = run_pipeline(spark, {"Orders": "samples.tpch.orders"})
        checks = results["Orders"]
        assert checks["has_rows"]
        assert checks["columns_match"]
        assert checks["rows_consistent_width"]
        assert checks["type_validation_pass"], f"Type errors: {checks['type_errors']}"


class TestPipelineTpchLineItem:
    """Test pipeline with TPC-H LineItem table (wide, 16 columns, all types)."""

    def test_lineitem_pipeline(self, spark):
        results = run_pipeline(spark, {"LineItem": "samples.tpch.lineitem"})
        checks = results["LineItem"]
        assert checks["has_rows"]
        assert checks["columns_match"]
        assert checks["rows_consistent_width"]
        assert checks["type_validation_pass"], f"Type errors: {checks['type_errors']}"


class TestPipelineNycTaxi:
    """Test pipeline with NYC Taxi trips (timestamps, floats, integers)."""

    def test_taxi_pipeline(self, spark):
        results = run_pipeline(spark, {"NYC_Taxi_Trips": "samples.nyctaxi.trips"})
        checks = results["NYC_Taxi_Trips"]
        assert checks["has_rows"]
        assert checks["columns_match"]
        assert checks["rows_consistent_width"]
        assert checks["type_validation_pass"], f"Type errors: {checks['type_errors']}"


class TestPipelineMultiTable:
    """Test pipeline with multiple tables simultaneously."""

    def test_multi_table_pipeline(self, spark):
        """All tables generate and validate when processed together."""
        results = run_pipeline(
            spark,
            {
                "Customer": "samples.tpch.customer",
                "Orders": "samples.tpch.orders",
                "LineItem": "samples.tpch.lineitem",
                "NYC_Taxi_Trips": "samples.nyctaxi.trips",
            },
        )

        for table_name, checks in results.items():
            assert checks["has_rows"], f"{table_name}: no rows generated"
            assert checks["columns_match"], f"{table_name}: column mismatch"
            assert checks["rows_consistent_width"], f"{table_name}: row width mismatch"
            assert checks["type_validation_pass"], (
                f"{table_name}: type errors: {checks['type_errors']}"
            )


class TestUMFModelRoundTrip:
    """Test that profiled UMF specs serialize and deserialize correctly."""

    def test_umf_round_trip(self, spark):
        """UMF from Spark -> YAML -> reload -> identical."""
        from tablespec import save_umf_to_yaml, load_umf_from_yaml

        df = spark.table("samples.tpch.customer").limit(100)
        umf = spark_df_to_enriched_umf(df, "Customer_RT", spark)

        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            save_umf_to_yaml(umf, f.name)
            reloaded = load_umf_from_yaml(f.name)

        assert reloaded.table_name == umf.table_name
        assert len(reloaded.columns) == len(umf.columns)
        for orig, loaded in zip(umf.columns, reloaded.columns):
            assert orig.name == loaded.name
            assert orig.data_type == loaded.data_type
