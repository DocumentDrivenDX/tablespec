"""Profiling data types for schema analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ColumnProfile:
    """Profile statistics for a single column."""

    column_name: str
    completeness: float
    approximate_num_distinct: int | None = None
    data_type: str | None = None
    is_data_type_inferred: bool | None = None
    type_counts: dict[str, int] | None = None
    histogram: list[dict[str, Any]] | None = None
    kll_sketch: Any | None = None
    maximum: Any | None = None
    minimum: Any | None = None
    mean: float | None = None
    sum: float | None = None
    standard_deviation: float | None = None
    distinct_values: list[Any] | None = None
    string_length_min: int | None = None
    string_length_max: int | None = None

    # --- Extended distribution fields (native profiler) ---
    quantiles: dict[str, float] | None = None
    """Percentile values, e.g. {"p5": 1.2, "p25": 5.0, "p50": 10.0, "p75": 18.0, "p95": 42.0}"""

    skewness: float | None = None
    """Distribution skewness (0 = symmetric, positive = right-tailed)."""

    kurtosis: float | None = None
    """Distribution kurtosis (3 = normal, >3 = heavy-tailed)."""

    sample_values: list[Any] | None = None
    """Representative sample values for high-cardinality columns."""

    value_pattern: str | None = None
    """Detected structural pattern, e.g. 'NNN-NNN-NNNN' for phone numbers."""

    top_values: list[dict[str, Any]] | None = None
    """Top-N most frequent values with counts: [{"value": "X", "count": N, "fraction": 0.12}, ...]"""

    value_lengths: dict[str, int] | None = None
    """Distribution of string lengths: {"min": 5, "max": 40, "mean": 18, "p50": 17}"""


@dataclass
class DataFrameProfile:
    """Complete profile of a DataFrame."""

    num_records: int
    columns: dict[str, ColumnProfile]
