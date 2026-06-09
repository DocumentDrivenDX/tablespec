"""Generate Great Expectations from a DataFrameProfile.

This module converts profiling statistics into GX expectation dictionaries
without requiring the data to pass through a UMF round-trip first. This is
the "profile → expectations" shortcut for data quality monitoring.

Usage::

    from tablespec.profiling import NativeSparkProfiler, ProfileToGxMapper

    profiler = NativeSparkProfiler(spark)
    profile = profiler.profile(df)

    mapper = ProfileToGxMapper()
    expectations = mapper.build_expectations(profile)

Each expectation is a dict matching the GX JSON expectation format::

    {
        "type": "expect_column_values_to_be_between",
        "kwargs": {"column": "price", "min_value": 0.5, "max_value": 9999.99},
        "meta": {"severity": "warning", "generated_from": "profiling", ...},
    }

Strictness levels control how tight the bounds are:
    - "tight": Bounds from observed min/max. Good for golden datasets.
    - "medium" (default): Bounds with 10% tolerance. Good for monitoring.
    - "loose": Bounds from p5/p95 quantiles. Good for drift detection.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from tablespec.profiling.types import ColumnProfile, DataFrameProfile

logger = logging.getLogger(__name__)

Strictness = Literal["tight", "medium", "loose"]


def _pattern_to_regex(pattern: str) -> str:
    """Convert a structural pattern (A, a, N, +) to a regex.

    Pattern language:
        A  = single uppercase letter [A-Z]
        a  = single lowercase letter [a-z]
        N  = single digit [0-9]
        A+ = one or more uppercase letters
        a+ = one or more lowercase letters
        N+ = one or more digits
        Other characters are escaped literals.
    """
    result = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        # Check for "X+" quantifier
        if i + 1 < len(pattern) and pattern[i + 1] == "+":
            if ch == "A":
                result.append("[A-Z]+")
            elif ch == "a":
                result.append("[a-z]+")
            elif ch == "N":
                result.append("[0-9]+")
            else:
                result.append(re.escape(ch) + "+")
            i += 2
        else:
            if ch == "A":
                result.append("[A-Z]")
            elif ch == "a":
                result.append("[a-z]")
            elif ch == "N":
                result.append("[0-9]")
            else:
                result.append(re.escape(ch))
            i += 1
    return "^" + "".join(result) + "$"


class ProfileToGxMapper:
    """Generate GX expectations directly from a DataFrameProfile.

    Parameters
    ----------
    strictness : Strictness, optional
        How tight to make numeric/length bounds. Defaults to "medium".
    completeness_threshold : float, optional
        Minimum completeness to emit a not-null expectation. Defaults to 0.95.
    uniqueness_threshold : float, optional
        Ratio of distinct/total above which to emit uniqueness. Defaults to 0.99.
    tolerance : float, optional
        Fractional tolerance for numeric bounds in "medium" mode. Defaults to 0.1.
    pattern_confidence : float, optional
        Minimum fraction of values that must match a pattern to emit a regex
        expectation. Defaults to 0.8.

    """

    def __init__(
        self,
        *,
        strictness: Strictness = "medium",
        completeness_threshold: float = 0.95,
        uniqueness_threshold: float = 0.99,
        tolerance: float = 0.1,
        pattern_confidence: float = 0.8,
    ) -> None:
        self._strictness = strictness
        self._completeness_threshold = completeness_threshold
        self._uniqueness_threshold = uniqueness_threshold
        self._tolerance = tolerance
        self._pattern_confidence = pattern_confidence

    def build_expectations(self, profile: DataFrameProfile) -> list[dict[str, Any]]:
        """Build GX expectations from a complete DataFrameProfile.

        Parameters
        ----------
        profile : DataFrameProfile
            Profile output from NativeSparkProfiler.

        Returns
        -------
        list[dict[str, Any]]
            List of GX expectation dictionaries.

        """
        expectations: list[dict[str, Any]] = []

        # Table-level: column count
        expectations.append(self._expect_table_column_count(profile))

        # Column-level expectations
        for col_name, col_profile in profile.columns.items():
            expectations.extend(self._build_column_expectations(col_profile, profile))

        logger.info(
            f"Generated {len(expectations)} expectations from profile "
            f"({len(profile.columns)} columns)"
        )
        return expectations

    def _expect_table_column_count(self, profile: DataFrameProfile) -> dict[str, Any]:
        """Expect the table to have the profiled number of columns."""
        return {
            "type": "expect_table_column_count_to_equal",
            "kwargs": {"value": len(profile.columns)},
            "meta": {
                "description": f"Table must have {len(profile.columns)} columns",
                "severity": "critical",
                "generated_from": "profiling",
            },
        }

    def _build_column_expectations(
        self, cp: ColumnProfile, profile: DataFrameProfile
    ) -> list[dict[str, Any]]:
        """Build all expectations for a single column."""
        expectations: list[dict[str, Any]] = []

        # 1. Completeness → not-null
        expectations.extend(self._completeness_expectations(cp))

        # 2. Uniqueness
        expectations.extend(self._uniqueness_expectations(cp, profile))

        # 3. Numeric range (with tolerance based on strictness)
        expectations.extend(self._numeric_range_expectations(cp))

        # 4. Quantile-based distribution bounds
        expectations.extend(self._quantile_expectations(cp))

        # 5. Value set (low-cardinality)
        expectations.extend(self._value_set_expectations(cp))

        # 6. String length bounds
        expectations.extend(self._string_length_expectations(cp))

        # 7. Pattern → regex match
        expectations.extend(self._pattern_expectations(cp))

        # 8. Distribution shape stability (optional, for drift detection)
        expectations.extend(self._distribution_shape_expectations(cp))

        return expectations

    # --- Individual expectation builders ---

    def _completeness_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate not-null expectations based on completeness."""
        col = cp.column_name
        if cp.completeness >= 1.0:
            return [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": col},
                    "meta": {
                        "description": f"{col}: 100% complete in profiling",
                        "severity": "critical",
                        "generated_from": "profiling",
                    },
                }
            ]
        elif cp.completeness >= self._completeness_threshold:
            return [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": col, "mostly": round(cp.completeness, 4)},
                    "meta": {
                        "description": f"{col}: {cp.completeness:.1%} complete in profiling",
                        "severity": "warning",
                        "generated_from": "profiling",
                    },
                }
            ]
        return []

    def _uniqueness_expectations(
        self, cp: ColumnProfile, profile: DataFrameProfile
    ) -> list[dict[str, Any]]:
        """Generate uniqueness expectation if column appears unique."""
        if self._has_verified_single_column_key_candidate(cp, profile):
            return []

        if (
            cp.approximate_num_distinct is not None
            and profile.num_records > 0
            and cp.approximate_num_distinct / profile.num_records
            >= self._uniqueness_threshold
        ):
            return [
                {
                    "type": "expect_column_values_to_be_unique",
                    "kwargs": {"column": cp.column_name},
                    "meta": {
                        "description": (
                            f"{cp.column_name}: ~{cp.approximate_num_distinct} distinct "
                            f"out of {profile.num_records} rows"
                        ),
                        "severity": "warning",
                        "generated_from": "profiling",
                    },
                }
            ]
        return []

    def _has_verified_single_column_key_candidate(
        self, cp: ColumnProfile, profile: DataFrameProfile
    ) -> bool:
        """Return true when exact key evidence supersedes approximate uniqueness."""
        for candidate in profile.key_candidates or []:
            if (
                candidate.verified_exact is True
                and candidate.exact_unique is True
                and candidate.emitted is True
                and len(candidate.columns) == 1
                and candidate.columns[0] == cp.column_name
            ):
                return True
        return False

    def _numeric_range_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate value-range expectations for numeric columns."""
        if cp.minimum is None or cp.maximum is None:
            return []

        col = cp.column_name
        min_val = cp.minimum
        max_val = cp.maximum

        if self._strictness == "tight":
            # Exact observed bounds
            pass
        elif self._strictness == "medium":
            # Add tolerance to handle natural variation
            span = max_val - min_val
            if span > 0:
                min_val = min_val - span * self._tolerance
                max_val = max_val + span * self._tolerance
            else:
                # Single value — add absolute tolerance
                min_val = min_val - abs(min_val) * self._tolerance - 1
                max_val = max_val + abs(max_val) * self._tolerance + 1
        elif self._strictness == "loose":
            # Use p5/p95 if available
            if cp.quantiles and "p5" in cp.quantiles and "p95" in cp.quantiles:
                min_val = cp.quantiles["p5"]
                max_val = cp.quantiles["p95"]
            # else fall back to observed min/max with 2x tolerance
            else:
                span = max_val - min_val
                min_val = min_val - span * self._tolerance * 2
                max_val = max_val + span * self._tolerance * 2

        # Round for readability
        min_val = round(min_val, 4) if isinstance(min_val, float) else min_val
        max_val = round(max_val, 4) if isinstance(max_val, float) else max_val

        return [
            {
                "type": "expect_column_values_to_be_between",
                "kwargs": {"column": col, "min_value": min_val, "max_value": max_val},
                "meta": {
                    "description": f"{col}: values in [{min_val}, {max_val}]",
                    "severity": "warning",
                    "generated_from": "profiling",
                    "strictness": self._strictness,
                    "observed_min": cp.minimum,
                    "observed_max": cp.maximum,
                },
            }
        ]

    def _quantile_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate quantile-based distribution bounds (drift detection)."""
        if not cp.quantiles or len(cp.quantiles) < 3:
            return []

        col = cp.column_name
        q = cp.quantiles

        # Build quantile value pairs for GX
        # expect_column_quantile_values_to_be_between
        quantile_ranges = {}
        for label, value in q.items():
            if value is not None:
                # Allow 20% tolerance around each quantile
                margin = abs(value) * 0.2 + 1  # +1 to handle zeros
                quantile_ranges[label] = {
                    "value": value,
                    "min": round(value - margin, 4),
                    "max": round(value + margin, 4),
                }

        if not quantile_ranges:
            return []

        # Convert to GX format
        quantiles_list = []
        value_ranges = []
        prob_map = {"p5": 0.05, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p95": 0.95}

        for label in sorted(quantile_ranges.keys(), key=lambda x: prob_map.get(x, 0)):
            if label in prob_map:
                qr = quantile_ranges[label]
                quantiles_list.append(prob_map[label])
                value_ranges.append([qr["min"], qr["max"]])

        if not quantiles_list:
            return []

        return [
            {
                "type": "expect_column_quantile_values_to_be_between",
                "kwargs": {
                    "column": col,
                    "quantile_ranges": {
                        "quantiles": quantiles_list,
                        "value_ranges": value_ranges,
                    },
                },
                "meta": {
                    "description": f"{col}: distribution quantiles within tolerance",
                    "severity": "info",
                    "generated_from": "profiling",
                    "observed_quantiles": cp.quantiles,
                },
            }
        ]

    def _value_set_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate value-set expectations for low-cardinality columns."""
        if not cp.distinct_values:
            return []

        from tablespec.type_mappings import is_numeric_data_type

        meta: dict[str, Any] = {
            "description": (
                f"{cp.column_name}: values must be in observed set "
                f"of {len(cp.distinct_values)} values"
            ),
            "severity": "warning",
            "generated_from": "profiling",
        }
        # A numeric column's value-set holds numeric literals (e.g. 1.5, 2.0). On the
        # RAW all-string stage those never match the string representation ("1.50"), so
        # pin numeric value-sets to the typed (ingested) stage. classify_validation_type
        # sees only the type (-> raw for in_set); execute_staged honors this explicit
        # meta stage. String value-sets keep the default raw classification.
        if is_numeric_data_type(cp.data_type):
            meta["validation_stage"] = "ingested"

        return [
            {
                "type": "expect_column_values_to_be_in_set",
                "kwargs": {
                    "column": cp.column_name,
                    "value_set": cp.distinct_values,
                },
                "meta": meta,
            }
        ]

    def _string_length_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate string length bounds."""
        if cp.string_length_min is None and cp.string_length_max is None:
            return []

        kwargs: dict[str, Any] = {"column": cp.column_name}
        if cp.string_length_min is not None:
            kwargs["min_value"] = cp.string_length_min
        if cp.string_length_max is not None:
            kwargs["max_value"] = cp.string_length_max

        return [
            {
                "type": "expect_column_value_lengths_to_be_between",
                "kwargs": kwargs,
                "meta": {
                    "description": (
                        f"{cp.column_name}: lengths in "
                        f"[{cp.string_length_min}, {cp.string_length_max}]"
                    ),
                    "severity": "warning",
                    "generated_from": "profiling",
                },
            }
        ]

    def _pattern_expectations(self, cp: ColumnProfile) -> list[dict[str, Any]]:
        """Generate regex expectations from detected value patterns."""
        if not cp.value_pattern:
            return []

        regex = _pattern_to_regex(cp.value_pattern)

        return [
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {
                    "column": cp.column_name,
                    "regex": regex,
                    "mostly": self._pattern_confidence,
                },
                "meta": {
                    "description": (
                        f"{cp.column_name}: values match pattern "
                        f"'{cp.value_pattern}' → regex {regex}"
                    ),
                    "severity": "info",
                    "generated_from": "profiling",
                    "source_pattern": cp.value_pattern,
                },
            }
        ]

    def _distribution_shape_expectations(
        self, cp: ColumnProfile
    ) -> list[dict[str, Any]]:
        """Generate distribution shape bounds for drift detection.

        Only emitted when we have enough data to be meaningful (skewness
        and kurtosis both present). These are informational — major shifts
        in distribution shape indicate upstream data changes.
        """
        if cp.skewness is None or cp.kurtosis is None:
            return []

        # Allow wide tolerance — we just want to catch dramatic shifts
        skew_tolerance = max(abs(cp.skewness) * 0.5, 1.0)
        max(abs(cp.kurtosis) * 0.5, 2.0)

        return [
            {
                "type": "expect_column_skewness_to_be_between",
                "kwargs": {
                    "column": cp.column_name,
                    "min_value": round(cp.skewness - skew_tolerance, 4),
                    "max_value": round(cp.skewness + skew_tolerance, 4),
                },
                "meta": {
                    "description": (
                        f"{cp.column_name}: skewness ~{cp.skewness} "
                        f"(tolerance ±{skew_tolerance:.2f})"
                    ),
                    "severity": "info",
                    "generated_from": "profiling",
                    "observed_skewness": cp.skewness,
                    "observed_kurtosis": cp.kurtosis,
                },
            }
        ]
