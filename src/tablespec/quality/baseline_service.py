"""Baseline service - High-level API for capturing and comparing run baselines.

This service provides the functionality to:
1. Capture baseline metrics from a DataFrame
2. Compare current data against previous baselines
3. Detect significant changes in row counts, distributions, and records
"""

from __future__ import annotations

from datetime import datetime
import logging
import math
from typing import TYPE_CHECKING, Any

from pyspark.sql import functions as F

from tablespec.quality.baseline_storage import (
    BaselineWriter,
    ColumnDistribution,
    DistributionComparison,
    NumericStats,
    RecordComparison,
    RowCountComparison,
    RunBaseline,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def _jensen_shannon_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Calculate Jensen-Shannon divergence between two distributions.

    Args:
        p: First probability distribution {value: probability}
        q: Second probability distribution {value: probability}

    Returns:
        JS divergence value between 0 (identical) and 1 (completely different)

    """
    # Get all keys from both distributions
    all_keys = set(p.keys()) | set(q.keys())

    if not all_keys:
        return 0.0

    # Normalize to probabilities and add smoothing for missing values
    epsilon = 1e-10
    p_probs = []
    q_probs = []

    for key in all_keys:
        p_probs.append(p.get(key, epsilon))
        q_probs.append(q.get(key, epsilon))

    # Normalize
    p_sum = sum(p_probs)
    q_sum = sum(q_probs)
    p_probs = [x / p_sum for x in p_probs]
    q_probs = [x / q_sum for x in q_probs]

    # Calculate M = (P + Q) / 2
    m_probs = [(p + q) / 2 for p, q in zip(p_probs, q_probs, strict=False)]

    # Calculate KL divergences
    def kl_divergence(p_dist: list[float], q_dist: list[float]) -> float:
        return sum(
            p * math.log(p / q) if p > 0 and q > 0 else 0
            for p, q in zip(p_dist, q_dist, strict=False)
        )

    kl_pm = kl_divergence(p_probs, m_probs)
    kl_qm = kl_divergence(q_probs, m_probs)

    # JS divergence is the average
    js_div = (kl_pm + kl_qm) / 2

    # Normalize to 0-1 range (JS divergence with log base e is between 0 and ln(2))
    return min(js_div / math.log(2), 1.0)


class BaselineService:
    """Service for capturing and comparing run baselines."""

    # Maximum number of distinct values to track per column for distributions
    MAX_DISTRIBUTION_VALUES = 100

    # Columns to exclude from distribution tracking (metadata columns)
    EXCLUDED_COLUMNS = frozenset(
        {
            "meta_source_name",
            "meta_source_checksum",
            "meta_load_dt",
            "meta_snapshot_dt",
            "meta_source_offset",
            "meta_checksum",
            "meta_pipeline_version",
            "meta_component",
        }
    )

    def __init__(
        self,
        backend: Any,
        spark: SparkSession,
        table_ref: str = "run_baselines",
        stage: str = "validation",
    ) -> None:
        """Initialize the baseline service.

        Args:
            backend: TableBackend instance for storage operations
            spark: SparkSession for DataFrame operations
            table_ref: Table reference for baselines (default: "run_baselines")
            stage: Storage stage for baselines (default: "validation")

        """
        self.backend = backend
        self.spark = spark
        self.writer = BaselineWriter(backend, table_ref, stage, spark)
        self.logger = logging.getLogger(self.__class__.__name__)

    def capture_baseline(
        self,
        df: DataFrame,
        pipeline_name: str,
        table_name: str,
        run_id: str,
        categorical_columns: list[str] | None = None,
        numeric_columns: list[str] | None = None,
        primary_key_columns: list[str] | None = None,
        capture_checksums: bool = False,
    ) -> RunBaseline:
        """Capture baseline metrics from a DataFrame.

        Args:
            df: PySpark DataFrame to capture baseline from
            pipeline_name: Pipeline name
            table_name: Table name
            run_id: Unique run identifier
            categorical_columns: Columns to track value distributions for.
                If None, auto-detects string columns with low cardinality.
            numeric_columns: Columns to track numeric statistics for.
                If None, auto-detects numeric columns.
            primary_key_columns: Columns forming primary key for record tracking.
                If None, record checksums are not captured.
            capture_checksums: Whether to capture record-level checksums.
                Requires primary_key_columns. Can be expensive for large tables.

        Returns:
            RunBaseline with captured metrics

        """
        run_timestamp = datetime.now()

        # Get row count
        row_count = df.count()
        self.logger.info(f"Capturing baseline for {table_name}: {row_count} rows")

        # Auto-detect columns if not specified
        if categorical_columns is None:
            categorical_columns = self._detect_categorical_columns(df)

        if numeric_columns is None:
            numeric_columns = self._detect_numeric_columns(df)

        # Capture column distributions
        column_distributions = {}
        for col in categorical_columns:
            if col in self.EXCLUDED_COLUMNS:
                continue
            dist = self._capture_column_distribution(df, col, row_count)
            if dist:
                column_distributions[col] = dist

        # Capture numeric stats
        numeric_stats = {}
        for col in numeric_columns:
            if col in self.EXCLUDED_COLUMNS:
                continue
            stats = self._capture_numeric_stats(df, col)
            if stats:
                numeric_stats[col] = stats

        # Capture record checksums if requested
        record_checksums = None
        if capture_checksums and primary_key_columns:
            record_checksums = self._capture_record_checksums(df, primary_key_columns)

        baseline = RunBaseline(
            run_id=run_id,
            run_timestamp=run_timestamp,
            pipeline_name=pipeline_name,
            table_name=table_name,
            row_count=row_count,
            column_distributions=column_distributions,
            numeric_stats=numeric_stats,
            record_checksums=record_checksums,
            primary_key_columns=primary_key_columns,
        )

        # Write to storage
        self.writer.write_baseline(baseline)

        return baseline

    def get_previous_baseline(
        self,
        pipeline_name: str,
        table_name: str,
    ) -> RunBaseline | None:
        """Retrieve the most recent baseline for a table.

        Args:
            pipeline_name: Pipeline name
            table_name: Table name

        Returns:
            Most recent RunBaseline or None if no baseline exists

        """
        return self.writer.read_latest_baseline(table_name, pipeline_name)

    def compare_row_counts(
        self,
        current_count: int,
        baseline: RunBaseline,
    ) -> RowCountComparison:
        """Compare current row count against baseline.

        Args:
            current_count: Current row count
            baseline: Previous baseline

        Returns:
            RowCountComparison with change metrics

        """
        previous_count = baseline.row_count
        absolute_change = current_count - previous_count

        if previous_count == 0:
            percent_change = 100.0 if current_count > 0 else 0.0
        else:
            percent_change = (absolute_change / previous_count) * 100

        if absolute_change > 0:
            direction = "increase"
        elif absolute_change < 0:
            direction = "decrease"
        else:
            direction = "unchanged"

        return RowCountComparison(
            previous_count=previous_count,
            current_count=current_count,
            absolute_change=absolute_change,
            percent_change=percent_change,
            direction=direction,
        )

    def compare_distribution(
        self,
        df: DataFrame,
        column_name: str,
        baseline: RunBaseline,
    ) -> DistributionComparison | None:
        """Compare current column distribution against baseline.

        Args:
            df: Current DataFrame
            column_name: Column to compare
            baseline: Previous baseline

        Returns:
            DistributionComparison or None if column not in baseline

        """
        if column_name not in baseline.column_distributions:
            return None

        baseline_dist = baseline.column_distributions[column_name]

        # Get current distribution
        current_dist = self._capture_column_distribution(df, column_name, df.count())
        if not current_dist:
            return None

        # Convert counts to probabilities
        baseline_probs = {
            v: c / baseline_dist.total_count if baseline_dist.total_count > 0 else 0
            for v, c in baseline_dist.value_counts.items()
        }
        current_probs = {
            v: c / current_dist.total_count if current_dist.total_count > 0 else 0
            for v, c in current_dist.value_counts.items()
        }

        # Calculate JS divergence
        js_div = _jensen_shannon_divergence(baseline_probs, current_probs)

        # Find new and removed values
        baseline_values = set(baseline_dist.value_counts.keys())
        current_values = set(current_dist.value_counts.keys())
        new_values = list(current_values - baseline_values)[:10]  # Limit to 10
        removed_values = list(baseline_values - current_values)[:10]

        return DistributionComparison(
            column_name=column_name,
            js_divergence=js_div,
            previous_distinct=baseline_dist.distinct_count,
            current_distinct=current_dist.distinct_count,
            new_values=new_values,
            removed_values=removed_values,
        )

    def compare_records(
        self,
        df: DataFrame,
        baseline: RunBaseline,
    ) -> RecordComparison | None:
        """Compare current records against baseline using checksums.

        Args:
            df: Current DataFrame
            baseline: Previous baseline with record checksums

        Returns:
            RecordComparison or None if checksums not available

        """
        if not baseline.record_checksums or not baseline.primary_key_columns:
            return None

        # Capture current checksums
        current_checksums = self._capture_record_checksums(
            df, baseline.primary_key_columns
        )
        if current_checksums is None:
            return None

        baseline_checksums = baseline.record_checksums

        # Compare
        baseline_keys = set(baseline_checksums.keys())
        current_keys = set(current_checksums.keys())

        added_keys = current_keys - baseline_keys
        removed_keys = baseline_keys - current_keys
        common_keys = baseline_keys & current_keys

        # Check for modifications in common keys
        modified_keys = {
            k for k in common_keys if baseline_checksums[k] != current_checksums[k]
        }
        unchanged_keys = common_keys - modified_keys

        total_baseline = len(baseline_keys)
        total_current = len(current_keys)

        return RecordComparison(
            added_count=len(added_keys),
            removed_count=len(removed_keys),
            modified_count=len(modified_keys),
            unchanged_count=len(unchanged_keys),
            added_percent=(len(added_keys) / total_current * 100)
            if total_current > 0
            else 0,
            removed_percent=(len(removed_keys) / total_baseline * 100)
            if total_baseline > 0
            else 0,
            modified_percent=(len(modified_keys) / total_baseline * 100)
            if total_baseline > 0
            else 0,
        )

    def _detect_categorical_columns(self, df: DataFrame) -> list[str]:
        """Auto-detect categorical columns suitable for distribution tracking."""
        categorical = []

        for field in df.schema.fields:
            if field.name in self.EXCLUDED_COLUMNS:
                continue

            # Only track string columns
            if str(field.dataType) != "StringType()":
                continue

            # Check cardinality (only track low-cardinality columns)
            distinct_count = df.select(field.name).distinct().count()
            if distinct_count <= self.MAX_DISTRIBUTION_VALUES:
                categorical.append(field.name)

        return categorical

    def _detect_numeric_columns(self, df: DataFrame) -> list[str]:
        """Auto-detect numeric columns for statistics tracking."""
        numeric = []

        numeric_types = {
            "IntegerType()",
            "LongType()",
            "DoubleType()",
            "FloatType()",
            "DecimalType",
        }

        for field in df.schema.fields:
            if field.name in self.EXCLUDED_COLUMNS:
                continue

            type_str = str(field.dataType)
            if any(t in type_str for t in numeric_types):
                numeric.append(field.name)

        return numeric

    def _capture_column_distribution(
        self,
        df: DataFrame,
        column_name: str,
        total_count: int,
    ) -> ColumnDistribution | None:
        """Capture value distribution for a column."""
        try:
            # Get value counts
            value_counts_df = (
                df.groupBy(column_name)
                .count()
                .orderBy(F.col("count").desc())
                .limit(self.MAX_DISTRIBUTION_VALUES)
            )

            rows = value_counts_df.collect()

            value_counts = {}
            for row in rows:
                value = row[column_name]
                count = row["count"]
                # Convert value to string for JSON serialization
                key = str(value) if value is not None else "__NULL__"
                value_counts[key] = count

            # Get distinct count
            distinct_count = df.select(column_name).distinct().count()

            # Get null count
            null_count = df.filter(F.col(column_name).isNull()).count()

            return ColumnDistribution(
                column_name=column_name,
                value_counts=value_counts,
                distinct_count=distinct_count,
                null_count=null_count,
                total_count=total_count,
            )

        except Exception as e:
            self.logger.warning(
                f"Could not capture distribution for {column_name}: {e}"
            )
            return None

    def _capture_numeric_stats(
        self,
        df: DataFrame,
        column_name: str,
    ) -> NumericStats | None:
        """Capture summary statistics for a numeric column."""
        try:
            stats_row = df.select(
                F.min(column_name).alias("min_val"),
                F.max(column_name).alias("max_val"),
                F.mean(column_name).alias("mean_val"),
                F.stddev(column_name).alias("stddev_val"),
            ).first()

            if stats_row is None:
                return None

            return NumericStats(
                column_name=column_name,
                min_value=float(stats_row["min_val"])
                if stats_row["min_val"] is not None
                else None,
                max_value=float(stats_row["max_val"])
                if stats_row["max_val"] is not None
                else None,
                mean_value=float(stats_row["mean_val"])
                if stats_row["mean_val"] is not None
                else None,
                stddev_value=float(stats_row["stddev_val"])
                if stats_row["stddev_val"] is not None
                else None,
            )

        except Exception as e:
            self.logger.warning(
                f"Could not capture numeric stats for {column_name}: {e}"
            )
            return None

    def _capture_record_checksums(
        self,
        df: DataFrame,
        primary_key_columns: list[str],
    ) -> dict[str, str] | None:
        """Capture record checksums using primary key and row hash.

        Uses the existing meta_checksum column if available, otherwise
        computes a hash of all columns.
        """
        try:
            # Check if meta_checksum exists
            has_meta_checksum = "meta_checksum" in df.columns

            # Create PK hash
            pk_expr = F.concat_ws(
                "|", *[F.col(c).cast("string") for c in primary_key_columns]
            )
            pk_hash_expr = F.sha2(pk_expr, 256)

            if has_meta_checksum:
                # Use existing meta_checksum
                checksum_df = df.select(
                    pk_hash_expr.alias("pk_hash"),
                    F.col("meta_checksum").cast("string").alias("row_checksum"),
                )
            else:
                # Compute hash of all non-meta columns
                non_meta_cols = [
                    c for c in df.columns if c not in self.EXCLUDED_COLUMNS
                ]
                row_expr = F.concat_ws(
                    "|", *[F.col(c).cast("string") for c in non_meta_cols]
                )
                checksum_df = df.select(
                    pk_hash_expr.alias("pk_hash"),
                    F.sha2(row_expr, 256).alias("row_checksum"),
                )

            rows = checksum_df.collect()
            return {row["pk_hash"]: row["row_checksum"] for row in rows}

        except Exception as e:
            self.logger.warning(f"Could not capture record checksums: {e}")
            return None
