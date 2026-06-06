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
    import pyspark.sql.functions  # noqa: F401  (presence probe only)

    _spark_available = True
except ImportError:
    _spark_available = False

SPARK_AVAILABLE = _spark_available


logger = logging.getLogger(__name__)


def _build_cast_expr(
    dataframe: Any,
    column_ref: Any,
    target_type: str,
    format_str: str | None,
    fallback_formats: list[str] | None = None,
) -> Any:
    """Build a NULL-on-failure cast expression for *column_ref*.

    Two regimes, selected by the session's ``try_to_timestamp_with_format``
    capability:

    * **Capable** (classic Spark 4.0; capable Connect builds): delegate to the rich
      :mod:`tablespec.casting_utils` path (``try_parse_flexible_timestamp`` /
      ``cast_column_with_format``) so behavior — multi-format fallback, Excel-serial
      and epoch detection, ``$``-stripping — is BYTE-IDENTICAL to what the classic
      ``add_spark`` path produced before this change. The only adjustment is passing
      the DataFrame-bound ``column_ref`` instead of ``F.col(column)``.
    * **Incapable** (Sail / Databricks-serverless Connect builds that ignore the
      Java format and whose strict casts THROW instead of NULLing): build a
      Connect-portable expression with the engine-correct functions module
      (``_functions_for``) — ``_connect_safe_parse`` for dates (formatless
      ``try_to_timestamp`` gated by a structural prefilter regex) and
      ``Column.try_cast`` for numerics/booleans (NULL-on-failure on both engines).
    """
    from tablespec.profiling.native_profiler import _functions_for
    from tablespec.session import get_capabilities

    capable = get_capabilities(dataframe.sparkSession)["try_to_timestamp_with_format"]

    if capable:
        # Classic-equivalent rich path (bound column instead of F.col).
        from tablespec.casting_utils import (
            build_flexible_formats,
            cast_column_with_format,
            try_parse_flexible_timestamp,
        )

        t = target_type.upper()
        if t in ("DATE", "TIMESTAMP"):
            formats = build_flexible_formats(target_type, format_str, fallback_formats)
            cast_expr = try_parse_flexible_timestamp(
                column_ref,
                primary_format=formats[0] if formats else "",
                fallback_formats=formats[1:] if len(formats) > 1 else None,
            )
            return cast_expr.cast("date") if t == "DATE" else cast_expr
        return cast_column_with_format(column_ref, target_type, format_str)

    # --- Connect-portable strict path (Sail / serverless) ---
    from tablespec.casting_utils import convert_umf_format_to_spark
    from tablespec.validation.native_executor import _connect_safe_parse

    F = _functions_for(dataframe)  # noqa: N806
    t = target_type.upper()

    if t in ("DATE", "TIMESTAMP"):
        if format_str:
            spark_format = convert_umf_format_to_spark(format_str)
            parsed = _connect_safe_parse(dataframe, column_ref, spark_format)
        else:
            parsed = F.try_to_timestamp(column_ref)
        return parsed.cast("date") if t == "DATE" else parsed

    # Numerics: strip a leading "$", trim, treat empty/whitespace as NULL, then
    # cast NULL-on-failure. ``Column.try_cast`` is the portable primitive here:
    # plain ``cast`` is ANSI-strict on Spark Connect (Sail/DataFusion) and THROWS
    # on a non-numeric string instead of NULLing it, whereas ``try_cast`` returns
    # NULL on both classic Spark and Connect.
    if t in ("INTEGER", "DECIMAL", "DOUBLE", "FLOAT"):
        cleaned = F.regexp_replace(F.trim(column_ref), r"^\$", "")
        cleaned = F.when(F.trim(cleaned) == "", F.lit(None).cast("string")).otherwise(
            cleaned
        )
        if t == "INTEGER":
            return cleaned.try_cast("int")
        if t == "DECIMAL":
            return cleaned.try_cast("decimal(10,2)")
        return cleaned.try_cast("double")  # DOUBLE / FLOAT

    if t == "BOOLEAN":
        return column_ref.try_cast("boolean")
    if t == "STRING":
        return column_ref

    msg = f"Unsupported target_type for cast validation: {target_type}"
    raise ValueError(msg)


def validate_cast_to_type(
    dataframe: Any,
    column: str,
    target_type: str,
    *,
    format_str: str | None = None,
    fallback_formats: list[str] | None = None,
    mostly: float = 1.0,
) -> dict[str, Any]:
    """Connect-safe validation that a column's values cast to ``target_type``.

    Standalone helper shared by the GX custom expectation
    (``ExpectColumnValuesToCastToType._validate``) and the native suite executor.
    Uses DataFrame-bound columns (``dataframe[column]``) rather than ``F.col`` so
    it works on BOTH classic Spark and Spark Connect (Sail / Databricks
    serverless): ``pyspark.sql.functions.col`` builds a CLASSIC Column when a
    classic JVM session is active in the process, which fails inside a Connect
    plan.

    Returns a GX-shaped result dict (``success`` + ``result`` with
    ``unexpected_count``, ``unexpected_percent``, ``partial_unexpected_list``,
    ``observed_value``).
    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for custom casting expectations"
        raise ImportError(msg)

    from pyspark.sql.types import DateType, TimestampType

    column_ref = dataframe[column]

    # Already the target type (e.g. Gold tables with pre-typed columns) -> pass.
    col_type = dataframe.schema[column].dataType
    is_already_target_type = (
        target_type.upper() == "DATE" and isinstance(col_type, DateType)
    ) or (target_type.upper() == "TIMESTAMP" and isinstance(col_type, TimestampType))
    if is_already_target_type:
        total_count = dataframe.count()
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

    original_non_null_count = dataframe.filter(column_ref.isNotNull()).count()
    if original_non_null_count == 0:
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

    cast_expr = _build_cast_expr(
        dataframe, column_ref, target_type, format_str, fallback_formats
    )

    casted_df = dataframe.withColumn(f"_casted_{column}", cast_expr)
    casting_failures_df = casted_df.filter(
        casted_df[column].isNotNull() & casted_df[f"_casted_{column}"].isNull()
    )
    unexpected_count = casting_failures_df.count()
    unexpected_percent = (
        (unexpected_count / original_non_null_count * 100)
        if original_non_null_count > 0
        else 0.0
    )

    unexpected_values = []
    if unexpected_count > 0:
        sample_rows = casting_failures_df.select(column).limit(20).collect()
        unexpected_values = [row[column] for row in sample_rows]

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
            "partial_unexpected_list": unexpected_values[:10],
            "observed_value": f"{success_percent * 100:.2f}% cast successfully to {target_type}{format_msg}",
        },
    }


def _pair_element_repr(value: Any) -> Any:
    """Render a column-pair element the way GX's classic ``add_spark`` engine does.

    GX stringifies non-null pair members in ``partial_unexpected_list`` (e.g. a
    ``datetime.date`` becomes its ISO ``str``) while preserving ``None`` for nulls.
    Mirroring that here keeps the native Connect path byte-equal with classic.
    """
    if value is None:
        return None
    return str(value)


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
    # Match GX's classic ``add_spark`` ``expect_column_pair_values_a_to_be_greater_than_b``
    # rendering byte-for-byte: a list of ``[column_A, column_B]`` pairs, each element
    # stringified (so ``datetime.date(2023, 1, 1)`` -> ``"2023-01-01"``). Emitting a
    # human-readable ``"a < b"`` comparison string here would diverge from the classic
    # engine's partial_unexpected_list and break cross-engine value parity.
    partial_unexpected_list = [
        [_pair_element_repr(row[value_column]), _pair_element_repr(row[reference_column])]
        for row in sample_rows
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


def validate_date_in_current_year(
    dataframe: Any,
    column: str,
    *,
    mostly: float = 1.0,
) -> dict[str, Any]:
    """Connect-safe validation that date values fall within the current year.

    Shared by ``ExpectColumnDateToBeInCurrentYear._validate`` and the native suite
    executor. Computes the year bounds with Spark SQL and compares using
    DataFrame-bound columns (``dataframe[column]``) so it works on classic Spark
    and Spark Connect alike.
    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for current year date validation"
        raise ImportError(msg)

    spark = dataframe.sparkSession
    # Cast the bounds to DATE. ``DATE_TRUNC`` returns a TIMESTAMP, which Spark
    # Connect (Sail / Databricks serverless) compares against a DATE column with
    # different semantics than classic Spark -- producing parity-breaking
    # false positives (e.g. a Jan-1 in-year date read as out-of-range). DATE
    # bounds make the comparison date-to-date and identical on both engines.
    bounds_row = spark.sql("""
        SELECT
            CAST(DATE_TRUNC('YEAR', CURRENT_DATE()) AS DATE) as year_start,
            CAST(DATE_TRUNC('YEAR', CURRENT_DATE()) + INTERVAL '1 YEAR' - INTERVAL '1 DAY' AS DATE) as year_end
    """).first()
    year_start = bounds_row["year_start"]
    year_end = bounds_row["year_end"]

    col = dataframe[column]
    non_null_count = dataframe.filter(col.isNotNull()).count()
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

    out_of_range_df = dataframe.filter(
        col.isNotNull() & ((col < year_start) | (col > year_end))
    )
    unexpected_count = out_of_range_df.count()
    unexpected_percent = (
        (unexpected_count / non_null_count * 100) if non_null_count > 0 else 0.0
    )

    unexpected_values = []
    if unexpected_count > 0:
        sample_rows = out_of_range_df.select(column).limit(20).collect()
        unexpected_values = [str(row[column]) for row in sample_rows]

    success_percent = (
        1.0 - (unexpected_count / non_null_count) if non_null_count > 0 else 1.0
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
            # In GX 1.x with Spark, the batch contains the DataFrame.
            # Delegate to the shared, Connect-safe ``validate_cast_to_type`` helper
            # (bound columns ``df[col]`` instead of ``F.col``) so the casting logic
            # is identical on classic Spark and the native Connect suite path.
            try:
                df = execution_engine.batch_manager.active_batch.data.dataframe
                return validate_cast_to_type(
                    df,
                    column,
                    target_type,
                    format_str=format_str,
                    fallback_formats=fallback_formats,
                    mostly=mostly,
                )

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
                # Access DataFrame through execution engine's active batch and
                # delegate to the Connect-safe shared helper (bound columns).
                df = execution_engine.batch_manager.active_batch.data.dataframe
                return validate_date_in_current_year(df, column, mostly=mostly)

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

    PANDAS shim -- requires a pandas frame, NOT a Spark/Connect DataFrame.
    Both callers (the GX ``ExpectColumnValuesToMatchDomainType._validate`` classic
    path and the native suite executor at ``gx_executor._evaluate_custom_native``)
    first materialize the single target column with ``df.select(col).toPandas()``
    before calling this. That collect is O(rows) in driver memory: it is fine for
    the bounded batch/test sizes here, but is NOT a scalable production path for
    very large columns. A native Spark-API rewrite (so domain-type runs without a
    full-column collect on Connect) is a separate, larger effort.

    Args:
        df: Pandas DataFrame containing the data (executor-collected, see above).
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
