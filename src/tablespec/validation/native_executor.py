"""Connect-safe native evaluation of GX expectations via the DataFrame API.

GX 1.x's ``add_spark`` / ``SparkDFExecutionEngine`` path uses classic
``pyspark.sql.functions`` (``F.lit`` / ``F.count``) which assert
``SparkContext._active_spark_context is not None``. On Spark Connect (Sail,
Databricks serverless) there is no JVM SparkContext, so that assertion fails,
the error is swallowed, and every data-scanning expectation silently returns
``success=False`` / ``result={}``.

This module re-implements each baseline expectation type that
``BaselineExpectationGenerator`` emits using ONLY the Spark DataFrame API,
selecting the engine-correct ``functions`` module from the DataFrame itself
(see :func:`tablespec.profiling.native_profiler._functions_for`) so the same
code works on BOTH classic Spark and Spark Connect.

Each evaluator returns a GX-shaped ``result`` dict matching what
``GXSuiteExecutor._parse_validation_result`` produces from the ``add_spark``
path::

    {
        "success": bool,
        "result": {
            "observed_value": Any,
            "unexpected_count": int,
            "unexpected_percent": float,
            "partial_unexpected_list": list,
        },
    }

so ``report.py`` and all downstream consumers are unaffected.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tablespec.profiling.native_profiler import _functions_for

if TYPE_CHECKING:
    from pyspark.sql import DataFrame

logger = logging.getLogger(__name__)


# Sample size for partial_unexpected_list (matches GX BASIC result_format).
_SAMPLE_LIMIT = 10


def _ok(observed_value: Any = None, element_count: int = 0) -> dict[str, Any]:
    """Build a passing GX-shaped result dict."""
    return {
        "success": True,
        "result": {
            "observed_value": observed_value,
            "element_count": element_count,
            "unexpected_count": 0,
            "unexpected_percent": 0.0,
            "partial_unexpected_list": [],
        },
    }


def _result(
    *,
    unexpected_count: int,
    element_count: int,
    partial_unexpected_list: list[Any],
    observed_value: Any,
    mostly: float = 1.0,
) -> dict[str, Any]:
    """Build a GX-shaped result dict honoring the ``mostly`` threshold.

    Success semantics mirror GX: the fraction of *non-unexpected* values over the
    considered (typically non-null) population must be ``>= mostly``. With the
    default ``mostly=1.0`` this means zero unexpected rows.
    """
    if element_count > 0:
        unexpected_percent = unexpected_count / element_count * 100
        success_fraction = 1.0 - (unexpected_count / element_count)
    else:
        unexpected_percent = 0.0
        success_fraction = 1.0
    return {
        "success": success_fraction >= mostly,
        "result": {
            "observed_value": observed_value,
            "element_count": element_count,
            "unexpected_count": unexpected_count,
            "unexpected_percent": unexpected_percent,
            "partial_unexpected_list": partial_unexpected_list,
        },
    }


def _apply_row_condition(df: DataFrame, kwargs: dict[str, Any]) -> DataFrame:
    """Apply a GX ``row_condition`` (Spark-SQL boolean expr) if present.

    Baseline per-context not-null expectations emit
    ``row_condition="CTX='value'"`` with ``condition_parser="spark"``. We honor it
    by filtering the DataFrame via ``F.expr`` (engine-correct via ``_functions_for``).
    """
    row_condition = kwargs.get("row_condition")
    if not row_condition:
        return df
    F = _functions_for(df)  # noqa: N806
    return df.filter(F.expr(row_condition))


def _bcol(df: DataFrame, column: str) -> Any:
    """Return the DataFrame-bound column (session-correct on classic & Connect)."""
    return df[column]


# ---------------------------------------------------------------------------
# Table-level expectations
# ---------------------------------------------------------------------------


def _table_row_count_to_be_between(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    count = df.count()
    min_value = kwargs.get("min_value")
    max_value = kwargs.get("max_value")
    success = True
    if min_value is not None and count < min_value:
        success = False
    if max_value is not None and count > max_value:
        success = False
    return {
        "success": success,
        "result": {
            "observed_value": count,
            "element_count": count,
            "unexpected_count": 0 if success else count,
            "unexpected_percent": 0.0,
            "partial_unexpected_list": [],
        },
    }


def _table_column_count_to_equal(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    actual = len(df.columns)
    expected = kwargs.get("value")
    success = actual == expected
    return {
        "success": success,
        "result": {
            "observed_value": actual,
            "element_count": actual,
            "unexpected_count": 0 if success else abs(actual - (expected or 0)),
            "unexpected_percent": 0.0,
            "partial_unexpected_list": [],
        },
    }


def _table_columns_to_match_ordered_list(
    df: DataFrame, kwargs: dict[str, Any]
) -> dict[str, Any]:
    actual = list(df.columns)
    expected = list(kwargs.get("column_list", []))
    success = actual == expected
    # Mismatched positions for the partial list.
    mismatches: list[Any] = []
    for idx in range(max(len(actual), len(expected))):
        a = actual[idx] if idx < len(actual) else None
        e = expected[idx] if idx < len(expected) else None
        if a != e:
            mismatches.append({"position": idx, "expected": e, "found": a})
    return {
        "success": success,
        "result": {
            "observed_value": actual,
            "element_count": len(actual),
            "unexpected_count": 0 if success else len(mismatches),
            "unexpected_percent": 0.0,
            "partial_unexpected_list": mismatches[:_SAMPLE_LIMIT],
        },
    }


# ---------------------------------------------------------------------------
# Column-level expectations
# ---------------------------------------------------------------------------


def _column_values_to_be_of_type(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    expected = str(kwargs.get("type_", kwargs.get("type", ""))).strip()
    actual_dt = df.schema[column].dataType
    actual_class = type(actual_dt).__name__  # e.g. "StringType"
    actual_simple = actual_dt.simpleString()  # e.g. "string"
    success = expected in (actual_class, actual_simple) or expected.lower() == actual_simple
    return {
        "success": success,
        "result": {
            "observed_value": actual_class,
            "element_count": 0,
            "unexpected_count": 0 if success else 1,
            "unexpected_percent": 0.0,
            "partial_unexpected_list": [] if success else [actual_class],
        },
    }


def _column_values_to_not_be_null(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    mostly = kwargs.get("mostly", 1.0)
    scoped = _apply_row_condition(df, kwargs)
    total = scoped.count()
    col = _bcol(scoped, column)
    null_df = scoped.filter(col.isNull())
    unexpected_count = null_df.count()
    return _result(
        unexpected_count=unexpected_count,
        element_count=total,
        partial_unexpected_list=[None] * min(unexpected_count, _SAMPLE_LIMIT),
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_values_to_be_in_set(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    value_set = list(kwargs.get("value_set", []))
    mostly = kwargs.get("mostly", 1.0)
    col = _bcol(df, column)
    # Only non-null values are considered (matches GX semantics).
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()
    unexpected_df = non_null.filter(~col.isin(value_set))
    unexpected_count = unexpected_df.count()
    samples = [row[column] for row in unexpected_df.select(column).limit(_SAMPLE_LIMIT).collect()]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_values_to_be_between(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    min_value = kwargs.get("min_value")
    max_value = kwargs.get("max_value")
    mostly = kwargs.get("mostly", 1.0)
    col = _bcol(df, column)
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()
    cond = None
    if min_value is not None:
        cond = col < min_value
    if max_value is not None:
        upper = col > max_value
        cond = upper if cond is None else (cond | upper)
    if cond is None:
        return _ok(observed_value=0, element_count=element_count)
    unexpected_df = non_null.filter(cond)
    unexpected_count = unexpected_df.count()
    samples = [row[column] for row in unexpected_df.select(column).limit(_SAMPLE_LIMIT).collect()]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_values_to_match_regex(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    regex = kwargs.get("regex", "")
    mostly = kwargs.get("mostly", 1.0)
    col = _bcol(df, column)
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()
    # Unexpected = non-null values that do NOT match the pattern.
    unexpected_df = non_null.filter(~col.rlike(regex))
    unexpected_count = unexpected_df.count()
    samples = [row[column] for row in unexpected_df.select(column).limit(_SAMPLE_LIMIT).collect()]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_value_lengths_to_be_between(
    df: DataFrame, kwargs: dict[str, Any]
) -> dict[str, Any]:
    column = kwargs["column"]
    min_value = kwargs.get("min_value")
    max_value = kwargs.get("max_value")
    mostly = kwargs.get("mostly", 1.0)
    F = _functions_for(df)  # noqa: N806
    col = _bcol(df, column)
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()
    length_col = F.length(col)
    cond = None
    if min_value is not None:
        cond = length_col < min_value
    if max_value is not None:
        upper = length_col > max_value
        cond = upper if cond is None else (cond | upper)
    if cond is None:
        return _ok(observed_value=0, element_count=element_count)
    unexpected_df = non_null.filter(cond)
    unexpected_count = unexpected_df.count()
    samples = [row[column] for row in unexpected_df.select(column).limit(_SAMPLE_LIMIT).collect()]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_values_to_be_unique(df: DataFrame, kwargs: dict[str, Any]) -> dict[str, Any]:
    column = kwargs["column"]
    mostly = kwargs.get("mostly", 1.0)
    F = _functions_for(df)  # noqa: N806
    col = _bcol(df, column)
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()
    # Group by the value; any group with count > 1 contributes its rows as unexpected.
    dup_groups = (
        non_null.groupBy(col.alias("_dup_val"))
        .agg(F.count(F.lit(1)).alias("_dup_cnt"))
        .filter(F.col("_dup_cnt") > 1)
    )
    dup_rows = dup_groups.collect()
    # GX counts every row participating in a duplicate set as unexpected.
    unexpected_count = sum(int(r["_dup_cnt"]) for r in dup_rows)
    samples = [r["_dup_val"] for r in dup_rows[:_SAMPLE_LIMIT]]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _column_values_to_match_strftime_format(
    df: DataFrame, kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Count non-null values that fail to parse under the given strftime format.

    GX's ``strftime_format`` kwarg uses C ``strftime`` ``%``-codes. We translate
    those to a Spark/Java datetime pattern and attempt a Connect-safe parse with
    ``try_to_timestamp`` (a value is "unexpected" when it is non-null but fails to
    parse). Spark's parser is strict about field widths, so this catches both
    format mismatches and impossible dates (e.g. 2023-02-30).
    """
    column = kwargs["column"]
    strftime_format = kwargs.get("strftime_format", "")
    mostly = kwargs.get("mostly", 1.0)
    col = _bcol(df, column)
    non_null = df.filter(col.isNotNull())
    element_count = non_null.count()

    spark_format = _strftime_to_spark(strftime_format)
    parsed = _connect_safe_parse(df, col.cast("string"), spark_format)
    unexpected_df = non_null.filter(parsed.isNull())
    unexpected_count = unexpected_df.count()
    samples = [row[column] for row in unexpected_df.select(column).limit(_SAMPLE_LIMIT).collect()]
    return _result(
        unexpected_count=unexpected_count,
        element_count=element_count,
        partial_unexpected_list=samples,
        observed_value=unexpected_count,
        mostly=mostly,
    )


def _connect_safe_parse(df: DataFrame, column_ref: Any, spark_format: str) -> Any:
    """Return a NULL-on-failure timestamp parse of *column_ref* for *spark_format*.

    Connect-portable: ``try_to_timestamp(col, fmt)`` works on classic Spark 4.0 but
    some Spark Connect builds (Sail/DataFusion) ignore the Java format and NULL
    everything, while the format-aware ``to_timestamp`` THROWS on impossible dates
    instead of returning NULL. So when the format overload is unsupported we fall
    back to formatless ``try_to_timestamp`` (ISO parse + bad-calendar rejection)
    gated behind a structural prefilter regex that enforces the declared field
    shape. Engine-correct ``F`` via ``_functions_for`` keeps it Connect-plan-safe.
    """
    from tablespec.casting_utils import _format_to_prefilter_regex
    from tablespec.session import get_capabilities

    F = _functions_for(df)  # noqa: N806
    if get_capabilities(df.sparkSession)["try_to_timestamp_with_format"]:
        return F.try_to_timestamp(column_ref, F.lit(spark_format))
    regex = _format_to_prefilter_regex(spark_format)
    base = F.try_to_timestamp(column_ref)
    return F.when(column_ref.rlike(regex), base).otherwise(
        F.lit(None).cast("timestamp")
    )


# strftime %-code -> Spark/Java datetime pattern token.
_STRFTIME_TO_SPARK: dict[str, str] = {
    "%Y": "yyyy",
    "%y": "yy",
    "%m": "MM",
    "%d": "dd",
    "%H": "HH",
    "%I": "hh",
    "%M": "mm",
    "%S": "ss",
    "%f": "SSSSSS",
    "%p": "a",
    "%j": "DDD",
    "%%": "%",
}


def _strftime_to_spark(strftime_format: str) -> str:
    """Translate a C strftime ``%``-code string to a Spark/Java datetime pattern.

    Literal characters between directives are emitted verbatim except letters,
    which are single-quoted so Spark treats them as literals rather than pattern
    tokens.
    """
    directives = sorted(_STRFTIME_TO_SPARK, key=len, reverse=True)
    out: list[str] = []
    idx = 0
    n = len(strftime_format)
    while idx < n:
        matched = False
        for directive in directives:
            if strftime_format.startswith(directive, idx):
                out.append(_STRFTIME_TO_SPARK[directive])
                idx += len(directive)
                matched = True
                break
        if matched:
            continue
        ch = strftime_format[idx]
        out.append(f"'{ch}'" if ch.isalpha() else ch)
        idx += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TABLE_EVALUATORS = {
    "expect_table_row_count_to_be_between": _table_row_count_to_be_between,
    "expect_table_column_count_to_equal": _table_column_count_to_equal,
    "expect_table_columns_to_match_ordered_list": _table_columns_to_match_ordered_list,
}

_COLUMN_EVALUATORS = {
    "expect_column_values_to_be_of_type": _column_values_to_be_of_type,
    "expect_column_values_to_not_be_null": _column_values_to_not_be_null,
    "expect_column_values_to_be_in_set": _column_values_to_be_in_set,
    "expect_column_values_to_be_between": _column_values_to_be_between,
    "expect_column_values_to_match_regex": _column_values_to_match_regex,
    "expect_column_value_lengths_to_be_between": _column_value_lengths_to_be_between,
    "expect_column_values_to_be_unique": _column_values_to_be_unique,
    "expect_column_values_to_match_strftime_format": _column_values_to_match_strftime_format,
}


def evaluate_expectation(df: DataFrame, exp_type: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a single expectation natively, or return ``None`` if unsupported.

    Returns a GX-shaped ``{"success": ..., "result": {...}}`` dict on success, or
    ``None`` when *exp_type* is not handled by the native path (the caller routes
    those — e.g. the custom cast/domain expectations — through their own handlers).
    """
    evaluator = _TABLE_EVALUATORS.get(exp_type) or _COLUMN_EVALUATORS.get(exp_type)
    if evaluator is None:
        return None
    return evaluator(df, kwargs)


def is_natively_supported(exp_type: str) -> bool:
    """True iff *exp_type* has a native DataFrame-API evaluator."""
    return exp_type in _TABLE_EVALUATORS or exp_type in _COLUMN_EVALUATORS
