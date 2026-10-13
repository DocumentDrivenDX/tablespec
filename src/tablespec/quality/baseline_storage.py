"""Baseline storage - Store and retrieve run baselines for change tracking.

This module provides functionality to capture and store baseline metrics
from pipeline runs for comparison with subsequent runs.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic model
import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pyspark.sql.types import (
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)


# Schema for run baselines Delta table
RUN_BASELINE_SCHEMA = StructType(
    [
        # Identification
        StructField("run_id", StringType(), False),
        StructField("run_timestamp", TimestampType(), False),
        StructField("run_date", StringType(), False),  # YYYY-MM-DD for partitioning
        StructField("pipeline_name", StringType(), False),
        StructField("table_name", StringType(), False),
        # Row Count Baseline
        StructField("row_count", LongType(), False),
        # Distribution Baselines (JSON)
        # Format: {"column_name": {"value1": count, "value2": count, ...}, ...}
        StructField("column_distributions", StringType(), True),
        # Distinct counts per column
        # Format: {"column_name": distinct_count, ...}
        StructField("distinct_counts", StringType(), True),
        # Null counts per column
        # Format: {"column_name": null_count, ...}
        StructField("null_counts", StringType(), True),
        # Record checksums for diff detection (optional, can be large)
        # Format: {"pk_hash": "row_checksum", ...}
        # Only populated if primary key is defined
        StructField("record_checksums", StringType(), True),
        # Primary key columns used for record tracking
        StructField("primary_key_columns", StringType(), True),  # JSON array
        # Summary statistics for numeric columns
        # Format: {"column_name": {"min": x, "max": y, "mean": z, "stddev": w}, ...}
        StructField("numeric_stats", StringType(), True),
    ]
)


class ColumnDistribution(BaseModel):
    """Value distribution for a single column."""

    column_name: str
    value_counts: dict[str, int] = Field(default_factory=dict)
    distinct_count: int = 0
    null_count: int = 0
    total_count: int = 0


class NumericStats(BaseModel):
    """Summary statistics for a numeric column."""

    column_name: str
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    stddev_value: float | None = None


class RunBaseline(BaseModel):
    """Baseline metrics captured from a pipeline run."""

    run_id: str
    run_timestamp: datetime
    pipeline_name: str
    table_name: str
    row_count: int

    # Column-level metrics
    column_distributions: dict[str, ColumnDistribution] = Field(default_factory=dict)
    numeric_stats: dict[str, NumericStats] = Field(default_factory=dict)

    # Record-level tracking (optional)
    record_checksums: dict[str, str] | None = None
    primary_key_columns: list[str] | None = None


class RowCountComparison(BaseModel):
    """Result of comparing row counts between runs."""

    previous_count: int
    current_count: int
    absolute_change: int
    percent_change: float
    direction: str  # "increase", "decrease", "unchanged"


class DistributionComparison(BaseModel):
    """Result of comparing value distributions between runs."""

    column_name: str
    js_divergence: float  # Jensen-Shannon divergence (0-1 scale)
    previous_distinct: int
    current_distinct: int
    new_values: list[str] = Field(default_factory=list)
    removed_values: list[str] = Field(default_factory=list)


class RecordComparison(BaseModel):
    """Result of comparing records between runs."""

    added_count: int
    removed_count: int
    modified_count: int
    unchanged_count: int
    added_percent: float
    removed_percent: float
    modified_percent: float


class BaselineWriter:
    """Write run baselines to Delta tables."""

    def __init__(
        self,
        backend: Any,
        table_ref: str = "run_baselines",
        stage: str = "validation",
        spark: SparkSession | None = None,
    ) -> None:
        """Initialize the baseline writer.

        Args:
            backend: TableBackend instance for storage operations
            table_ref: Table reference for baselines (default: "run_baselines")
            stage: Storage stage for baselines (default: "validation")
            spark: SparkSession for creating DataFrames

        """
        self.backend = backend
        self.table_ref = table_ref
        self.stage = stage
        self.spark = spark
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def get_schema() -> StructType:
        """Get the PySpark schema for run baselines Delta table."""
        return RUN_BASELINE_SCHEMA

    def write_baseline(self, baseline: RunBaseline) -> None:
        """Write a run baseline to Delta table.

        Args:
            baseline: RunBaseline with captured metrics

        """
        if not self.spark:
            msg = "SparkSession required for writing baselines"
            raise ValueError(msg)

        row = self._baseline_to_row(baseline)
        df = self.spark.createDataFrame([row], schema=RUN_BASELINE_SCHEMA)

        full_table_ref = f"{self.stage}/{self.table_ref}"

        self.logger.info(
            f"Writing baseline for {baseline.table_name} (run_id={baseline.run_id}) "
            f"to {self.table_ref}"
        )

        self.backend.storage.write(
            df,
            table_ref=full_table_ref,
            mode="append",
            partition_cols=["run_date", "table_name"],
        )

        self.logger.info(f"Successfully wrote baseline to {self.table_ref}")

    def _baseline_to_row(self, baseline: RunBaseline) -> dict[str, Any]:
        """Convert RunBaseline to row dictionary."""
        run_date = baseline.run_timestamp.strftime("%Y-%m-%d")

        # Serialize column distributions
        distributions_json = None
        if baseline.column_distributions:
            distributions_json = json.dumps(
                {
                    col: dist.value_counts
                    for col, dist in baseline.column_distributions.items()
                }
            )

        # Serialize distinct counts
        distinct_json = None
        if baseline.column_distributions:
            distinct_json = json.dumps(
                {
                    col: dist.distinct_count
                    for col, dist in baseline.column_distributions.items()
                }
            )

        # Serialize null counts
        null_json = None
        if baseline.column_distributions:
            null_json = json.dumps(
                {
                    col: dist.null_count
                    for col, dist in baseline.column_distributions.items()
                }
            )

        # Serialize numeric stats
        numeric_json = None
        if baseline.numeric_stats:
            numeric_json = json.dumps(
                {
                    col: {
                        "min": stats.min_value,
                        "max": stats.max_value,
                        "mean": stats.mean_value,
                        "stddev": stats.stddev_value,
                    }
                    for col, stats in baseline.numeric_stats.items()
                }
            )

        return {
            "run_id": baseline.run_id,
            "run_timestamp": baseline.run_timestamp,
            "run_date": run_date,
            "pipeline_name": baseline.pipeline_name,
            "table_name": baseline.table_name,
            "row_count": baseline.row_count,
            "column_distributions": distributions_json,
            "distinct_counts": distinct_json,
            "null_counts": null_json,
            "record_checksums": json.dumps(baseline.record_checksums)
            if baseline.record_checksums
            else None,
            "primary_key_columns": json.dumps(baseline.primary_key_columns)
            if baseline.primary_key_columns
            else None,
            "numeric_stats": numeric_json,
        }

    def read_latest_baseline(
        self,
        table_name: str,
        pipeline_name: str,
    ) -> RunBaseline | None:
        """Read the most recent baseline for a table.

        Args:
            table_name: Table name to query
            pipeline_name: Pipeline name to query

        Returns:
            Most recent RunBaseline or None if no baseline exists

        """
        if not self.spark:
            msg = "SparkSession required for reading baselines"
            raise ValueError(msg)

        full_table_ref = f"{self.stage}/{self.table_ref}"

        try:
            df = self.backend.storage.read(self.spark, full_table_ref)
        except Exception as e:
            self.logger.debug(f"Could not read baselines table: {e}")
            return None

        # Filter and get latest
        df = (
            df.filter(df.table_name == table_name)
            .filter(df.pipeline_name == pipeline_name)
            .orderBy(df.run_timestamp.desc())
            .limit(1)
        )

        rows = df.collect()
        if not rows:
            return None

        return self._row_to_baseline(rows[0])

    def _row_to_baseline(self, row: Any) -> RunBaseline:
        """Convert Delta row to RunBaseline."""
        # Parse column distributions
        column_distributions: dict[str, ColumnDistribution] = {}
        if row.column_distributions:
            dist_data = json.loads(row.column_distributions)
            distinct_data = (
                json.loads(row.distinct_counts) if row.distinct_counts else {}
            )
            null_data = json.loads(row.null_counts) if row.null_counts else {}

            for col, value_counts in dist_data.items():
                column_distributions[col] = ColumnDistribution(
                    column_name=col,
                    value_counts=value_counts,
                    distinct_count=distinct_data.get(col, 0),
                    null_count=null_data.get(col, 0),
                )

        # Parse numeric stats
        numeric_stats: dict[str, NumericStats] = {}
        if row.numeric_stats:
            stats_data = json.loads(row.numeric_stats)
            for col, stats in stats_data.items():
                numeric_stats[col] = NumericStats(
                    column_name=col,
                    min_value=stats.get("min"),
                    max_value=stats.get("max"),
                    mean_value=stats.get("mean"),
                    stddev_value=stats.get("stddev"),
                )

        # Parse record checksums
        record_checksums = None
        if row.record_checksums:
            record_checksums = json.loads(row.record_checksums)

        # Parse primary key columns
        primary_key_columns = None
        if row.primary_key_columns:
            primary_key_columns = json.loads(row.primary_key_columns)

        return RunBaseline(
            run_id=row.run_id,
            run_timestamp=row.run_timestamp,
            pipeline_name=row.pipeline_name,
            table_name=row.table_name,
            row_count=row.row_count,
            column_distributions=column_distributions,
            numeric_stats=numeric_stats,
            record_checksums=record_checksums,
            primary_key_columns=primary_key_columns,
        )
