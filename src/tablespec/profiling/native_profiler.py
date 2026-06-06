"""Profile a Spark DataFrame using native Spark SQL functions.

Uses only standard Spark SQL aggregations (min, max, avg, stddev,
approx_count_distinct, percentile_approx, skewness, kurtosis, etc.)
that work over Spark Connect — no JVM, no extra dependencies beyond pyspark.

Usage::

    from tablespec.profiling import NativeSparkProfiler, ProfileToGxMapper

    profiler = NativeSparkProfiler(spark)
    profile = profiler.profile(df)

    # Generate GX expectations directly from the profile
    gx_mapper = ProfileToGxMapper(strictness="medium")
    expectations = gx_mapper.build_expectations(profile)

Returns a :class:`~tablespec.profiling.types.DataFrameProfile` dataclass.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from tablespec.profiling.types import ColumnProfile, DataFrameProfile

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)

# Spark type names that should be treated as numeric
_NUMERIC_TYPES = frozenset(
    {
        "IntegerType",
        "LongType",
        "ShortType",
        "ByteType",
        "FloatType",
        "DoubleType",
        "DecimalType",
    }
)

# Spark type names that should get string-length stats
_STRING_TYPES = frozenset({"StringType"})

# Quantile probabilities
_QUANTILE_PROBS = [0.05, 0.25, 0.50, 0.75, 0.95]
_QUANTILE_LABELS = ["p5", "p25", "p50", "p75", "p95"]


def _functions_for(df: DataFrame) -> Any:
    """Return the ``functions`` module matching the DataFrame's engine.

    ``pyspark.sql.functions`` auto-dispatches to classic vs. connect based on
    process-global remote state (``is_remote()``), NOT on the DataFrame. When a
    classic JVM session and a Spark Connect (e.g. Sail) session coexist in one
    process -- as in the local Connect test lane -- ``pyspark.sql.functions``
    yields CLASSIC Column objects that fail inside a Connect plan
    (``'Column' object is not callable``). Selecting the functions module from
    the DataFrame's own type makes column expressions session-correct.

    This is behavior-identical in production: on real Databricks serverless the
    DataFrame is a Connect DataFrame and there is no classic session, so the
    result is the same connect functions module ``F`` already resolves to; on a
    purely classic local session it is the classic functions module.
    """
    module = type(df).__module__
    if module.startswith("pyspark.sql.connect"):
        from pyspark.sql.connect import functions as connect_F  # noqa: N812

        return connect_F
    from pyspark.sql import functions as classic_F  # noqa: N812

    return classic_F


class NativeSparkProfiler:
    """Profile a Spark DataFrame using native SQL aggregations.

    Works on all Spark environments including Spark Connect and
    Databricks serverless — no JVM, no py4j, no extra dependencies.

    Parameters
    ----------
    spark : SparkSession
        Any Spark session (classic or Connect).
    low_cardinality_threshold : int, optional
        If a column has fewer than this many distinct values, the profiler
        will collect the distinct values into the profile. Defaults to 50.
    histogram_bins : int, optional
        Number of top-N frequent values to collect for categorical histograms.
        Defaults to 20.
    sample_size : int, optional
        Number of sample values to collect for high-cardinality columns.
        Defaults to 10.
    quantile_accuracy : int, optional
        Accuracy parameter for percentile_approx (higher = more accurate but
        slower). Represents 1/relative_error. Defaults to 10000.

    """

    def __init__(
        self,
        spark: SparkSession,
        *,
        low_cardinality_threshold: int = 50,
        histogram_bins: int = 20,
        sample_size: int = 10,
        quantile_accuracy: int = 10000,
    ) -> None:
        self._spark = spark
        self._low_card_threshold = low_cardinality_threshold
        self._histogram_bins = histogram_bins
        self._sample_size = sample_size
        self._quantile_accuracy = quantile_accuracy

    def profile(
        self,
        df: DataFrame,
        *,
        restrict_to_columns: list[str] | None = None,
        cache_inputs: bool = True,
    ) -> DataFrameProfile:
        """Profile a Spark DataFrame.

        Parameters
        ----------
        df : DataFrame
            The DataFrame to profile.
        restrict_to_columns : list[str] | None, optional
            If provided, only profile these columns. By default profiles all.
        cache_inputs : bool, optional
            Whether to cache the DataFrame during profiling for performance.
            Defaults to True.

        Returns
        -------
        DataFrameProfile
            Profiling results for use with ``ProfileToGxMapper``.

        """
        F = _functions_for(df)  # noqa: N806

        cached = False
        if cache_inputs:
            try:
                df = df.cache()
                cached = True
            except Exception:
                # cache() not supported on serverless — proceed without it
                pass

        num_records = df.count()
        columns_to_profile = restrict_to_columns or df.columns

        logger.info(
            f"Starting native profiling: {num_records} rows, "
            f"{len(columns_to_profile)} columns"
        )

        # --- Phase 1: Batch completeness & cardinality for ALL columns ---
        completeness_exprs = []
        cardinality_exprs = []
        for col_name in columns_to_profile:
            c = F.col(f"`{col_name}`")
            completeness_exprs.append(
                F.count(F.when(c.isNotNull(), 1)).alias(f"_nn_{col_name}")
            )
            # Cardinality: approx_count_distinct is fast and Connect-safe for most
            # types, but DataFusion (Sail) does not implement approx_distinct for
            # Float64. For float/double columns fall back to exact countDistinct,
            # which is behavior-identical on classic Spark (just exact, not approx).
            field_type = type(df.schema[col_name].dataType).__name__
            if field_type in {"FloatType", "DoubleType"}:
                cardinality_exprs.append(F.count_distinct(c).alias(f"_cd_{col_name}"))
            else:
                cardinality_exprs.append(
                    F.approx_count_distinct(c).alias(f"_cd_{col_name}")
                )

        # Execute in one pass (completeness + cardinality together)
        batch_row = df.select(*completeness_exprs, *cardinality_exprs).collect()[0]

        columns: dict[str, ColumnProfile] = {}

        for col_name in columns_to_profile:
            field = df.schema[col_name]
            type_name = type(field.dataType).__name__

            non_null = batch_row[f"_nn_{col_name}"]
            completeness = non_null / num_records if num_records > 0 else 0.0
            approx_distinct = batch_row[f"_cd_{col_name}"]

            profile = ColumnProfile(
                column_name=col_name,
                completeness=completeness,
                approximate_num_distinct=approx_distinct,
                data_type=type_name,
                is_data_type_inferred=False,
            )

            # --- Phase 2: Numeric columns — stats + quantiles + shape ---
            if type_name in _NUMERIC_TYPES:
                self._profile_numeric(df, col_name, profile)

            # --- Phase 3: String columns — lengths + patterns ---
            if type_name in _STRING_TYPES:
                self._profile_string(df, col_name, profile, num_records)

            # --- Phase 4: Cardinality-based decisions ---
            if approx_distinct <= self._low_card_threshold:
                # Low cardinality: collect all distinct values + frequency histogram
                self._collect_distinct_with_counts(df, col_name, profile, num_records)
            else:
                # High cardinality: collect a sample of representative values
                self._collect_sample_values(df, col_name, profile)

            columns[col_name] = profile

        if cached:
            df.unpersist()

        logger.info(f"Profiling complete: {len(columns)} columns profiled")
        return DataFrameProfile(num_records=num_records, columns=columns)

    def _profile_numeric(
        self, df: DataFrame, col_name: str, profile: ColumnProfile
    ) -> None:
        """Compute numeric statistics, quantiles, and distribution shape."""
        F = _functions_for(df)  # noqa: N806

        c = F.col(f"`{col_name}`").cast("double")

        # All numeric stats in one query: min, max, mean, stddev, sum,
        # skewness, kurtosis, and quantiles.
        #
        # Quantiles: emit one SCALAR percentile_approx per probe (not a single
        # call with an array of probes). DataFusion (Sail) only accepts a scalar
        # percentile for approx_percentile_cont; classic Spark accepts both, so
        # this is behavior-identical there. All probes stay inside this single
        # df.select so profiling remains one aggregation / one job.
        quantile_exprs = [
            F.percentile_approx(c, prob, self._quantile_accuracy).alias(f"_q_{label}")
            for label, prob in zip(_QUANTILE_LABELS, _QUANTILE_PROBS)
        ]
        stats_row = df.select(
            F.min(c).alias("min_val"),
            F.max(c).alias("max_val"),
            F.avg(c).alias("mean_val"),
            F.stddev(c).alias("stddev_val"),
            F.sum(c).alias("sum_val"),
            F.skewness(c).alias("skew_val"),
            F.kurtosis(c).alias("kurt_val"),
            *quantile_exprs,
        ).collect()[0]

        profile.minimum = stats_row["min_val"]
        profile.maximum = stats_row["max_val"]
        profile.mean = stats_row["mean_val"]
        profile.standard_deviation = stats_row["stddev_val"]
        profile.sum = stats_row["sum_val"]

        # Distribution shape
        skew = stats_row["skew_val"]
        kurt = stats_row["kurt_val"]
        if skew is not None:
            profile.skewness = round(skew, 4)
        if kurt is not None:
            profile.kurtosis = round(kurt, 4)

        # Quantiles (one scalar column per probe)
        quantile_values = {
            label: stats_row[f"_q_{label}"]
            for label in _QUANTILE_LABELS
            if stats_row[f"_q_{label}"] is not None
        }
        if quantile_values:
            profile.quantiles = quantile_values

    def _profile_string(
        self,
        df: DataFrame,
        col_name: str,
        profile: ColumnProfile,
        num_records: int,
    ) -> None:
        """Compute string length statistics and detect patterns."""
        F = _functions_for(df)  # noqa: N806

        c = F.col(f"`{col_name}`")
        length_c = F.length(c)

        # String length distribution in one query
        len_row = df.select(
            F.min(length_c).alias("min_len"),
            F.max(length_c).alias("max_len"),
            F.avg(length_c).alias("mean_len"),
            # Scalar percentile (0.50, not [0.50]) for Sail/DataFusion
            # compatibility; classic Spark accepts both identically.
            F.percentile_approx(
                length_c.cast("double"), 0.50, self._quantile_accuracy
            ).alias("median_len"),
        ).collect()[0]

        profile.string_length_min = len_row["min_len"]
        profile.string_length_max = len_row["max_len"]

        mean_len = len_row["mean_len"]
        median_len = len_row["median_len"]
        if mean_len is not None and median_len is not None:
            profile.value_lengths = {
                "min": len_row["min_len"],
                "max": len_row["max_len"],
                "mean": round(mean_len),
                # median_len is now a scalar (was a single-element array).
                "p50": median_len,
            }

        # Pattern detection — sample a few values and infer structural patterns
        sample_rows = df.select(c).where(c.isNotNull()).limit(100).collect()
        if sample_rows:
            pattern = self._detect_pattern([str(row[0]) for row in sample_rows])
            if pattern:
                profile.value_pattern = pattern

    def _collect_distinct_with_counts(
        self,
        df: DataFrame,
        col_name: str,
        profile: ColumnProfile,
        num_records: int,
    ) -> None:
        """Collect all distinct values with frequency counts (low-cardinality)."""
        F = _functions_for(df)  # noqa: N806

        c = F.col(f"`{col_name}`")

        freq_rows = (
            df.where(c.isNotNull())
            .groupBy(c)
            .agg(F.count("*").alias("cnt"))
            .orderBy(F.desc("cnt"))
            .limit(self._low_card_threshold)
            .collect()
        )

        profile.distinct_values = sorted(str(row[0]) for row in freq_rows)

        # Build histogram (value frequencies) for the generator
        profile.histogram = [
            {
                "value": str(row[col_name]),
                "count": row["cnt"],
                "fraction": round(row["cnt"] / num_records, 4)
                if num_records > 0
                else 0,
            }
            for row in freq_rows
        ]

        # Top values (same data, sorted by frequency)
        profile.top_values = [
            {
                "value": str(row[col_name]),
                "count": row["cnt"],
                "fraction": round(row["cnt"] / num_records, 4)
                if num_records > 0
                else 0,
            }
            for row in freq_rows[: self._histogram_bins]
        ]

    def _collect_sample_values(
        self, df: DataFrame, col_name: str, profile: ColumnProfile
    ) -> None:
        """Collect representative sample values for high-cardinality columns."""
        F = _functions_for(df)  # noqa: N806

        c = F.col(f"`{col_name}`")

        # Stratified sample: take a few from top, middle, and tail
        sample_rows = (
            df.select(c)
            .where(c.isNotNull())
            .orderBy(F.rand(seed=42))
            .limit(self._sample_size)
            .collect()
        )

        if sample_rows:
            profile.sample_values = [str(row[0]) for row in sample_rows]

        # Also get top-N most frequent values even for high cardinality
        top_rows = (
            df.where(c.isNotNull())
            .groupBy(c)
            .agg(F.count("*").alias("cnt"))
            .orderBy(F.desc("cnt"))
            .limit(self._histogram_bins)
            .collect()
        )

        sum(row["cnt"] for row in top_rows) if top_rows else 1
        num_records = df.count()
        if top_rows:
            profile.top_values = [
                {
                    "value": str(row[col_name]),
                    "count": row["cnt"],
                    "fraction": round(row["cnt"] / num_records, 4)
                    if num_records > 0
                    else 0,
                }
                for row in top_rows
            ]

    @staticmethod
    def _detect_pattern(values: list[str]) -> str | None:
        """Detect structural patterns in string values.

        Converts characters to pattern classes:
        - A = uppercase letter
        - a = lowercase letter
        - N = digit
        - Punctuation/whitespace preserved as-is

        Returns the pattern if >80% of values match it, else None.
        """
        if not values:
            return None

        def _to_pattern(s: str) -> str:
            result = []
            for ch in s:
                if ch.isupper():
                    result.append("A")
                elif ch.islower():
                    result.append("a")
                elif ch.isdigit():
                    result.append("N")
                else:
                    result.append(ch)
            return "".join(result)

        patterns = [_to_pattern(v) for v in values]

        # Find the most common pattern
        from collections import Counter

        counts = Counter(patterns)
        most_common_pattern, most_common_count = counts.most_common(1)[0]

        # Only report if dominant (>80% of sample matches)
        if most_common_count / len(values) >= 0.8:
            return most_common_pattern

        # Try collapsing runs: NNNN → N+, aaaa → a+
        def _collapse_runs(p: str) -> str:
            collapsed = re.sub(r"(A)\1{2,}", "A+", p)
            collapsed = re.sub(r"(a)\1{2,}", "a+", collapsed)
            collapsed = re.sub(r"(N)\1{2,}", "N+", collapsed)
            return collapsed

        collapsed_patterns = [_collapse_runs(p) for p in patterns]
        counts2 = Counter(collapsed_patterns)
        top_pattern, top_count = counts2.most_common(1)[0]

        if top_count / len(values) >= 0.6:
            return top_pattern

        return None
