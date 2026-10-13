"""Quality check results storage - Write quality check results to Delta tables.

This module provides functionality to write quality check execution results
to a Delta table format for tracking and trend analysis.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING, Any

from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

try:
    from tablespec.models.quality import QualityCheckRun
except ImportError:
    QualityCheckRun = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

# Schema for quality check results Delta table
# Extends validation_results schema with quality-specific fields
QUALITY_CHECK_RESULT_SCHEMA = StructType(
    [
        # Identification & Timing
        StructField("run_id", StringType(), False),  # UUID per quality check run
        StructField("run_timestamp", TimestampType(), False),
        StructField("run_date", StringType(), False),  # YYYY-MM-DD for partitioning
        StructField("pipeline_name", StringType(), False),
        StructField("table_name", StringType(), False),
        # Check Type (for unified storage with validation_results)
        StructField(
            "check_type", StringType(), False
        ),  # "quality_check" vs "validation"
        # Check Details
        StructField("check_id", StringType(), False),  # Unique check identifier
        StructField("expectation_type", StringType(), False),  # GX expectation type
        StructField("column_name", StringType(), True),  # Column (null for table-level)
        # Result
        StructField("success", BooleanType(), False),
        StructField("severity", StringType(), False),  # critical, warning, info
        StructField("blocking", BooleanType(), False),  # Whether check is blocking
        StructField("description", StringType(), True),  # Human-readable description
        # Metrics
        StructField("unexpected_count", LongType(), True),  # Number of failing rows
        StructField("unexpected_percent", DoubleType(), True),  # Failure percentage
        StructField(
            "observed_value", StringType(), True
        ),  # JSON-serialized observed value
        # Metadata
        StructField("tags", StringType(), True),  # JSON-serialized list of tags
        StructField("details", StringType(), True),  # JSON-serialized check details
        # Aggregate Metrics (run-level)
        StructField("total_checks", IntegerType(), True),  # Total checks in run
        StructField("passed_checks", IntegerType(), True),  # Passed checks
        StructField("failed_checks", IntegerType(), True),  # Failed checks
        StructField("success_rate", DoubleType(), True),  # Overall success rate
        StructField("should_block", BooleanType(), True),  # Pipeline should be blocked
        StructField("threshold_breached", BooleanType(), True),  # Threshold breached
        # Incremental validation fields
        StructField(
            "since_timestamp", TimestampType(), True
        ),  # Cutoff for incremental validation
        StructField(
            "incremental_mode", BooleanType(), True
        ),  # Whether incremental mode was used
        StructField(
            "total_source_records", LongType(), True
        ),  # Total records before filtering
        StructField(
            "validated_records", LongType(), True
        ),  # Records actually validated
    ]
)


class QualityResultsWriter:
    """Write quality check results to Delta tables.

    Uses backend abstraction to write to a quality_check_results table.
    Can be unified with validation_results table using check_type field.
    """

    def __init__(
        self,
        backend: Any,
        table_ref: str = "quality_check_results",
        stage: str = "validation",
        spark: SparkSession | None = None,
    ) -> None:
        """Initialize the quality results writer.

        Args:
            backend: TableBackend instance for storage operations
            table_ref: Table reference for quality results (default: "quality_check_results")
            stage: Storage stage for quality results (default: "validation")
            spark: SparkSession for creating DataFrames (optional, can be inferred from backend)

        """
        self.backend = backend
        self.table_ref = table_ref
        self.stage = stage
        self.spark = spark
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def get_schema() -> StructType:
        """Get the PySpark schema for quality check results Delta table.

        Returns:
            StructType schema for quality check results

        """
        return QUALITY_CHECK_RESULT_SCHEMA

    def write_quality_check_run(self, quality_run: QualityCheckRun) -> None:
        """Write quality check run results to Delta table.

        Args:
            quality_run: QualityCheckRun with execution results

        """
        if not self.spark:
            msg = "SparkSession required for writing quality check results"
            raise ValueError(msg)

        # Convert QualityCheckRun to rows
        rows = self._quality_run_to_rows(quality_run)

        if not rows:
            self.logger.warning(
                f"No quality check results to write for {quality_run.table_name}"
            )
            return

        # Create DataFrame
        df = self.spark.createDataFrame(rows, schema=QUALITY_CHECK_RESULT_SCHEMA)

        # Write to Delta using backend
        self.logger.info(
            f"Writing {len(rows)} quality check results for {quality_run.table_name} to {self.table_ref}"
        )

        # Format table ref as stage/table
        full_table_ref = f"{self.stage}/{self.table_ref}"

        self.backend.storage.write(
            df,
            table_ref=full_table_ref,
            mode="append",
            partition_cols=["run_date", "table_name"],
        )

        self.logger.info(
            f"Successfully wrote quality check results to {self.table_ref}"
        )

    def _quality_run_to_rows(
        self, quality_run: QualityCheckRun
    ) -> list[dict[str, Any]]:
        """Convert QualityCheckRun to list of rows for Delta table.

        Args:
            quality_run: QualityCheckRun with execution results

        Returns:
            List of row dictionaries matching QUALITY_CHECK_RESULT_SCHEMA

        """
        rows = []
        run_date = quality_run.run_timestamp.strftime("%Y-%m-%d")

        # Extract score metrics (run-level)
        score = quality_run.score
        total_checks = score.total_checks if score else 0
        passed_checks = score.passed_checks if score else 0
        failed_checks = score.failed_checks if score else 0
        success_rate = score.success_rate if score else 0.0
        threshold_breached = score.threshold_breached if score else False

        for result in quality_run.results:
            row = {
                # Identification & Timing
                "run_id": quality_run.run_id,
                "run_timestamp": quality_run.run_timestamp,
                "run_date": run_date,
                "pipeline_name": quality_run.pipeline_name,
                "table_name": quality_run.table_name,
                # Check Type
                "check_type": "quality_check",
                # Check Details
                "check_id": result.check_id,
                "expectation_type": result.expectation_type,
                "column_name": result.column_name,
                # Result
                "success": result.success,
                "severity": result.severity,
                "blocking": result.blocking,
                "description": result.description,
                # Metrics
                "unexpected_count": result.unexpected_count,
                "unexpected_percent": result.unexpected_percent,
                "observed_value": json.dumps(result.observed_value)
                if result.observed_value is not None
                else None,
                # Metadata
                "tags": json.dumps(result.tags) if result.tags else None,
                "details": json.dumps(result.details) if result.details else None,
                # Aggregate Metrics (run-level)
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "success_rate": success_rate,
                "should_block": quality_run.should_block,
                "threshold_breached": threshold_breached,
                # Incremental validation fields
                "since_timestamp": quality_run.since_timestamp,
                "incremental_mode": quality_run.incremental_mode,
                "total_source_records": quality_run.total_source_records,
                "validated_records": quality_run.validated_records,
            }
            rows.append(row)

        return rows

    def read_quality_check_history(
        self,
        table_name: str,
        pipeline_name: str | None = None,
        limit: int = 100,
    ) -> DataFrame:
        """Read quality check history from Delta table.

        Args:
            table_name: Table name to query
            pipeline_name: Optional pipeline name filter
            limit: Maximum number of results to return

        Returns:
            DataFrame with quality check history

        """
        if not self.spark:
            msg = "SparkSession required for reading quality check history"
            raise ValueError(msg)

        # Read from Delta using full table ref
        full_table_ref = f"{self.stage}/{self.table_ref}"
        df = self.backend.storage.read(full_table_ref)

        # Filter by table name
        df = df.filter(df.table_name == table_name)

        # Filter by pipeline if specified
        if pipeline_name:
            df = df.filter(df.pipeline_name == pipeline_name)

        # Order by timestamp descending
        df = df.orderBy(df.run_timestamp.desc())

        # Limit results
        if limit > 0:
            df = df.limit(limit)

        return df

    def get_last_validation_timestamp(
        self,
        pipeline_name: str,
        table_name: str,
    ) -> datetime | None:
        """Get the timestamp of the last validation run for incremental filtering.

        Returns the run_timestamp of the most recent quality check run for the
        given pipeline/table combination. This is used as the cutoff for
        incremental validation (only validate records with meta_load_dt > this).

        Args:
            pipeline_name: Pipeline name
            table_name: Table name

        Returns:
            datetime of last validation run, or None if no previous runs exist

        """
        if not self.spark:
            self.logger.warning(
                "SparkSession required for reading last validation timestamp"
            )
            return None

        try:
            # Read from Delta using full table ref
            full_table_ref = f"{self.stage}/{self.table_ref}"
            df = self.backend.storage.read(full_table_ref)

            # Filter by pipeline and table
            df = df.filter(
                (df.pipeline_name == pipeline_name) & (df.table_name == table_name)
            )

            # Get max run_timestamp
            from pyspark.sql import functions as F

            result = df.agg(F.max("run_timestamp").alias("max_timestamp")).collect()

            if result and result[0]["max_timestamp"]:
                max_ts = result[0]["max_timestamp"]
                self.logger.info(
                    f"Last validation timestamp for {pipeline_name}/{table_name}: {max_ts}"
                )
                # Ensure it's a datetime object
                if isinstance(max_ts, datetime):
                    return max_ts
                return None

            self.logger.info(
                f"No previous validation runs found for {pipeline_name}/{table_name}"
            )
            return None

        except Exception as e:
            # Table may not exist yet on first run
            self.logger.debug(
                f"Could not read last validation timestamp (may be first run): {e}"
            )
            return None
