"""Shared utilities for format-aware Spark type casting.

This module provides a single source of truth for casting operations used by both:
- TypeConverter (Phase 8 ingestion)
- ExpectColumnValuesToCastToType (validation)

This ensures validation tests exactly what ingestion will do.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import Column

from tablespec.date_formats import SUPPORTED_DATE_FORMATS, FormatType

try:
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        BooleanType,
        DecimalType,
        DoubleType,
        IntegerType,
    )

    _spark_available = True
except ImportError:
    _spark_available = False

SPARK_AVAILABLE = _spark_available


logger = logging.getLogger(__name__)


# Common date formats derived from the canonical SUPPORTED_DATE_FORMATS registry.
# These are tried in order after the primary format fails.
# NOTE: European formats (DD/MM/YYYY, DD-MM-YYYY) are intentionally excluded
# to avoid ambiguity with US formats. For US healthcare data, MM/DD/YYYY
# is the standard convention.
COMMON_DATE_FORMATS: tuple[str, ...] = tuple(
    f.umf_format for f in SUPPORTED_DATE_FORMATS if f.format_type.value == "date"
)

# Common timestamp formats derived from the canonical SUPPORTED_DATE_FORMATS registry.
# Order matters: more specific formats first.
COMMON_TIMESTAMP_FORMATS: tuple[str, ...] = tuple(
    f.umf_format for f in SUPPORTED_DATE_FORMATS if f.format_type.value == "datetime"
)


def _format_to_prefilter_regex(spark_format: str) -> str:
    """Build a structural regex for a Spark timestamp/date format string.

    The regex is intentionally permissive: it filters out obvious garbage before
    delegating to Spark parsing, but it does not attempt semantic date validation.
    """
    token_patterns = {
        "yyyy": r"\d{4}",
        "yy": r"\d{2}",
        "MM": r"\d{1,2}",
        "dd": r"\d{1,2}",
        "HH": r"\d{1,2}",
        "hh": r"\d{1,2}",
        "mm": r"\d{1,2}",
        "ss": r"\d{1,2}",
        "SSSSSS": r"\d{6}",
        "SSSSS": r"\d{5}",
        "SSSS": r"\d{4}",
        "SSS": r"\d{3}",
        "SS": r"\d{2}",
        "S": r"\d",
        "a": r"(?:AM|PM)",
    }
    tokens = sorted(token_patterns, key=len, reverse=True)

    parts: list[str] = ["^"]
    idx = 0
    while idx < len(spark_format):
        if spark_format[idx] == "'":
            end_idx = spark_format.find("'", idx + 1)
            literal = (
                spark_format[idx + 1 :]
                if end_idx == -1
                else spark_format[idx + 1 : end_idx]
            )
            parts.append(re.escape(literal))
            idx = len(spark_format) if end_idx == -1 else end_idx + 1
            continue

        matched = False
        for token in tokens:
            if spark_format.startswith(token, idx):
                parts.append(token_patterns[token])
                idx += len(token)
                matched = True
                break

        if matched:
            continue

        parts.append(re.escape(spark_format[idx]))
        idx += 1

    parts.append("$")
    return "".join(parts)


def _is_spark_connect_column(column: Column) -> bool:
    """Best-effort fallback for environments without an explicit session handle."""
    return "connect" in type(column).__module__


def safe_to_timestamp(
    column: Column,
    spark_format: str | None = None,
    spark: object | None = None,
) -> Column:
    """Compatibility wrapper for timestamp parsing across classic Spark and Connect."""
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for timestamp casting"
        raise ImportError(msg)

    if spark_format is None:
        return F.try_to_timestamp(column)  # type: ignore[attr-defined]

    can_use_try_with_format = not _is_spark_connect_column(column)
    if spark is not None:
        from tablespec.session import get_capabilities

        can_use_try_with_format = get_capabilities(spark)[
            "try_to_timestamp_with_format"
        ]

    if can_use_try_with_format:
        return F.try_to_timestamp(column, F.lit(spark_format))  # type: ignore[attr-defined]

    regex = _format_to_prefilter_regex(spark_format)
    parsed = F.to_timestamp(column, spark_format)  # type: ignore[attr-defined]
    return F.when(column.rlike(regex), parsed).otherwise(  # type: ignore[attr-defined]
        F.lit(None).cast("timestamp")  # type: ignore[attr-defined]
    )


def safe_to_date(
    column: Column,
    spark_format: str | None = None,
    spark: object | None = None,
) -> Column:
    """Compatibility wrapper that delegates to ``safe_to_timestamp`` then casts to date."""
    return safe_to_timestamp(column, spark_format=spark_format, spark=spark).cast(
        "date"
    )


def build_flexible_formats(
    target_type: str,
    primary_format: str | None,
    fallback_formats: list[str] | None = None,
) -> list[str]:
    """Build a prioritized list of flexible formats for date/timestamp parsing.

    Formats are ordered as: primary -> fallback -> supported formats -> common fallback formats.
    Time-only formats are excluded for DATE/TIMESTAMP parsing.

    The common fallback formats include additional patterns not in SUPPORTED_DATE_FORMATS,
    such as two-digit year variants (MM/DD/YY, M/D/YY, YY-MM-DD) for DATE columns and
    additional timestamp patterns for TIMESTAMP columns.
    """
    target_type_upper = target_type.upper()
    if target_type_upper == "DATE":
        allowed = {FormatType.DATE}
        common_formats = COMMON_DATE_FORMATS
    elif target_type_upper == "TIMESTAMP":
        allowed = {FormatType.DATE, FormatType.DATETIME}
        common_formats = COMMON_TIMESTAMP_FORMATS
    else:
        return []

    # Get formats from SUPPORTED_DATE_FORMATS (explicit UMF formats)
    supported = [
        fmt.umf_format for fmt in SUPPORTED_DATE_FORMATS if fmt.format_type in allowed
    ]

    seen: set[str] = set()
    ordered: list[str] = []

    def add_format(fmt: str | None) -> None:
        if fmt and fmt not in seen:
            ordered.append(fmt)
            seen.add(fmt)

    # Priority order: primary -> fallback -> supported -> common fallback
    add_format(primary_format)
    for fmt in fallback_formats or []:
        add_format(fmt)
    for fmt in supported:
        add_format(fmt)
    # Add common fallback formats (includes two-digit year patterns, etc.)
    for fmt in common_formats:
        add_format(fmt)

    return ordered


def convert_umf_format_to_spark(umf_format: str) -> str:
    """Convert UMF date/timestamp format to Java SimpleDateFormat pattern.

    This function converts UMF format strings (like YYYY-MM-DD) to Java SimpleDateFormat
    patterns used by Spark's to_date() and to_timestamp() functions.

    Args:
    ----
        umf_format: UMF format string (e.g., "MM/DD/YYYY", "YYYY-MM-DD HH:MM:SS")

    Returns:
    -------
        Java SimpleDateFormat pattern (e.g., "MM/dd/yyyy", "yyyy-MM-dd HH:mm:ss")

    Examples:
    --------
        >>> convert_umf_format_to_spark("MM/DD/YYYY")
        "MM/dd/yyyy"
        >>> convert_umf_format_to_spark("YYYY-MM-DD HH:MM:SS")
        "yyyy-MM-dd HH:mm:ss"

    Note:
    ----
        UMF uses uppercase tokens (YYYY, MM, DD, HH, MM, SS) but Java SimpleDateFormat
        is case-sensitive:
        - yyyy = 4-digit year (not YYYY)
        - MM = month (stays uppercase)
        - dd = day (not DD)
        - HH = 24-hour hour zero-padded (stays uppercase)
        - H = 24-hour hour non-padded (stays uppercase)
        - hh = 12-hour hour zero-padded (stays lowercase)
        - h = 12-hour hour non-padded (stays lowercase)
        - mm = minute (not MM - to avoid conflict with month)
        - ss = second (not SS)
        - SSSSSS = fractional seconds/microseconds (6 digits, stays uppercase)
        - SSS = fractional seconds/milliseconds (3 digits, stays uppercase)

    """
    import re

    # Java SimpleDateFormat is case-sensitive
    # Special handling for fractional seconds:
    # - Fractional seconds (.SSSSSS, .SSS) use UPPERCASE S in Java SimpleDateFormat
    # - Whole seconds (SS without dot prefix) use lowercase ss
    # Strategy: Temporarily replace fractional seconds with placeholder,
    # then convert whole seconds, then restore fractional seconds

    result = umf_format

    # Step 1: Protect fractional seconds by replacing with placeholder
    # Match dot followed by 1-9 S characters (fractional seconds)
    # Use a placeholder that won't be affected by subsequent replacements
    # Using only underscores and digits to avoid conflicts with ALL pattern replacements
    # (A->a, D->d, H->h, M->M, Y->y, S->s, etc.)
    fractional_seconds_pattern = r"\.S+"
    fractional_matches = re.findall(fractional_seconds_pattern, result)
    for i, match in enumerate(fractional_matches):
        result = result.replace(match, f"__{i}__", 1)

    # Step 2: Apply standard replacements
    # Order matters! Replace longer patterns first to avoid partial matches
    replacements = [
        ("YYYY", "yyyy"),  # 4-digit year
        ("YY", "yy"),  # 2-digit year
        ("DD", "dd"),  # Day of month (zero-padded)
        ("HH", "HH"),  # Hour 24-hour zero-padded (no change, already correct)
        ("hh", "hh"),  # Hour 12-hour zero-padded (no change, already correct)
        ("SS", "ss"),  # Seconds (2-digit) - safe now, fractional seconds are protected
        ("A", "a"),  # AM/PM marker (Java uses lowercase 'a' for both AM and PM)
        # Single-character patterns for non-zero-padded values
        # Must come after two-character patterns to avoid partial replacement
        ("D", "d"),  # Day of month (no leading zero)
        ("M", "M"),  # Month (no change - Java uses M for both)
        ("H", "H"),  # Hour 24-hour no leading zero (no change - Java uses H)
        ("h", "h"),  # Hour 12-hour no leading zero (no change - Java uses h)
        # MM is tricky - it means both month and minutes in different contexts
        # We need to handle this carefully based on position
    ]

    # Apply replacements
    for umf_token, spark_token in replacements:
        result = result.replace(umf_token, spark_token)

    # Handle MM (month vs minutes) based on context
    # MM in date portion (before T or space) stays as MM (month)
    # MM after : in time portion becomes mm (minutes)
    #
    # Strategy: Split on T or space to separate date from time parts
    # Then only convert MM->mm in the time portion (which contains :)
    # Split into date and time parts (separated by T or space)
    # Keep the separator for reassembly
    match = re.match(r"^([^T\s]+)([T\s]?)(.*)$", result)
    if match:
        date_part, separator, time_part = match.groups()
        # Only convert MM to mm in the time part (which has colons)
        if time_part and ":" in time_part:
            time_part = time_part.replace("MM", "mm")
        result = date_part + separator + time_part

    # Escape literal 'T' separator in ISO 8601 formats (e.g., YYYY-MM-DDTHH:MM:SS)
    # Java SimpleDateFormat requires literal characters to be quoted with single quotes
    # Replace 'T' between date and time components with quoted literal
    if "dTH" in result or "dTh" in result:
        result = result.replace("dTH", "d'T'H").replace("dTh", "d'T'h")

    # Step 3: Restore fractional seconds (Java uses uppercase S for fractional seconds)
    # IMPORTANT: This must happen LAST to avoid placeholder being affected by other replacements
    for i, match in enumerate(fractional_matches):
        # Keep fractional seconds uppercase (.SSSSSS stays .SSSSSS in Java)
        result = result.replace(f"__{i}__", match)

    return result


def convert_umf_format_to_duckdb(umf_format: str) -> str:
    """Convert a UMF date/timestamp format to a DuckDB strptime ``%``-code string.

    DuckDB's ``try_strptime`` / ``strftime`` use C ``strftime`` format codes
    (``%Y``, ``%m``, ``%d`` ...), which is exactly the ``strftime_format`` already
    recorded for every entry in :data:`SUPPORTED_DATE_FORMATS`. This function is the
    DuckDB sibling of :func:`convert_umf_format_to_spark`: both are driven by the
    SAME registry, so the two engines parse the identical set of UMF formats.

    Args:
    ----
        umf_format: UMF format string (e.g. ``"MM/DD/YYYY"``, ``"YYYYMMDD"``).

    Returns:
    -------
        The DuckDB/strftime ``%``-code pattern (e.g. ``"%m/%d/%Y"``, ``"%Y%m%d"``).

    Raises:
    ------
        ValueError: If *umf_format* is not in the supported registry.

    Examples:
    --------
        >>> convert_umf_format_to_duckdb("MM/DD/YYYY")
        '%m/%d/%Y'
        >>> convert_umf_format_to_duckdb("YYYY-MM-DD HH:MM:SS")
        '%Y-%m-%d %H:%M:%S'

    """
    fmt = _DUCKDB_FORMAT_BY_UMF.get(umf_format)
    if fmt is None:
        supported = ", ".join(sorted(_DUCKDB_FORMAT_BY_UMF))
        msg = (
            f"Unsupported UMF date/timestamp format for DuckDB: '{umf_format}'. "
            f"Supported formats: {supported}"
        )
        raise ValueError(msg)
    return fmt


# Registry-driven lookup for the DuckDB converter. Built from the SAME
# SUPPORTED_DATE_FORMATS source as the Spark path so the two dialects can never
# drift in which UMF formats they accept (enforced by a parity unit test).
_DUCKDB_FORMAT_BY_UMF: dict[str, str] = {
    f.umf_format: f.strftime_format for f in SUPPORTED_DATE_FORMATS
}


def _is_registry_format(umf_format: str) -> bool:
    """True iff *umf_format* is in the shared cross-engine date/time registry."""
    return umf_format in _DUCKDB_FORMAT_BY_UMF


# strftime directive -> structural regex fragment for the DuckDB padding pre-filter.
# DuckDB's try_strptime is uniformly lenient: %m/%d/%H/%M/%S accept BOTH "6" and
# "06", and %Y accepts a short year. Spark's to_timestamp is strict about
# zero-padded fields: with format "MM/dd/yyyy", Spark NULLs "6/3/2026" but DuckDB
# would silently parse it. To keep the byte-identical canonical-form contract for
# malformed input, we gate the DuckDB parse behind a regex that demands the SAME
# field widths Spark requires, so a value Spark would NULL also NULLs in DuckDB.
#
# Zero-padded directives require EXACTLY two digits (Spark MM/dd/HH/mm/ss/hh);
# their non-padding %-X variants accept one or two (Spark M/d/H/h, which also
# tolerate a leading zero). %Y is four digits, %y is two, %f defaults to 1-6
# fractional digits (the cap is narrowed per-format via fractional_cap; see
# _duckdb_padding_prefilter_regex), and %p is the case-insensitive AM/PM marker.
_DUCKDB_DIRECTIVE_REGEX: dict[str, str] = {
    "%Y": r"\d{4}",
    "%y": r"\d{2}",
    "%m": r"\d{2}",
    "%d": r"\d{2}",
    "%H": r"\d{2}",
    "%I": r"\d{2}",
    "%M": r"\d{2}",
    "%S": r"\d{2}",
    "%-m": r"\d{1,2}",
    "%-d": r"\d{1,2}",
    "%-H": r"\d{1,2}",
    "%-I": r"\d{1,2}",
    "%f": r"\d{1,6}",
    # AM/PM marker, case-INSENSITIVE: both Spark's DateTimeFormatter
    # (parseCaseInsensitive) and DuckDB's %p accept mixed case ("Pm", "pM"), so the
    # pre-filter must too or it would over-strictly NULL values both engines parse.
    "%p": r"[AaPp][Mm]",
}


def _fractional_digit_cap(umf_format: str | None) -> int:
    """Max fractional-second digits Spark accepts for *umf_format* (the ``S`` run).

    Spark's ``to_timestamp`` accepts at most as many fractional digits as the
    pattern declares: ``.SSS`` parses 1-3 digits and NULLs 4+, ``.SSSSSS`` parses
    1-6. DuckDB's portable ``%f`` strftime would otherwise greedily consume up to 6
    regardless, so the pre-filter uses this cap (derived from the UMF ``S``-run,
    since both widths share the ``%f`` directive) to NULL exactly what Spark NULLs.
    Defaults to 6 when no fractional component is present.
    """
    if not umf_format:
        return 6
    match = re.search(r"\.(S+)", umf_format)
    return len(match.group(1)) if match else 6


def _duckdb_padding_prefilter_regex(
    strftime_format: str, *, fractional_cap: int = 6
) -> str:
    """Build a structural regex mirroring Spark's zero-padding strictness.

    Walks a DuckDB/strftime ``%``-code pattern (the value stored in
    :data:`SUPPORTED_DATE_FORMATS`) and replaces each directive with a digit-width
    fragment matching what Spark's ``to_timestamp`` accepts, escaping every literal
    in between. The result is anchored implicitly by DuckDB ``regexp_full_match``.

    ``%f`` is special-cased: both ``.SSS`` and ``.SSSSSS`` map to the portable
    ``%f`` strftime, so the per-format fractional width is supplied separately via
    *fractional_cap* (see :func:`_fractional_digit_cap`) to reproduce Spark's
    narrower millisecond acceptance.

    This is intentionally structural, not semantic: it enforces field widths
    (so "6/3/2026" is rejected against ``%m/%d/%Y``) but leaves value-range checks
    (month 13, day 30) to ``try_strptime`` itself, which NULLs them in both engines.
    """
    # Longer directives first so "%-m" is matched before "%m"/"%-"/"%".
    directives = sorted(_DUCKDB_DIRECTIVE_REGEX, key=len, reverse=True)
    parts: list[str] = []
    idx = 0
    n = len(strftime_format)
    while idx < n:
        matched = False
        for directive in directives:
            if strftime_format.startswith(directive, idx):
                if directive == "%f":
                    parts.append(rf"\d{{1,{fractional_cap}}}")
                else:
                    parts.append(_DUCKDB_DIRECTIVE_REGEX[directive])
                idx += len(directive)
                matched = True
                break
        if matched:
            continue
        parts.append(re.escape(strftime_format[idx]))
        idx += 1
    return "".join(parts)


def cast_column_sql(
    column: str,
    target_type: str,
    format: str | None = None,
    *,
    precision: int | None = None,
    scale: int | None = None,
    dialect: str = "spark",
) -> str:
    """Return a SQL expression that casts *column* to *target_type*.

    SQL counterpart of :func:`cast_column_with_format`: it emits the same casting
    logic as a plain SQL string so it can be embedded in a committed,
    independently-runnable ingest artifact -- no PySpark at runtime. The Spark and
    DuckDB dialects share a single registry for date/timestamp formats
    (:func:`convert_umf_format_to_spark` / :func:`convert_umf_format_to_duckdb`),
    and emit identical SQL wherever the two engines agree.

    The cast contract is NULL-on-failure for malformed input, realised as:

    * Spark: ANSI casting disabled, so plain ``cast(...)`` yields NULL; dates use
      ``try_to_timestamp``.
    * DuckDB: there is no session ANSI toggle, so ``try_cast(...)`` is emitted for
      numerics/booleans and ``try_strptime(...)`` for dates -- producing the same
      NULL-on-failure behaviour the Spark baseline relies on.

    Args:
    ----
        column: Raw column reference (assumed to be a valid SQL identifier).
        target_type: UMF/Spark target type (DATE, TIMESTAMP, INTEGER, DECIMAL, ...).
        format: Optional UMF date/timestamp format (e.g. "YYYYMMDD").
        precision: DECIMAL precision (defaults to 10, matching the runtime caster).
        scale: DECIMAL scale (defaults to 2, matching the runtime caster).
        dialect: ``"spark"`` (default), ``"databricks"``, or ``"duckdb"``.
            ``"databricks"`` is an explicit, separately-selectable dialect that
            renders byte-for-byte identical SQL to ``"spark"`` -- Databricks SQL is
            Spark SQL for our casts (``try_to_timestamp`` + Java date tokens), so a
            Databricks dbt target reuses the Spark rendering. It exists as a named
            dialect purely so a Databricks compile/run target can be selected
            explicitly rather than masquerading as plain Spark.

    Returns:
    -------
        A SQL expression string,
        e.g. ``cast(try_to_timestamp(d, 'yyyyMMdd') as date)`` (spark) or
        ``cast(try_strptime(d, '%Y%m%d') as date)`` (duckdb).

    Examples:
    --------
        >>> cast_column_sql("birth_date", "DATE", "MM/DD/YYYY")
        "cast(try_to_timestamp(birth_date, 'MM/dd/yyyy') as date)"
        >>> cast_column_sql("age", "INTEGER")
        "cast(nullif(trim(regexp_replace(age, '^\\\\$', '')), '') as INT)"
        >>> cast_column_sql("age", "INTEGER", dialect="duckdb")
        "try_cast(nullif(trim(regexp_replace(age, '^\\$', '')), '') as INT)"

    """
    if dialect not in ("spark", "databricks", "duckdb"):
        msg = (
            f"Unsupported dialect: {dialect!r} "
            "(expected 'spark', 'databricks', or 'duckdb')"
        )
        raise ValueError(msg)
    # Databricks SQL == Spark SQL for our casts: try_to_timestamp + Java date
    # tokens. We keep 'databricks' as a distinct, explicitly-selectable named
    # dialect but render it through the identical Spark code path below, so the two
    # never drift. Everything past this point only distinguishes duckdb vs not.
    is_duck = dialect == "duckdb"
    t = target_type.upper()

    # String types: raw landing data is already a string -- passthrough.
    # Identical across both dialects.
    if t in ("STRING", "VARCHAR", "TEXT", "CHAR"):
        return column

    # Numerics: strip a leading "$", trim, and treat empty/whitespace strings as
    # NULL (cast fails on "") before casting -- mirrors cast_column_with_format.
    # The cleaning + nullif logic is identical; only the regex backslash escaping
    # and the cast keyword differ between dialects.
    if t in ("INTEGER", "DECIMAL", "DOUBLE", "FLOAT"):
        # Spark SQL needs a doubled backslash ('^\\$'); DuckDB regexp_replace
        # treats '\\' as a literal backslash, so it needs a single one ('^\$').
        dollar_re = "'^\\$'" if is_duck else "'^\\\\$'"
        cleaned = f"nullif(trim(regexp_replace({column}, {dollar_re}, '')), '')"
        if t == "INTEGER":
            sql_type = "INT"
        elif t == "DECIMAL":
            sql_type = f"DECIMAL({precision or 10},{scale if scale is not None else 2})"
        else:  # DOUBLE, FLOAT -> double (runtime maps FLOAT to DoubleType)
            sql_type = "DOUBLE"
        cast_kw = "try_cast" if is_duck else "cast"
        return f"{cast_kw}({cleaned} as {sql_type})"

    # Date/time: graceful NULL-on-failure parsing.
    #   spark  -> try_to_timestamp(col[, javaFmt])  (Spark 4.0+)
    #   duckdb -> try_strptime(col, strftimeFmt)     (NULL when unparseable)
    if t in ("DATE", "DATETIME", "TIMESTAMP"):
        # Single-registry guard for the ingest seam. convert_umf_format_to_spark is
        # a permissive string transformer (it happily rewrites e.g. 2-digit-year
        # "MM/DD/YY" -> "MM/dd/yy"), but DuckDB and Spark do NOT agree on every such
        # format: Spark's "yy" always resolves to 20xx while DuckDB's %y pivots at
        # 1969, so the SAME 2-digit-year input would yield DIFFERENT centuries and
        # silently break the byte-identical canonical-form contract. To keep the two
        # ingest emitters symmetric, BOTH dialects accept only formats proven in the
        # shared SUPPORTED_DATE_FORMATS registry and otherwise raise the same error
        # (rather than one crashing while the other emits a divergent cast).
        if format and not _is_registry_format(format):
            supported = ", ".join(sorted(_DUCKDB_FORMAT_BY_UMF))
            msg = (
                f"Unsupported UMF date/timestamp format for cross-engine ingest: "
                f"'{format}'. Only registry formats parse identically in Spark and "
                f"DuckDB. Supported formats: {supported}"
            )
            raise ValueError(msg)
        if is_duck:
            if format:
                duck_format = convert_umf_format_to_duckdb(format)
                # Gate try_strptime behind a Spark-equivalent padding regex so a
                # malformed-padding value Spark would NULL (e.g. "6/3/2026" under
                # MM/DD/YYYY) also NULLs in DuckDB, preserving byte-identical
                # canonical output. The fractional cap is taken from the UMF S-run
                # so ".SSS" rejects 4+ fractional digits exactly as Spark does.
                # See _duckdb_padding_prefilter_regex.
                prefilter = _duckdb_padding_prefilter_regex(
                    duck_format, fractional_cap=_fractional_digit_cap(format)
                )
                strptime = f"try_strptime({column}, '{duck_format}')"
                expr = (
                    f"case when regexp_full_match({column}, '{prefilter}') "
                    f"then {strptime} end"
                )
            else:
                # No declared format: cast through DuckDB's permissive TIMESTAMP
                # parser, which returns NULL on failure under try_cast.
                expr = f"try_cast({column} as timestamp)"
            return f"cast({expr} as date)" if t == "DATE" else expr

        if format:
            spark_format = convert_umf_format_to_spark(format)
            expr = f"try_to_timestamp({column}, '{spark_format}')"
        else:
            expr = f"try_to_timestamp({column})"
        return f"cast({expr} as date)" if t == "DATE" else expr

    if t == "BOOLEAN":
        # DuckDB cast aborts on malformed booleans; try_cast keeps NULL-on-failure
        # parity with the ANSI-disabled Spark baseline.
        return (
            f"try_cast({column} as boolean)"
            if is_duck
            else f"cast({column} as boolean)"
        )

    msg = f"Unsupported target_type for SQL cast: {target_type}"
    raise ValueError(msg)


def cast_column_with_format(
    column: Column,
    target_type: str,
    format: str | None = None,
) -> Column:
    """Cast a Spark column to target type with optional format support.

    This is the single source of truth for type casting used by both validation
    and ingestion to ensure consistency.

    Uses try_to_timestamp for graceful handling of invalid formats (Spark 4.0+).
    Returns NULL instead of throwing exceptions for invalid input.

    Args:
    ----
        column: Spark Column expression to cast
        target_type: Target type name (DATE, TIMESTAMP, INTEGER, DOUBLE, etc.)
        format: Optional UMF format string for DATE/TIMESTAMP casting

    Returns:
    -------
        Column expression with appropriate casting applied

    Examples:
    --------
        >>> # Date with custom format
        >>> cast_column_with_format(F.col("birth_date"), "DATE", "MM/DD/YYYY")
        try_to_timestamp(birth_date, "MM/dd/yyyy").cast("date")

        >>> # Timestamp with format
        >>> cast_column_with_format(F.col("created_at"), "TIMESTAMP", "YYYY-MM-DD HH:MM:SS")
        try_to_timestamp(created_at, "yyyy-MM-dd HH:mm:ss")

        >>> # Integer (no format needed)
        >>> cast_column_with_format(F.col("age"), "INTEGER")
        cast(age as int)

        >>> # Currency string to decimal
        >>> cast_column_with_format(F.col("price"), "DECIMAL")
        # "$100.00" -> 100.00

    Raises:
    ------
        ImportError: If PySpark is not available
        ValueError: If target_type is unsupported

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for casting operations"
        raise ImportError(msg)

    target_type_upper = target_type.upper()

    # Preprocess for numeric types: strip currency symbols and handle empty strings
    if target_type_upper in ("INTEGER", "DECIMAL", "DOUBLE", "FLOAT"):
        from pyspark.sql.types import StringType

        # Strip leading currency symbol ($) and trim whitespace
        column = F.regexp_replace(F.trim(column), r"^\$", "")
        # Convert empty/whitespace-only strings to NULL (Spark cast fails on empty strings)
        column = F.when(F.trim(column) == "", F.lit(None).cast(StringType())).otherwise(
            column
        )

    # STRING type - no casting needed, already string
    if target_type_upper == "STRING":
        logger.debug("Column already STRING type, no casting needed")
        return column

    # Map type names to Spark types for simple cast()
    if not SPARK_AVAILABLE:
        msg = "PySpark types required but not available"
        raise ImportError(msg)

    type_mapping = {
        "INTEGER": IntegerType(),  # type: ignore[misc]
        "DOUBLE": DoubleType(),  # type: ignore[misc]
        "FLOAT": DoubleType(),  # type: ignore[misc]
        "BOOLEAN": BooleanType(),  # type: ignore[misc]
        "DECIMAL": DecimalType(10, 2),  # type: ignore[misc]
    }

    # For DATE and TIMESTAMP with format, use try_to_timestamp for graceful handling
    if target_type_upper == "DATE" and format:
        spark_format = convert_umf_format_to_spark(format)
        logger.debug(f"Casting to DATE with format: {format} -> {spark_format}")
        return F.try_to_timestamp(column, F.lit(spark_format)).cast("date")  # type: ignore[attr-defined]

    if target_type_upper == "TIMESTAMP" and format:
        spark_format = convert_umf_format_to_spark(format)
        logger.debug(f"Casting to TIMESTAMP with format: {format} -> {spark_format}")
        return F.try_to_timestamp(column, F.lit(spark_format))  # type: ignore[attr-defined]

    # For DATE/TIMESTAMP without format, use try_to_timestamp with default format
    if target_type_upper == "DATE":
        return F.try_to_timestamp(column).cast("date")  # type: ignore[attr-defined]

    if target_type_upper == "TIMESTAMP":
        return F.try_to_timestamp(column)  # type: ignore[attr-defined]

    # For other types, use standard cast
    if target_type_upper in type_mapping:
        return column.cast(type_mapping[target_type_upper])

    # Unknown type
    msg = f"Unsupported target_type: {target_type}. Supported types: {[*list(type_mapping.keys()), 'DATE', 'TIMESTAMP', 'STRING']}"
    raise ValueError(msg)


def is_excel_serial_date(column: Column) -> Column:
    """Check if a string column contains Excel serial dates.

    Excel serial dates are integers representing days since 1900-01-01.
    Valid range: 1 (1900-01-01) to ~2958465 (9999-12-31)
    Common range for recent dates: 40000-50000 (2009-2036)

    Detection uses 4-6 digit pattern to cover dates from ~1927 to ~2737,
    which safely covers all realistic healthcare data dates while avoiding
    false positives with other numeric data.

    Args:
    ----
        column: Spark Column to check

    Returns:
    -------
        Boolean Column indicating if value looks like Excel serial date

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for Excel serial date detection"
        raise ImportError(msg)

    # Pattern: 4-6 digit integer (covers dates from ~1927 to ~2737)
    # This avoids false positives with epoch ms (12+ digits) and small IDs
    excel_serial_pattern = r"^[0-9]{4,6}$"

    return column.rlike(excel_serial_pattern)


def convert_excel_serial_to_date(column: Column) -> Column:
    """Convert Excel serial date to Spark date.

    Excel uses a serial date system where:
    - Serial 1 = January 1, 1900
    - Serial 2 = January 2, 1900
    - etc.

    Note: Excel incorrectly treats 1900 as a leap year (the Lotus 1-2-3 bug).
    For dates >= 60 (March 1, 1900), we subtract 1 extra day to compensate.
    However, for modern healthcare data (dates after 1900), this is handled
    correctly by the standard conversion.

    Conversion approach:
    - Use date_add from Excel epoch (Dec 30, 1899) by serial number of days
    - This avoids timezone issues that occur with Unix timestamp conversion

    Args:
    ----
        column: Spark Column containing Excel serial date as string

    Returns:
    -------
        Column with date values

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for Excel serial date conversion"
        raise ImportError(msg)

    # Excel epoch is Dec 30, 1899 (serial 0)
    # Use date_add to add the serial number of days to the epoch
    # This avoids timezone issues that occur with Unix timestamp conversion
    excel_epoch = F.lit("1899-12-30").cast("date")  # type: ignore[attr-defined]
    return F.date_add(excel_epoch, column.cast("int"))  # type: ignore[attr-defined]


def convert_excel_serial_to_timestamp(column: Column) -> Column:
    """Convert Excel serial date/time to Spark timestamp.

    Excel uses fractional serial numbers for time:
    - 45131.0 = midnight on July 24, 2023
    - 45131.5 = noon on July 24, 2023
    - 45131.75 = 6:00 PM on July 24, 2023

    Conversion approach:
    - Extract date portion using date_add from Excel epoch
    - Extract time portion from fractional part and add as seconds

    Args:
    ----
        column: Spark Column containing Excel serial date/time as string

    Returns:
    -------
        Column with timestamp values

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for Excel serial timestamp conversion"
        raise ImportError(msg)

    # Convert to double to handle fractional values
    serial_double = column.cast("double")

    # Extract the integer (date) and fractional (time) parts
    date_part = F.floor(serial_double).cast("int")  # type: ignore[attr-defined]
    time_fraction = serial_double - F.floor(serial_double)  # type: ignore[attr-defined]

    # Convert date part using date_add from Excel epoch
    excel_epoch = F.lit("1899-12-30").cast("date")  # type: ignore[attr-defined]
    date_value = F.date_add(excel_epoch, date_part)  # type: ignore[attr-defined]

    # Convert date to timestamp at midnight, then add time as seconds
    # Time fraction: 0.5 = 12 hours = 43200 seconds
    seconds_in_day = 86400
    time_seconds = (time_fraction * seconds_in_day).cast("long")

    # Combine: timestamp at midnight + time offset in seconds
    midnight_ts = date_value.cast("timestamp")
    return midnight_ts + F.expr("INTERVAL 1 SECOND") * time_seconds  # type: ignore[attr-defined]


def is_epoch_milliseconds(column: Column) -> Column:
    """Check if a string column contains epoch milliseconds (including scientific notation).

    Detects values like:
    - "1750000000000" (numeric epoch ms)
    - "1.75E+12" or "1.75e12" (scientific notation)

    Args:
    ----
        column: Spark Column to check

    Returns:
    -------
        Boolean Column indicating if value looks like epoch milliseconds

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for epoch detection"
        raise ImportError(msg)

    # Pattern for scientific notation: digits, optional decimal, E/e, optional +/-, digits
    scientific_pattern = r"^[0-9]+\.?[0-9]*[Ee][+\-]?[0-9]+$"

    # Pattern for large numeric values (epoch ms are typically 13+ digits for dates after 2001)
    large_number_pattern = r"^[0-9]{12,}$"

    # Use rlike directly on the column expression
    return column.rlike(scientific_pattern) | column.rlike(large_number_pattern)


def convert_epoch_ms_to_timestamp(column: Column) -> Column:
    """Convert epoch milliseconds (including scientific notation) to timestamp.

    Handles values like:
    - "1750000000000" → 2025-05-25 17:46:40
    - "1.75E+12" → 2025-05-25 17:46:40

    Args:
    ----
        column: Spark Column containing epoch ms as string

    Returns:
    -------
        Column with timestamp values

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for epoch conversion"
        raise ImportError(msg)

    # Cast to double first to handle scientific notation, then divide by 1000 for seconds
    epoch_seconds = column.cast("double") / 1000
    return F.from_unixtime(epoch_seconds).cast("timestamp")  # type: ignore[attr-defined]


def try_parse_flexible_timestamp(
    column: Column,
    primary_format: str,
    fallback_formats: list[str] | None = None,
) -> Column:
    """Try multiple timestamp formats, returning first successful parse.

    Used for columns where data may have partial components (e.g., date-only
    when expecting full timestamp). Time-only values return NULL.

    Uses try_to_timestamp for graceful handling of invalid formats.

    Args:
    ----
        column: Spark Column to parse
        primary_format: Primary UMF format to try first
        fallback_formats: Additional formats to try if primary fails

    Returns:
    -------
        Column with parsed timestamp, NULL if all formats fail

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for flexible timestamp parsing"
        raise ImportError(msg)

    formats_to_try = [primary_format]
    if fallback_formats:
        formats_to_try.extend(fallback_formats)
    formats_to_try = [fmt for fmt in formats_to_try if fmt]

    # Start with NULL as default
    result = F.lit(None).cast("timestamp")  # type: ignore[attr-defined]

    # Try formats in reverse order so first format has highest priority
    for fmt in reversed(formats_to_try):
        spark_format = convert_umf_format_to_spark(fmt)
        parsed = F.try_to_timestamp(column, F.lit(spark_format))  # type: ignore[attr-defined]

        # Use coalesce to keep first successful parse
        result = F.coalesce(parsed, result)  # type: ignore[attr-defined]

    # Preserve epoch parsing even when flexible formats are provided
    epoch_timestamp = convert_epoch_ms_to_timestamp(column)
    return F.when(is_epoch_milliseconds(column), epoch_timestamp).otherwise(  # type: ignore[attr-defined]
        result
    )


def cast_timestamp_with_epoch_fallback(
    column: Column,
    format: str | None = None,
) -> Column:
    """Cast to timestamp with automatic epoch millisecond detection and fallback.

    First checks if value looks like epoch ms (numeric or scientific notation).
    If so, converts from epoch. Otherwise, uses format-based parsing.

    Uses try_to_timestamp for graceful NULL handling of invalid values.

    Args:
    ----
        column: Spark Column to cast
        format: Optional UMF format string for non-epoch values

    Returns:
    -------
        Column with timestamp values

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for timestamp casting"
        raise ImportError(msg)

    # Detect if value looks like epoch milliseconds
    scientific_pattern = r"^[0-9]+\.?[0-9]*[Ee][+\-]?[0-9]+$"
    large_number_pattern = r"^[0-9]{12,}$"

    # Use rlike directly on the column expression
    is_epoch = column.rlike(scientific_pattern) | column.rlike(large_number_pattern)

    # Convert epoch ms to timestamp
    epoch_seconds = column.cast("double") / 1000
    epoch_timestamp = F.from_unixtime(epoch_seconds).cast("timestamp")  # type: ignore[attr-defined]

    # Parse with format
    if format:
        spark_format = convert_umf_format_to_spark(format)
        format_timestamp = F.try_to_timestamp(column, F.lit(spark_format))  # type: ignore[attr-defined]
    else:
        format_timestamp = F.try_to_timestamp(column)  # type: ignore[attr-defined]

    # Use epoch conversion if detected, otherwise use format parsing
    return F.when(is_epoch, epoch_timestamp).otherwise(format_timestamp)  # type: ignore[attr-defined]


def cast_date_with_flexible_fallback(
    column: Column,
    format: str | None = None,
) -> Column:
    """Cast to date with automatic multi-format fallback.

    Tries the specified format first (if provided), then falls back to
    common date formats, then common timestamp formats (extracting date portion).
    Also detects and converts Excel serial dates (e.g., 45141 -> 2023-07-24).

    This provides robust date parsing for data sources that may have varying
    date or timestamp formats, including raw Excel exports with serial dates.

    The format parameter (if provided) specifies the EXPECTED format for
    validation purposes, but parsing will still try common alternatives
    to maximize successful conversion.

    Uses try_to_timestamp for graceful NULL handling of invalid values.

    Args:
    ----
        column: Spark Column to cast
        format: Optional UMF format string for primary parsing attempt.
                If provided, this format is tried first.

    Returns:
    -------
        Column with date values

    Examples:
    --------
        >>> # With specified format (tried first, then fallbacks)
        >>> cast_date_with_flexible_fallback(F.col("date_col"), format="YYYY-MM-DD")

        >>> # Without format (tries all common formats)
        >>> cast_date_with_flexible_fallback(F.col("date_col"))

        >>> # Also handles timestamp values by extracting date portion
        >>> cast_date_with_flexible_fallback(F.col("col_with_timestamp"))
        # "2025-01-15 14:30:00" -> 2025-01-15

        >>> # Handles Excel serial dates
        >>> cast_date_with_flexible_fallback(F.col("excel_date"))
        # "45141" -> 2023-07-24

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for date casting"
        raise ImportError(msg)

    # Normalize whitespace: trim leading/trailing and collapse multiple internal spaces
    # This handles inputs like "  2025-01-15  " or "01/01/2024  10:00 AM"
    normalized_col = F.regexp_replace(F.trim(column), r"\s+", " ")  # type: ignore[attr-defined]

    # Detect Excel serial dates (4-6 digit integers like 45141)
    is_excel = is_excel_serial_date(F.trim(column))  # type: ignore[attr-defined]
    excel_date = convert_excel_serial_to_date(F.trim(column))  # type: ignore[attr-defined]

    # Build list of formats to try
    # Primary format first (if specified), then common date formats, then timestamp formats
    formats_to_try: list[str] = []
    if format:
        formats_to_try.append(format)
    # Add common date formats that aren't already the primary
    for common_fmt in COMMON_DATE_FORMATS:
        if common_fmt not in formats_to_try:
            formats_to_try.append(common_fmt)
    # Also try timestamp formats (we'll extract the date portion)
    for ts_fmt in COMMON_TIMESTAMP_FORMATS:
        if ts_fmt not in formats_to_try:
            formats_to_try.append(ts_fmt)

    # Start with NULL as default
    result = F.lit(None).cast("date")  # type: ignore[attr-defined]

    # Try formats in reverse order so first format has highest priority (via coalesce)
    for fmt in reversed(formats_to_try):
        spark_format = convert_umf_format_to_spark(fmt)
        # try_to_timestamp with cast to date for graceful NULL handling
        # This works for both date-only and timestamp formats
        parsed = F.try_to_timestamp(normalized_col, F.lit(spark_format)).cast("date")  # type: ignore[attr-defined]

        # Use coalesce to keep first successful parse
        result = F.coalesce(parsed, result)  # type: ignore[attr-defined]

    # Use Excel serial conversion if detected, otherwise use format-based parsing
    return F.when(is_excel, excel_date).otherwise(result)  # type: ignore[attr-defined]


def cast_timestamp_with_flexible_fallback(
    column: Column,
    format: str | None = None,
) -> Column:
    """Cast to timestamp with automatic multi-format, epoch, and Excel serial fallback.

    Combines epoch millisecond detection, Excel serial date/time detection, and
    multi-format timestamp parsing. Detection priority:
    1. Epoch milliseconds (12+ digits or scientific notation like 1.75E+12)
    2. Excel serial dates with optional time (4-6 digit numbers like 45141.5)
    3. Format-based parsing (tries specified format, then common formats)

    Uses try_to_timestamp for graceful NULL handling of invalid values.

    Args:
    ----
        column: Spark Column to cast
        format: Optional UMF format string for primary parsing attempt.
                If provided, this format is tried first after special format detection.

    Returns:
    -------
        Column with timestamp values

    Examples:
    --------
        >>> # Handles epoch ms (1.75E+12), standard formats, and date-only
        >>> cast_timestamp_with_flexible_fallback(F.col("ts_col"), format="M/D/YYYY h:mm A")

        >>> # Handles Excel serial dates with time
        >>> cast_timestamp_with_flexible_fallback(F.col("excel_datetime"))
        # "45141.5" -> 2023-07-24 12:00:00 (noon)

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for timestamp casting"
        raise ImportError(msg)

    # Normalize whitespace: trim leading/trailing and collapse multiple internal spaces
    # This handles inputs like "  2025-01-15 10:30  " or "01/01/2024  10:00  AM"
    normalized_col = F.regexp_replace(F.trim(column), r"\s+", " ")  # type: ignore[attr-defined]
    trimmed_col = F.trim(column)  # type: ignore[attr-defined]

    # Detect if value looks like epoch milliseconds (check before normalization affects it)
    scientific_pattern = r"^[0-9]+\.?[0-9]*[Ee][+\-]?[0-9]+$"
    large_number_pattern = r"^[0-9]{12,}$"
    is_epoch = trimmed_col.rlike(scientific_pattern) | trimmed_col.rlike(
        large_number_pattern
    )

    # Convert epoch ms to timestamp
    epoch_seconds = trimmed_col.cast("double") / 1000
    epoch_timestamp = F.from_unixtime(epoch_seconds).cast("timestamp")  # type: ignore[attr-defined]

    # Detect Excel serial dates (4-6 digits, optionally with decimal for time)
    # Pattern allows for fractional part (e.g., 45141.5 = noon on that date)
    excel_serial_pattern = r"^[0-9]{4,6}(\.[0-9]+)?$"
    is_excel = trimmed_col.rlike(excel_serial_pattern)
    excel_timestamp = convert_excel_serial_to_timestamp(trimmed_col)

    # Build list of formats to try for non-epoch values
    formats_to_try: list[str] = []
    if format:
        formats_to_try.append(format)
    # Add common formats that aren't already the primary
    for common_fmt in COMMON_TIMESTAMP_FORMATS:
        if common_fmt not in formats_to_try:
            formats_to_try.append(common_fmt)

    # Start with NULL as default
    format_timestamp = F.lit(None).cast("timestamp")  # type: ignore[attr-defined]

    # Try formats in reverse order so first format has highest priority (via coalesce)
    for fmt in reversed(formats_to_try):
        spark_format = convert_umf_format_to_spark(fmt)
        parsed = F.try_to_timestamp(normalized_col, F.lit(spark_format))  # type: ignore[attr-defined]

        # Use coalesce to keep first successful parse
        format_timestamp = F.coalesce(parsed, format_timestamp)  # type: ignore[attr-defined]

    # Priority: epoch ms > Excel serial > format-based parsing
    # Epoch ms checked first (12+ digits), then Excel serial (4-6 digits)
    return F.when(is_epoch, epoch_timestamp).otherwise(  # type: ignore[attr-defined]
        F.when(is_excel, excel_timestamp).otherwise(format_timestamp)  # type: ignore[attr-defined]
    )
