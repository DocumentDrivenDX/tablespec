"""Custom Great Expectations for Spark-specific validation.

This module provides custom GX expectations that validate actual Spark casting
behavior rather than just pattern matching. These expectations catch edge cases
like "2023-02-30" (valid format, invalid date) that pass regex validation but
fail when Spark attempts to cast them.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from typing import Protocol

    class ExpectationConfiguration(Protocol):  # type: ignore[misc]
        """Protocol for ExpectationConfiguration when GX unavailable."""

        kwargs: dict[str, Any]


try:
    from great_expectations.expectations.expectation import Expectation

    _gx_available = True
except ImportError:
    _gx_available = False
    # Create dummy class for type hints when GX not available
    Expectation = object  # type: ignore[misc, assignment]

GX_AVAILABLE = _gx_available

try:
    from pyspark.sql import functions as F

    _spark_available = True
except ImportError:
    _spark_available = False

SPARK_AVAILABLE = _spark_available


logger = logging.getLogger(__name__)


def validate_column_pair_date_order(
    dataframe: Any,
    value_column: str,
    reference_column: str,
    *,
    or_equal: bool = True,
    mostly: float = 1.0,
) -> dict[str, Any]:
    """Compatibility helper for validating date ordering between two columns."""
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for date order validation"
        raise ImportError(msg)

    # Use the DataFrame's own bound columns (``dataframe[col]``) rather than
    # ``F.col(col)``. ``pyspark.sql.functions.col`` builds a CLASSIC Column when a
    # classic JVM session is active in the process, which fails when ``dataframe``
    # is a Spark CONNECT DataFrame (``'Column' object is not callable`` inside the
    # connect plan). Bound columns are always session-correct. Behavior-identical
    # on classic Spark and on real Databricks serverless (Spark Connect).
    value_col = dataframe[value_column]
    reference_col = dataframe[reference_column]

    scoped = dataframe.filter(value_col.isNotNull() & reference_col.isNotNull())
    element_count = scoped.count()
    if element_count == 0:
        return {
            "success": True,
            "result": {
                "element_count": 0,
                "unexpected_count": 0,
                "unexpected_percent": 0.0,
                "partial_unexpected_list": [],
                "observed_value": f"{value_column} vs {reference_column}: no non-null pairs",
            },
        }

    scoped_value = scoped[value_column]
    scoped_reference = scoped[reference_column]
    comparator = (
        scoped_value >= scoped_reference
        if or_equal
        else scoped_value > scoped_reference
    )
    unexpected_df = scoped.filter(~comparator)
    unexpected_count = unexpected_df.count()
    unexpected_percent = unexpected_count / element_count * 100
    success_ratio = 1.0 - (unexpected_count / element_count)

    sample_rows = (
        unexpected_df.select(value_column, reference_column).limit(10).collect()
    )
    operator = "<" if or_equal else "<="
    partial_unexpected_list = [
        f"{row[value_column]} {operator} {row[reference_column]}" for row in sample_rows
    ]

    return {
        "success": success_ratio >= mostly,
        "result": {
            "element_count": element_count,
            "unexpected_count": unexpected_count,
            "unexpected_percent": unexpected_percent,
            "partial_unexpected_list": partial_unexpected_list,
            "observed_value": (
                f"{value_column} {'>=' if or_equal else '>'} {reference_column} "
                f"for {success_ratio * 100:.2f}% of non-null rows"
            ),
        },
    }


# Great Expectations Expectation Classes
if GX_AVAILABLE:

    class ExpectColumnValuesToCastToType(Expectation):  # type: ignore[misc]
        """Expect column values to successfully cast to a specified type.

        This expectation validates that values can be cast to the target type
        without becoming NULL, catching edge cases like invalid dates.

        This is a Spark-specific custom expectation that validates actual casting
        behavior rather than just pattern matching.
        """

        expectation_type = "expect_column_values_to_cast_to_type"

        # These define the parameters this expectation accepts
        success_keys = (
            "column",
            "target_type",
            "format",  # Optional UMF format string for DATE/TIMESTAMP
            "fallback_formats",  # Optional list of alternative formats to try
            "mostly",
        )

        # Default values for parameters
        default_kwarg_values: ClassVar[dict[str, Any]] = {
            "format": None,  # Optional - if None, uses Spark default casting
            "fallback_formats": None,  # Optional - list of fallback formats for mixed data
            "mostly": 1.0,
            "result_format": "BASIC",
        }

        # Configure Pydantic to allow our custom fields
        class Config:
            extra = "allow"  # Allow additional fields beyond the base Expectation model

        def validate_configuration(
            self, configuration: ExpectationConfiguration | None = None
        ) -> None:
            """Validate that configuration is correct."""
            super().validate_configuration(configuration)  # type: ignore[arg-type]  # GX base class accepts None but type stub is incomplete

            if configuration:
                target_type = configuration.kwargs.get("target_type")
                if target_type:
                    valid_types = [
                        "DATE",
                        "INTEGER",
                        "DOUBLE",
                        "FLOAT",
                        "TIMESTAMP",
                        "BOOLEAN",
                        "DECIMAL",
                    ]
                    if target_type.upper() not in valid_types:
                        msg = f"target_type must be one of {valid_types}, got {target_type}"
                        raise ValueError(msg)

        def _validate(
            self,
            metrics: dict,
            runtime_configuration: dict | None = None,
            execution_engine: Any = None,
        ) -> dict:
            """Validate expectation against actual data.

            This method is called by GX during actual validation.
            Performs Spark-specific casting validation.
            """
            if not SPARK_AVAILABLE:
                msg = "PySpark is required for custom casting expectations"
                raise ImportError(msg)

            # Extract parameters from self.configuration (set by GX)
            column = self.column  # type: ignore[attr-defined]
            target_type = self.target_type  # type: ignore[attr-defined]
            format_str = getattr(self, "format", None)  # type: ignore[attr-defined]
            fallback_formats = getattr(self, "fallback_formats", None)  # type: ignore[attr-defined]
            mostly = getattr(self, "mostly", 1.0)  # type: ignore[attr-defined]

            # Get Spark DataFrame from execution engine
            # In GX 1.x with Spark, the batch contains the DataFrame
            try:
                from tablespec.casting_utils import (
                    build_flexible_formats,
                    cast_column_with_format,
                    try_parse_flexible_timestamp,
                )

                # Access DataFrame through execution engine's active batch
                df = execution_engine.batch_manager.active_batch.data.dataframe

                # Check if column is already the target type (e.g., Gold tables with pre-typed columns)
                # This avoids trying to parse strings when the column is already DATE/TIMESTAMP
                from pyspark.sql.types import DateType, TimestampType

                col_schema = df.schema[column]
                col_type = col_schema.dataType
                is_already_target_type = (
                    target_type.upper() == "DATE" and isinstance(col_type, DateType)
                ) or (
                    target_type.upper() == "TIMESTAMP"
                    and isinstance(col_type, TimestampType)
                )

                if is_already_target_type:
                    # Column is already the target type - validation passes
                    total_count = df.count()
                    return {
                        "success": True,
                        "result": {
                            "element_count": total_count,
                            "unexpected_count": 0,
                            "unexpected_percent": 0.0,
                            "partial_unexpected_list": [],
                            "observed_value": f"Column already typed as {col_type}",
                        },
                    }

                # Count total non-null values before casting
                original_non_null_count = df.filter(F.col(column).isNotNull()).count()  # type: ignore[attr-defined]

                if original_non_null_count == 0:
                    # Column is entirely NULL - nothing to cast
                    return {
                        "success": True,
                        "result": {
                            "element_count": 0,
                            "unexpected_count": 0,
                            "unexpected_percent": 0.0,
                            "partial_unexpected_list": [],
                            "observed_value": "Column is entirely NULL",
                        },
                    }

                # Use flexible parsing for DATE/TIMESTAMP columns
                if target_type.upper() in ("DATE", "TIMESTAMP"):
                    formats = build_flexible_formats(
                        target_type, format_str, fallback_formats
                    )
                    cast_expr = try_parse_flexible_timestamp(
                        F.col(column),  # type: ignore[attr-defined]
                        primary_format=formats[0] if formats else "",
                        fallback_formats=formats[1:] if len(formats) > 1 else None,
                    )
                    if target_type.upper() == "DATE":
                        cast_expr = cast_expr.cast("date")
                else:
                    # Use shared casting utility (always uses try_to_timestamp for graceful handling)
                    cast_expr = cast_column_with_format(
                        F.col(column),
                        target_type,
                        format_str,
                    )
                casted_df = df.withColumn(f"_casted_{column}", cast_expr)

                # Count nulls after casting (excluding rows that were already null)
                casting_failures_df = casted_df.filter(
                    F.col(column).isNotNull() & F.col(f"_casted_{column}").isNull()  # type: ignore[attr-defined]
                )

                unexpected_count = casting_failures_df.count()
                unexpected_percent = (
                    (unexpected_count / original_non_null_count * 100)
                    if original_non_null_count > 0
                    else 0.0
                )

                # Collect sample of values that failed casting (limited to 20 examples)
                unexpected_values = []
                if unexpected_count > 0:
                    sample_rows = casting_failures_df.select(column).limit(20).collect()
                    unexpected_values = [row[column] for row in sample_rows]

                # Calculate success
                success_percent = (
                    1.0 - (unexpected_count / original_non_null_count)
                    if original_non_null_count > 0
                    else 1.0
                )
                success = success_percent >= mostly

                format_msg = f" with format {format_str}" if format_str else ""
                if fallback_formats:
                    format_msg += f" (fallbacks: {fallback_formats})"
                return {
                    "success": success,
                    "result": {
                        "element_count": original_non_null_count,
                        "unexpected_count": unexpected_count,
                        "unexpected_percent": unexpected_percent,
                        "partial_unexpected_list": unexpected_values[
                            :10
                        ],  # Limit to 10 for reporting
                        "observed_value": f"{success_percent * 100:.2f}% cast successfully to {target_type}{format_msg}",
                    },
                }

            except Exception as e:
                logger.exception(f"Failed to execute casting validation: {e}")
                return {
                    "success": False,
                    "result": {
                        "element_count": 0,
                        "unexpected_count": 0,
                        "unexpected_percent": 0.0,
                        "partial_unexpected_list": [],
                        "observed_value": f"Validation failed: {e!s}",
                    },
                }

    class ExpectColumnDateToBeInCurrentYear(Expectation):  # type: ignore[misc]
        """Expect date column values to fall within the current calendar year.

        This expectation validates that date values are between January 1st and
        December 31st of the current year. Useful for validating gap closure dates,
        transaction dates, or other fields that should only contain current-year data.

        Uses Spark SQL to dynamically compute year bounds at validation time.
        """

        expectation_type = "expect_column_date_to_be_in_current_year"

        # Parameters this expectation accepts
        success_keys = (
            "column",
            "mostly",
        )

        # Default values for parameters
        default_kwarg_values: ClassVar[dict[str, Any]] = {
            "mostly": 1.0,
            "result_format": "BASIC",
        }

        # Configure Pydantic to allow our custom fields
        class Config:
            extra = "allow"

        def _validate(
            self,
            metrics: dict,
            runtime_configuration: dict | None = None,
            execution_engine: Any = None,
        ) -> dict:
            """Validate that date values fall within the current calendar year.

            This method is called by GX during actual validation.
            Uses Spark SQL to compute dynamic year bounds.
            """
            if not SPARK_AVAILABLE:
                msg = "PySpark is required for current year date validation"
                raise ImportError(msg)

            # Extract parameters
            column = self.column  # type: ignore[attr-defined]
            mostly = getattr(self, "mostly", 1.0)  # type: ignore[attr-defined]

            try:
                # Access DataFrame through execution engine's active batch
                df = execution_engine.batch_manager.active_batch.data.dataframe
                spark = df.sparkSession

                # Compute current year bounds using Spark SQL
                bounds_row = spark.sql("""
                    SELECT
                        DATE_TRUNC('YEAR', CURRENT_DATE()) as year_start,
                        DATE_TRUNC('YEAR', CURRENT_DATE()) + INTERVAL '1 YEAR' - INTERVAL '1 DAY' as year_end
                """).first()

                year_start = bounds_row["year_start"]
                year_end = bounds_row["year_end"]

                # Count total non-null date values
                non_null_count = df.filter(F.col(column).isNotNull()).count()

                if non_null_count == 0:
                    return {
                        "success": True,
                        "result": {
                            "element_count": 0,
                            "unexpected_count": 0,
                            "unexpected_percent": 0.0,
                            "partial_unexpected_list": [],
                            "observed_value": "Column is entirely NULL",
                        },
                    }

                # Find dates outside the current year
                out_of_range_df = df.filter(
                    F.col(column).isNotNull()
                    & ((F.col(column) < year_start) | (F.col(column) > year_end))
                )

                unexpected_count = out_of_range_df.count()
                unexpected_percent = (
                    (unexpected_count / non_null_count * 100)
                    if non_null_count > 0
                    else 0.0
                )

                # Collect sample of out-of-range values
                unexpected_values = []
                if unexpected_count > 0:
                    sample_rows = out_of_range_df.select(column).limit(20).collect()
                    unexpected_values = [str(row[column]) for row in sample_rows]

                # Calculate success based on mostly threshold
                success_percent = (
                    1.0 - (unexpected_count / non_null_count)
                    if non_null_count > 0
                    else 1.0
                )
                success = success_percent >= mostly

                return {
                    "success": success,
                    "result": {
                        "element_count": non_null_count,
                        "unexpected_count": unexpected_count,
                        "unexpected_percent": unexpected_percent,
                        "partial_unexpected_list": unexpected_values[:10],
                        "observed_value": f"{success_percent * 100:.2f}% of dates within {year_start} to {year_end}",
                    },
                }

            except Exception as e:
                logger.exception(f"Failed to execute current year validation: {e}")
                return {
                    "success": False,
                    "result": {
                        "element_count": 0,
                        "unexpected_count": 0,
                        "unexpected_percent": 0.0,
                        "partial_unexpected_list": [],
                        "observed_value": f"Validation failed: {e!s}",
                    },
                }

    class ExpectColumnValuesToMatchDomainType(Expectation):  # type: ignore[misc]
        """Validate column values against a domain type's validation rules.

        Loads the domain type definition from the registry and checks that
        all values comply with the validation spec (regex patterns, value sets, etc.).

        Works with both Spark and Pandas DataFrames.

        kwargs:
            column: str - column name
            domain_type: str - domain type name from registry (e.g., "us_state_code")
            mostly: float - percentage of values that must match (default 1.0)
        """

        expectation_type = "expect_column_values_to_match_domain_type"

        success_keys = (
            "column",
            "domain_type",
            "mostly",
        )

        default_kwarg_values: ClassVar[dict[str, Any]] = {
            "mostly": 1.0,
            "result_format": "BASIC",
        }

        class Config:
            extra = "allow"

        def validate_configuration(
            self, configuration: ExpectationConfiguration | None = None
        ) -> None:
            """Validate that configuration is correct."""
            super().validate_configuration(configuration)  # type: ignore[arg-type]
            if configuration:
                domain_type = configuration.kwargs.get("domain_type")
                if not domain_type:
                    msg = "domain_type is required"
                    raise ValueError(msg)

        def _validate(
            self,
            metrics: dict,
            runtime_configuration: dict | None = None,
            execution_engine: Any = None,
        ) -> dict:
            """Validate column values against domain type rules.

            Supports both Spark and Pandas execution engines.
            """
            column = self.column  # type: ignore[attr-defined]
            domain_type_name = self.domain_type  # type: ignore[attr-defined]
            mostly = getattr(self, "mostly", 1.0)  # type: ignore[attr-defined]

            try:
                # Get DataFrame - works for both Spark and Pandas engines
                batch_data = execution_engine.batch_manager.active_batch.data.dataframe
                if hasattr(batch_data, "toPandas"):
                    df = batch_data.toPandas()
                else:
                    df = batch_data

                return validate_domain_type(df, column, domain_type_name, mostly)

            except Exception as e:
                logger.exception(f"Failed to execute domain type validation: {e}")
                return {
                    "success": False,
                    "result": {
                        "element_count": 0,
                        "unexpected_count": 0,
                        "unexpected_percent": 0.0,
                        "partial_unexpected_list": [],
                        "observed_value": f"Validation failed: {e!s}",
                    },
                }


def validate_domain_type(
    df: Any,
    column: str,
    domain_type_name: str,
    mostly: float = 1.0,
) -> dict[str, Any]:
    """Validate column values against a domain type's validation rules.

    Standalone validation function that works with Pandas DataFrames.
    Can be used as a shim when the full GX custom expectation framework
    is not available or practical.

    Args:
        df: Pandas DataFrame containing the data.
        column: Column name to validate.
        domain_type_name: Domain type name from registry (e.g., "us_state_code").
        mostly: Fraction of values that must match (default 1.0).

    Returns:
        GX-compatible result dict with 'success' and 'result' keys.

    """
    from tablespec.inference.domain_types import DomainTypeRegistry

    registry = DomainTypeRegistry()
    validations = registry.get_validation_specs(domain_type_name)

    if not validations:
        return {
            "success": False,
            "result": {
                "element_count": 0,
                "unexpected_count": 0,
                "unexpected_percent": 0.0,
                "partial_unexpected_list": [],
                "observed_value": f"Domain type '{domain_type_name}' not found or has no validations",
            },
        }

    # Get column values, dropping nulls.
    #
    # NOTE (Spark Connect / serverless limitation): this is a PANDAS-only shim.
    # ``df[column]`` on a Spark Connect DataFrame returns a Column (not a pandas
    # Series), so ``.dropna()`` here raises ``TypeError: 'Column' object is not
    # callable``. Callers MUST pass a pandas DataFrame. The production GX path
    # (ExpectColumnValuesToMatchDomainType._validate) already materializes the
    # batch via ``toPandas()`` before calling this. Making the domain-type custom
    # expectation execute natively on Spark Connect (GX-on-serverless) is a
    # separate, much larger effort and is intentionally left as future work.
    import pandas as pd

    series = df[column].dropna()
    total_count = len(series)

    if total_count == 0:
        return {
            "success": True,
            "result": {
                "element_count": 0,
                "unexpected_count": 0,
                "unexpected_percent": 0.0,
                "partial_unexpected_list": [],
                "observed_value": "Column is entirely NULL",
            },
        }

    # Collect unexpected values across all applicable validations
    unexpected_mask = pd.Series(False, index=series.index)

    for validation in validations:
        vtype = validation.get("type", "")
        kwargs = validation.get("kwargs", {})

        if vtype == "expect_column_values_to_match_regex":
            regex_pattern = kwargs.get("regex", "")
            if regex_pattern:
                pattern = re.compile(regex_pattern)
                mask = ~series.astype(str).map(lambda v, p=pattern: bool(p.match(v)))  # type: ignore[misc]
                unexpected_mask = unexpected_mask | mask

        elif vtype == "expect_column_values_to_be_in_set":
            value_set = kwargs.get("value_set", [])
            if value_set:
                # Convert value_set items to strings for comparison if series is string
                str_values = [str(v) for v in value_set]
                mask = ~series.astype(str).isin(str_values)
                unexpected_mask = unexpected_mask | mask

        elif vtype == "expect_column_value_lengths_to_be_between":
            min_len = kwargs.get("min_value", 0)
            max_len = kwargs.get("max_value", float("inf"))
            lengths = series.astype(str).str.len()
            mask = (lengths < min_len) | (lengths > max_len)
            unexpected_mask = unexpected_mask | mask

        elif vtype == "expect_column_values_to_be_between":
            min_val = kwargs.get("min_value")
            max_val = kwargs.get("max_value")
            try:
                numeric = pd.to_numeric(series, errors="coerce")
                mask = pd.Series(False, index=series.index)
                if min_val is not None:
                    mask = mask | (numeric < min_val)
                if max_val is not None:
                    mask = mask | (numeric > max_val)
                mask = mask | pd.Series(pd.isna(numeric), index=series.index)
                unexpected_mask = unexpected_mask | mask
            except (ValueError, TypeError):
                # If conversion fails, all values are unexpected
                unexpected_mask = unexpected_mask | pd.Series(True, index=series.index)

        # Skip type-check validations (expect_column_values_to_be_of_type)
        # and existence checks (expect_column_to_exist) - not applicable to value validation

    unexpected_count = int(unexpected_mask.sum())
    unexpected_percent = (
        (unexpected_count / total_count * 100) if total_count > 0 else 0.0
    )

    # Collect sample unexpected values
    unexpected_values = series[unexpected_mask].head(10).tolist()

    success_percent = 1.0 - (unexpected_count / total_count) if total_count > 0 else 1.0
    success = success_percent >= mostly

    return {
        "success": success,
        "result": {
            "element_count": total_count,
            "unexpected_count": unexpected_count,
            "unexpected_percent": unexpected_percent,
            "partial_unexpected_list": unexpected_values,
            "observed_value": f"{success_percent * 100:.2f}% of values match domain type '{domain_type_name}'",
        },
    }
