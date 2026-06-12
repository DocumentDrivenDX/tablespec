"""Generate Great Expectations baseline expectations from UMF metadata.

This module provides deterministic expectation generation from UMF schema files,
with no dependencies on Spark or profiling data.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml

from tablespec.format_utils import convert_umf_format_to_strftime

logger = logging.getLogger(__name__)

# Required baseline expectation types that must exist for every column
# Note: expect_column_to_exist was removed because it is redundant with schema metadata
REQUIRED_BASELINE_EXPECTATION_TYPES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Raw-suite typing (FEAT-031 SUITE-01..03)
# ---------------------------------------------------------------------------
# String-shape checks assert facts about STRING-rendered values (character
# length, regex shape, strftime format, string->type castability). They are
# meaningful only against the all-STRING raw landing of text-landed sources
# (ADR-007); against NATIVE-TYPED raw (parquet/jdbc, ADR-015) they are at best
# meaningless and at worst force a typed column back through string parsing.
#
# Design choice (SUITE-01/02 seam): the raw-typing branch lives HERE, at suite
# COMPOSITION time, keyed on the UMF's declared ``source.kind`` -- not in the
# executor. Stage ROUTING stays data-driven via the existing classification
# (``classify_validation_type`` / ``ExpectationMeta.stage``, SUITE-03):
# composition decides WHAT belongs in a typed-raw suite, the executor keeps
# deciding WHERE each expectation runs. Typed raw keeps its schema-type and
# nullability conformance checks (structural column count/order + not-null)
# and every ingested-stage check; only raw-stage string-shape checks are
# withheld. Delimited / legacy UMFs (no ``source:`` block) are untouched.
STRING_SHAPE_EXPECTATION_TYPES: frozenset[str] = frozenset(
    {
        # Character-length checks
        "expect_column_value_lengths_to_be_between",
        "expect_column_value_lengths_to_equal",
        # Regex shape checks
        "expect_column_values_to_match_regex",
        "expect_column_values_to_match_regex_list",
        "expect_column_values_to_not_match_regex",
        "expect_column_values_to_not_match_regex_list",
        # String date/time format checks
        "expect_column_values_to_match_strftime_format",
        # String->type castability (typed raw never string-parses, PARQ-02/JDBC-03)
        "expect_column_values_to_cast_to_type",
    }
)


def raw_stage_is_typed(umf_data: dict[str, Any]) -> bool:
    """True when *umf_data* declares a source whose raw landing is native-typed.

    Data-driven off the UMF's ``source.kind`` (SRC-04): ``jdbc`` and
    ``parquet`` land typed raw; ``delimited`` (or no ``source:`` block at all,
    the legacy spelling) lands all-STRING raw.
    """
    from tablespec.models.umf import TYPED_RAW_SOURCE_KINDS

    source = umf_data.get("source") or {}
    if not isinstance(source, dict):  # tolerate a model instance
        source = {"kind": getattr(source, "kind", None)}
    return source.get("kind") in TYPED_RAW_SOURCE_KINDS


def drop_string_shape_raw_expectations(
    expectations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove RAW-stage string-shape checks from *expectations* (SUITE-01).

    Only expectations that are BOTH string-shape typed AND effectively
    raw-stage (explicit ``meta.validation_stage`` first, classification
    fallback -- the same precedence the staged executor applies) are dropped;
    an explicitly ingested-stage check always survives (SUITE-03).
    """
    from tablespec.models.umf import classify_validation_type

    kept: list[dict[str, Any]] = []
    for exp in expectations:
        exp_type = exp.get("type", exp.get("expectation_type", ""))
        if exp_type in STRING_SHAPE_EXPECTATION_TYPES:
            stage = exp.get("meta", {}).get(
                "validation_stage"
            ) or classify_validation_type(exp_type)
            if stage == "raw":
                continue
        kept.append(exp)
    return kept


class DomainTypeExpectationGenerator:
    """Generate expectations from domain type specifications.

    This generator creates validation expectations based on pre-defined
    domain type specifications in the domain_types.yaml registry.
    """

    def __init__(self) -> None:
        """Initialize domain type expectation generator."""
        self.logger = logging.getLogger(self.__class__.__name__)
        # Lazy import to avoid circular dependencies
        self._registry = None

    @property
    def registry(self):
        """Lazy load the domain type registry."""
        if self._registry is None:
            try:
                from tablespec.inference.domain_types import DomainTypeRegistry

                self._registry = DomainTypeRegistry()
            except ImportError:
                self.logger.debug("DomainTypeRegistry not available")
                self._registry = None
        return self._registry

    def generate_domain_type_expectations(
        self, column: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate expectations based on column's domain type.

        Args:
        ----
            column: Column dictionary from UMF with potential domain_type field

        Returns:
        -------
            List of expectation dictionaries based on domain type

        """
        expectations = []

        # Check if column has a domain type
        domain_type = column.get("domain_type")
        if not domain_type:
            return expectations

        # Check if registry is available
        if self.registry is None:
            return expectations

        # Get validation specs from registry (can be multiple validations per domain)
        validation_specs = self.registry.get_validation_specs(domain_type)
        if not validation_specs:
            self.logger.debug(
                f"No validation specs found for domain type: {domain_type}"
            )
            return expectations

        # Create expectation for each validation spec
        for validation_spec in validation_specs:
            expectation = {
                "type": validation_spec["type"],
                "kwargs": {
                    "column": column["name"],
                    **validation_spec.get("kwargs", {}),
                },
                "meta": {
                    "description": f"Column {column['name']} must conform to {domain_type} domain type standards",
                    "severity": validation_spec.get("severity", "warning"),
                    "generated_from": "domain_type",
                    "domain_type": domain_type,
                },
            }

            expectations.append(expectation)
            self.logger.debug(
                f"Generated domain type expectation for {column['name']}: "
                + f"{validation_spec['type']} (domain: {domain_type})"
            )

        return expectations


# Backward compatibility alias
def _convert_umf_date_format_to_strftime(umf_format: str) -> str:
    """Deprecated: Use convert_umf_format_to_strftime() from format_utils instead."""
    return convert_umf_format_to_strftime(umf_format)


class BaselineExpectationGenerator:
    """Generate baseline Great Expectations rules from UMF metadata.

    This generates simple, deterministic expectations that don't require LLM reasoning:
    - Nullability (from UMF nullable field)
    - Length constraints (from UMF length/max_length)
    - Structural checks (column count, column list)
    - Date/timestamp/numeric casting validation
    - Domain type validations (from domain_types.yaml registry)
    - Profiling-based expectations (uniqueness, ranges, completeness)

    Note: Column existence and column type expectations are intentionally NOT generated
    as they are classified as REDUNDANT_VALIDATION_TYPES (covered by schema metadata).
    """

    def __init__(self) -> None:
        """Initialize the baseline expectation generator."""
        self.domain_type_generator = DomainTypeExpectationGenerator()

    def generate_baseline_expectations(
        self, umf_data: dict[str, Any], include_structural: bool = True
    ) -> list[dict[str, Any]]:
        """Generate baseline expectations from UMF metadata.

        Args:
        ----
            umf_data: UMF dictionary (loaded from YAML)
            include_structural: Include table-level structural checks

        Returns:
        -------
            List of expectation dictionaries

        """
        expectations = []

        # Structural checks (table-level)
        if include_structural:
            expectations.extend(self._generate_structural_expectations(umf_data))

        # Column-level baseline expectations
        context_column = umf_data.get("context_column")
        for column in umf_data.get("columns", []):
            expectations.extend(
                self.generate_baseline_column_expectations(
                    column, context_column=context_column
                )
            )

        # Cross-column expectations (date ordering, etc.)
        expectations.extend(self._generate_cross_column_expectations(umf_data))

        # Raw-suite typing (FEAT-031 SUITE-01/02): sources that land
        # NATIVE-TYPED raw (jdbc/parquet) never receive raw-stage string-shape
        # checks; their schema-type/nullability and ingested-stage checks
        # remain. Delimited / legacy UMFs are returned unchanged.
        if raw_stage_is_typed(umf_data):
            expectations = drop_string_shape_raw_expectations(expectations)

        return expectations

    def _generate_structural_expectations(
        self, umf_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate table-level structural expectations.

        Args:
        ----
            umf_data: UMF dictionary

        Returns:
        -------
            List of structural expectation dictionaries

        """
        expectations = []
        columns = umf_data.get("columns", [])
        column_names = [col["name"] for col in columns]

        # Expect specific column count
        if columns:
            expectations.append(
                {
                    "type": "expect_table_column_count_to_equal",
                    "kwargs": {"value": len(columns)},
                    "meta": {
                        "description": f"Table must have exactly {len(columns)} columns",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )

            # Expect columns to match ordered list
            expectations.append(
                {
                    "type": "expect_table_columns_to_match_ordered_list",
                    "kwargs": {"column_list": column_names},
                    "meta": {
                        "description": "Table columns must match expected schema in order",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )

        return expectations

    def _generate_cross_column_expectations(
        self, umf_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate cross-column expectations from column relationships.

        Detects date-range pairs (start/end patterns) and generates
        expect_column_pair_values_a_to_be_greater_than_b expectations.

        Args:
        ----
            umf_data: UMF dictionary (loaded from YAML)

        Returns:
        -------
            List of expectation dictionaries

        """
        expectations = []
        columns = umf_data.get("columns", [])

        # Build lookup of date/datetime columns
        date_columns: dict[str, dict[str, Any]] = {}
        for col in columns:
            dt = col.get("data_type", "").upper()
            if dt in ("DATE", "DATETIME", "TIMESTAMP"):
                date_columns[col["name"]] = col

        # Detect start/end pairs by naming convention
        start_patterns = ("start_", "begin_", "effective_", "from_")
        end_patterns = ("end_", "stop_", "expiry_", "to_", "termination_")

        start_cols = [
            name
            for name in date_columns
            if any(name.lower().startswith(p) for p in start_patterns)
        ]

        for start_col in start_cols:
            # Try to find matching end column
            base = start_col.lower()
            for prefix in start_patterns:
                if base.startswith(prefix):
                    base = base[len(prefix) :]
                    break

            for end_prefix in end_patterns:
                candidate = end_prefix + base
                # Case-insensitive match
                for name in date_columns:
                    if name.lower() == candidate:
                        expectations.append(
                            {
                                "type": "expect_column_pair_values_a_to_be_greater_than_b",
                                "kwargs": {
                                    "column_A": name,  # end date
                                    "column_B": start_col,  # start date
                                    "or_equal": True,
                                },
                                "meta": {
                                    "description": f"{name} should be >= {start_col} (date range ordering)",
                                    "severity": "warning",
                                    "generated_from": "baseline",
                                },
                            }
                        )

        return expectations

    def generate_baseline_column_expectations(
        self,
        column: dict[str, Any],
        context_column: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate baseline expectations for a single column from UMF metadata.

        This includes both standard baseline expectations and domain type expectations.

        Args:
        ----
            column: Column dictionary from UMF
            context_column: Optional name of the context column (e.g. "LOB").
                When set, per-context nullable rules emit filtered expectations
                using ``row_condition``.

        Returns:
        -------
            List of expectation dictionaries

        """
        expectations = []
        column_name = column["name"]
        data_type = column.get("data_type", "STRING")

        # 1. Nullability (from UMF nullable field, not profiling)
        # Note: expect_column_to_exist and expect_column_values_to_be_of_type
        # are no longer generated here as they are in REDUNDANT_VALIDATION_TYPES
        nullable = column.get("nullable", {})
        if nullable:
            if isinstance(nullable, dict):
                # Dict format: {context: is_nullable} e.g. {"MD": False, "MP": True}
                required_contexts = [
                    ctx for ctx, is_null in nullable.items() if not is_null
                ]
                if required_contexts:
                    if context_column:
                        # Per-context expectations using row_condition
                        for ctx in required_contexts:
                            expectations.append(
                                {
                                    "type": "expect_column_values_to_not_be_null",
                                    "kwargs": {
                                        "column": column_name,
                                        "row_condition": f"{context_column}='{ctx}'",
                                        # row_condition uses Spark SQL syntax — requires
                                        # a Spark or Sail session.
                                        "condition_parser": "spark",
                                    },
                                    "meta": {
                                        "description": f"Column {column_name} is required (nullable=false) for {context_column}='{ctx}'",
                                        "severity": "critical",
                                        "contexts": [ctx],
                                        "generated_from": "baseline",
                                    },
                                }
                            )
                    else:
                        # No context_column — most-restrictive-wins (global not-null)
                        expectations.append(
                            {
                                "type": "expect_column_values_to_not_be_null",
                                "kwargs": {"column": column_name},
                                "meta": {
                                    "description": f"Column {column_name} is required (nullable=false) for contexts: {', '.join(required_contexts)}",
                                    "severity": "critical",
                                    "contexts": required_contexts,
                                    "generated_from": "baseline",
                                },
                            }
                        )
            # If nullable is True (bool), column IS nullable — no not-null expectation needed

        # 2. Length constraints
        max_length = column.get("max_length") or column.get("length")
        if max_length:
            expectations.append(
                {
                    "type": "expect_column_value_lengths_to_be_between",
                    "kwargs": {"column": column_name, "max_value": max_length},
                    "meta": {
                        "description": f"Column {column_name} values must not exceed {max_length} characters (from UMF max_length/length)",
                        "severity": "warning",
                        "generated_from": "baseline",
                    },
                }
            )

        # 2.5 Embedding dimensionality
        if data_type.upper() == "EMBEDDING":
            dimension = column.get("dimension")
            if dimension is not None:
                expectations.append(
                    {
                        "type": "expect_column_value_lengths_to_equal",
                        "kwargs": {"column": column_name, "value": dimension},
                        "meta": {
                            "description": f"Column {column_name} values must have exactly {dimension} elements",
                            "severity": "critical",
                            "validation_stage": "ingested",
                            "generated_from": "baseline",
                        },
                    }
                )
                if dimension % 16 != 0:
                    expectations.append(
                        {
                            "type": "expect_embedding_dimension_multiple_of_16_advisory",
                            "kwargs": {
                                "column": column_name,
                                "dimension": dimension,
                            },
                            "meta": {
                                "description": (
                                    f"Column {column_name} has dimension {dimension}; "
                                    "storage-optimized Databricks Vector Search endpoints "
                                    "require dimensions divisible by 16"
                                ),
                                "severity": "info",
                                "blocking": False,
                                "validation_stage": "ingested",
                                "generated_from": "baseline",
                            },
                        }
                    )

        # 3. Date format and casting validation (if DATE type)
        if data_type == "DateType" or data_type.upper() == "DATE":
            umf_format = column.get("format", "YYYY-MM-DD")
            expectations.append(
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {
                        "column": column_name,
                        "target_type": "DATE",
                        "format": umf_format,
                        "mostly": 1.0,
                    },
                    "meta": {
                        "description": f"Column {column_name} values must successfully cast to DATE with format {umf_format} (catches invalid dates like 2023-02-30)",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )
            strict_format = column.get("format")
            if strict_format:
                expectations.append(
                    {
                        "type": "expect_column_values_to_match_strftime_format",
                        "kwargs": {
                            "column": column_name,
                            "strftime_format": convert_umf_format_to_strftime(
                                strict_format
                            ),
                        },
                        "meta": {
                            "description": f"Column {column_name} values must match format {strict_format}",
                            "severity": "info",
                            "generated_from": "baseline",
                        },
                    }
                )
            else:
                # Legacy fallback: default date format check when no explicit format specified
                expectations.append(
                    {
                        "type": "expect_column_values_to_match_strftime_format",
                        "kwargs": {"column": column_name, "strftime_format": "%Y%m%d"},
                        "meta": {
                            "description": f"Column {column_name} must match YYYYMMDD date format (standard for DATE type)",
                            "severity": "warning",
                            "generated_from": "baseline",
                        },
                    }
                )

        # 4. Timestamp casting validation (if DATETIME/TIMESTAMP type)
        if data_type in ("TimestampType", "DateTimeType") or data_type.upper() in (
            "DATETIME",
            "TIMESTAMP",
        ):
            # Read format from UMF column, default to YYYY-MM-DD HH:MM:SS if not specified
            timestamp_format = column.get("format", "YYYY-MM-DD HH:MM:SS")
            expectations.append(
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {
                        "column": column_name,
                        "target_type": "TIMESTAMP",
                        "format": timestamp_format,
                        "mostly": 1.0,
                    },
                    "meta": {
                        "description": f"Column {column_name} values must successfully cast to TIMESTAMP with format {timestamp_format}",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )
            strict_format = column.get("format")
            if strict_format:
                expectations.append(
                    {
                        "type": "expect_column_values_to_match_strftime_format",
                        "kwargs": {
                            "column": column_name,
                            "strftime_format": convert_umf_format_to_strftime(
                                strict_format
                            ),
                        },
                        "meta": {
                            "description": f"Column {column_name} values must match format {strict_format}",
                            "severity": "info",
                            "generated_from": "baseline",
                        },
                    }
                )

        # 5. Integer casting validation (if INTEGER type)
        if data_type == "IntegerType" or data_type.upper() == "INTEGER":
            expectations.append(
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {
                        "column": column_name,
                        "target_type": "INTEGER",
                        "mostly": 1.0,
                    },
                    "meta": {
                        "description": f"Column {column_name} values must successfully cast to INTEGER (no letters or decimals)",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )

        # 6. Numeric casting validation (if FLOAT/DOUBLE/DECIMAL type)
        if data_type in (
            "FloatType",
            "DoubleType",
            "DecimalType",
        ) or data_type.upper() in (
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
        ):
            expectations.append(
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {
                        "column": column_name,
                        "target_type": "DOUBLE",
                        "mostly": 1.0,
                    },
                    "meta": {
                        "description": f"Column {column_name} values must successfully cast to numeric type",
                        "severity": "critical",
                        "generated_from": "baseline",
                    },
                }
            )

        # 7. Domain type expectations (if applicable)
        domain_expectations = (
            self.domain_type_generator.generate_domain_type_expectations(column)
        )
        expectations.extend(domain_expectations)

        # 8. Profiling-based expectations (if profiling data attached to column)
        profiling_expectations = self._generate_profiling_expectations(column)
        expectations.extend(profiling_expectations)

        return expectations

    def _generate_profiling_expectations(
        self, column: dict[str, Any], strictness: str = "medium"
    ) -> list[dict[str, Any]]:
        """Generate expectations from profiling data attached to UMF column.

        Args:
        ----
            column: Column dictionary from UMF with optional profiling data
            strictness: Strictness level (reserved for future use)

        Returns:
        -------
            List of expectation dictionaries derived from profiling statistics

        """
        expectations: list[dict[str, Any]] = []
        profiling = column.get("profiling", {})
        if not profiling:
            return expectations

        col_name = column["name"]

        # Check what baseline already covers to avoid duplicates
        nullable = column.get("nullable", {})
        has_baseline_not_null = isinstance(nullable, dict) and any(
            not v for v in nullable.values()
        )
        has_baseline_length = bool(column.get("max_length") or column.get("length"))

        # Uniqueness from high cardinality (use threshold for approximate counts)
        num_distinct = profiling.get("approximate_num_distinct")
        num_records = profiling.get("num_records")
        if num_distinct and num_records and num_distinct >= 0.99 * num_records:
            expectations.append(
                {
                    "type": "expect_column_values_to_be_unique",
                    "kwargs": {"column": col_name},
                    "meta": {
                        "description": f"Column {col_name} appears unique based on profiling",
                        "severity": "warning",
                        "generated_from": "profiling",
                    },
                }
            )

        # Range from min/max (canonical location: profiling.statistics.min/max)
        statistics = profiling.get("statistics", {})
        minimum = statistics.get("min")
        maximum = statistics.get("max")
        if minimum is not None and maximum is not None:
            expectations.append(
                {
                    "type": "expect_column_values_to_be_between",
                    "kwargs": {
                        "column": col_name,
                        "min_value": minimum,
                        "max_value": maximum,
                    },
                    "meta": {
                        "description": f"Column {col_name} values between {minimum} and {maximum} based on profiling",
                        "severity": "warning",
                        "generated_from": "profiling",
                    },
                }
            )

        # Not-null from high completeness (skip if baseline already generates not-null)
        completeness = profiling.get("completeness")
        if not has_baseline_not_null:
            if completeness is not None and completeness > 0.99:
                expectations.append(
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": col_name},
                        "meta": {
                            "description": f"Column {col_name} has {completeness:.1%} completeness in profiling",
                            "severity": "warning",
                            "generated_from": "profiling",
                        },
                    }
                )
            elif completeness is not None and completeness >= 0.95:
                # Soft null check for moderate completeness
                expectations.append(
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": col_name, "mostly": completeness},
                        "meta": {
                            "description": f"Column {col_name} has {completeness:.1%} completeness in profiling (soft check)",
                            "severity": "warning",
                            "generated_from": "profiling",
                        },
                    }
                )

        # Value set from low-cardinality columns
        distinct_values = profiling.get("distinct_values")
        if distinct_values:
            from tablespec.type_mappings import is_numeric_data_type

            in_set_meta: dict[str, Any] = {
                "description": f"Column {col_name} values must be in observed set of {len(distinct_values)} values",
                "severity": "warning",
                "generated_from": "profiling",
            }
            # Numeric value-sets hold numeric literals; validate on the typed (ingested)
            # stage, not the raw all-string stage where 1.5 != "1.50".
            if is_numeric_data_type(column.get("data_type")):
                in_set_meta["validation_stage"] = "ingested"
            expectations.append(
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": col_name, "value_set": distinct_values},
                    "meta": in_set_meta,
                }
            )

        # String length from profiling (skip if baseline already generates length from max_length)
        string_lengths = profiling.get("string_lengths", {})
        sl_min = string_lengths.get("min_length")
        sl_max = string_lengths.get("max_length")
        if (sl_min is not None or sl_max is not None) and not has_baseline_length:
            kwargs: dict[str, Any] = {"column": col_name}
            if sl_min is not None:
                kwargs["min_value"] = sl_min
            if sl_max is not None:
                kwargs["max_value"] = sl_max
            expectations.append(
                {
                    "type": "expect_column_value_lengths_to_be_between",
                    "kwargs": kwargs,
                    "meta": {
                        "description": f"Column {col_name} string lengths between {sl_min} and {sl_max} based on profiling",
                        "severity": "warning",
                        "generated_from": "profiling",
                    },
                }
            )

        # Regex patterns from profiling (detected format patterns)
        patterns = profiling.get("patterns", [])
        if not patterns:
            patterns = profiling.get("format_patterns", [])
        if patterns:
            # Use the most common pattern (first in list)
            primary_pattern = patterns[0] if isinstance(patterns, list) else patterns
            if isinstance(primary_pattern, str):
                expectations.append(
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {
                            "column": col_name,
                            "regex": primary_pattern,
                            "mostly": 0.95,
                        },
                        "meta": {
                            "description": f"Column {col_name} values should match pattern {primary_pattern} based on profiling",
                            "severity": "warning",
                            "generated_from": "profiling",
                        },
                    }
                )

        return expectations


class UmfToGxMapper:
    """Maps UMF with optional profiling data to Great Expectations expectation suite.

    This class provides full Great Expectations suite generation including:
    - Baseline expectations from UMF metadata
    - Profiling-based expectations (if profiling data is present)
    - Complete suite structure with metadata
    """

    def __init__(self) -> None:
        """Initialize the UMF to GX mapper."""
        self.baseline_generator = BaselineExpectationGenerator()

    def generate_expectations(
        self,
        umf_file: Path | str,
        strictness: Literal["loose", "medium", "strict"] = "medium",
    ) -> dict[str, Any]:
        """Generate GX expectation suite from UMF with profiling data.

        Args:
        ----
            umf_file: Path to UMF YAML file
            strictness: Strictness level (loose, medium, strict)

        Returns:
        -------
            Dictionary representing GX expectation suite

        """
        # Load UMF
        umf_path = Path(umf_file)
        with umf_path.open(encoding="utf-8") as f:
            umf = yaml.safe_load(f)

        table_name = umf.get("table_name", "unknown")
        logger.info(
            f"Generating expectations for {table_name} with strictness={strictness}"
        )

        # Build expectation suite
        suite = {
            "name": f"{table_name}_suite",
            "meta": {
                "table_name": table_name,
                "generated_by": "tablespec",
                "strictness": strictness,
                "source_umf": str(umf_path),
            },
            "expectations": [],
        }

        # Generate all expectations (baseline + profiling) from UMF metadata
        # BaselineExpectationGenerator handles both baseline and profiling expectations
        suite["expectations"].extend(
            self.baseline_generator.generate_baseline_expectations(umf)
        )

        logger.info(f"Generated {len(suite['expectations'])} expectations")
        return suite
