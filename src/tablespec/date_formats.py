"""Supported date and datetime formats for UMF specifications.

This module defines all supported date/datetime formats and provides validation
and conversion utilities. Format strings must be explicitly supported to ensure
consistent behavior across sample data generation, validation, and type conversion.

UMF Format Notation:
    YYYY - 4-digit year
    YY   - 2-digit year
    MM   - 2-digit month (01-12)
    M    - 1-2 digit month (1-12, no zero padding)
    DD   - 2-digit day (01-31)
    dd   - 2-digit day (01-31), lowercase variant
    D    - 1-2 digit day (1-31, no zero padding)
    d    - 1-2 digit day (1-31, no zero padding), lowercase variant
    HH   - 24-hour hour (00-23)
    hh   - 12-hour hour (01-12)
    h    - 1-2 digit 12-hour hour (1-12, no zero padding)
    mm   - 2-digit minutes (00-59)
    MM   - 2-digit minutes when in time context (after HH:)
    SS   - 2-digit seconds (00-59)
    ss   - 2-digit seconds (00-59), lowercase variant
    A    - AM/PM marker (uppercase)
    a    - am/pm marker (lowercase)
"""

from dataclasses import dataclass
from enum import Enum


class FormatType(Enum):
    """Type of date/time format."""

    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"


@dataclass(frozen=True)
class DateFormat:
    """A supported date/datetime format with its strftime equivalent."""

    umf_format: str
    strftime_format: str
    format_type: FormatType
    description: str


# All supported date formats - these are the ONLY formats that should be used
# in UMF specifications for date/datetime columns
SUPPORTED_DATE_FORMATS: tuple[DateFormat, ...] = (
    # ISO date formats (preferred)
    DateFormat("YYYY-MM-DD", "%Y-%m-%d", FormatType.DATE, "ISO 8601 date"),
    DateFormat("YYYY/MM/DD", "%Y/%m/%d", FormatType.DATE, "ISO date with slashes"),
    # US date formats (MM/DD/YYYY family)
    DateFormat("MM/DD/YYYY", "%m/%d/%Y", FormatType.DATE, "US date with slashes"),
    DateFormat("MM-DD-YYYY", "%m-%d-%Y", FormatType.DATE, "US date with dashes"),
    DateFormat(
        "M/D/YYYY", "%-m/%-d/%Y", FormatType.DATE, "US date without zero padding"
    ),
    DateFormat(
        "M/d/YYYY",
        "%-m/%-d/%Y",
        FormatType.DATE,
        "US date without zero padding (mixed case)",
    ),
    DateFormat(
        "M/d/yyyy",
        "%-m/%-d/%Y",
        FormatType.DATE,
        "US date without zero padding (lowercase year)",
    ),
    # NOTE: European date formats (DD/MM/YYYY, DD-MM-YYYY) intentionally excluded
    # to avoid ambiguity with US formats. For US healthcare data, MM/DD/YYYY
    # is the standard convention.
    # Compact date formats
    DateFormat("YYYYMMDD", "%Y%m%d", FormatType.DATE, "Compact date"),
    DateFormat("MMDDYYYY", "%m%d%Y", FormatType.DATE, "Compact US date"),
    # ISO datetime formats (preferred)
    DateFormat(
        "YYYY-MM-DD HH:MM:SS",
        "%Y-%m-%d %H:%M:%S",
        FormatType.DATETIME,
        "ISO 8601 datetime",
    ),
    DateFormat(
        "YYYY-MM-DDTHH:MM:SS",
        "%Y-%m-%dT%H:%M:%S",
        FormatType.DATETIME,
        "ISO 8601 datetime with T separator",
    ),
    DateFormat(
        "YYYY-MM-DD HH:MM",
        "%Y-%m-%d %H:%M",
        FormatType.DATETIME,
        "ISO datetime without seconds",
    ),
    # US datetime formats
    DateFormat(
        "MM/DD/YYYY HH:MM:SS",
        "%m/%d/%Y %H:%M:%S",
        FormatType.DATETIME,
        "US datetime 24-hour",
    ),
    DateFormat(
        "MM/DD/YYYY hh:mm:ss A",
        "%m/%d/%Y %I:%M:%S %p",
        FormatType.DATETIME,
        "US datetime 12-hour with AM/PM",
    ),
    DateFormat(
        "M/D/YYYY h:mm A",
        "%-m/%-d/%Y %-I:%M %p",
        FormatType.DATETIME,
        "US datetime 12-hour no padding with AM/PM",
    ),
    DateFormat(
        "M/d/YYYY h:mm A",
        "%-m/%-d/%Y %-I:%M %p",
        FormatType.DATETIME,
        "US datetime 12-hour no padding with AM/PM (mixed case)",
    ),
    DateFormat(
        "M/d/yyyy h:mm a",
        "%-m/%-d/%Y %-I:%M %p",
        FormatType.DATETIME,
        "US datetime 12-hour no padding with am/pm (lowercase)",
    ),
    DateFormat(
        "M/d/yyyy, h:mm a",
        "%-m/%-d/%Y, %-I:%M %p",
        FormatType.DATETIME,
        "US datetime with comma separator",
    ),
    DateFormat(
        "MM/dd/yyyy h:mma",
        "%m/%d/%Y %-I:%M%p",
        FormatType.DATETIME,
        "US datetime 12-hour with attached am/pm",
    ),
    DateFormat(
        "MM/dd/yyyy h:mmA",
        "%m/%d/%Y %-I:%M%p",
        FormatType.DATETIME,
        "US datetime 12-hour with attached AM/PM",
    ),
    DateFormat(
        "MM/DD/YYYY hh:mm A",
        "%m/%d/%Y %I:%M %p",
        FormatType.DATETIME,
        "US datetime 12-hour uppercase with AM/PM",
    ),
    DateFormat(
        "M/D/YYYY, h:mm A",
        "%-m/%-d/%Y, %-I:%M %p",
        FormatType.DATETIME,
        "US datetime with comma separator and AM/PM",
    ),
    DateFormat(
        "M/D/YYYY h:mm:ss A",
        "%-m/%-d/%Y %-I:%M:%S %p",
        FormatType.DATETIME,
        "US datetime 12-hour no padding with seconds and AM/PM",
    ),
    DateFormat(
        "YYYY-MM-DD HH:mm:ss",
        "%Y-%m-%d %H:%M:%S",
        FormatType.DATETIME,
        "ISO 8601 datetime with lowercase minutes/seconds",
    ),
    # Fractional-second datetime formats. Both map to the portable strftime %f
    # (microseconds) so this strftime_format stays Python-parseable. The WIDTH
    # difference that matters for cross-engine parity -- Spark ".SSS" accepts only
    # 1-3 fractional digits and NULLs a 4+/6-digit fraction, while ".SSSSSS" accepts
    # 1-6, whereas DuckDB %f greedily consumes 1-6 -- is enforced for DuckDB by the
    # padding pre-filter (which derives the fractional digit cap from the UMF S-run,
    # not from %f), so DuckDB NULLs exactly what Spark NULLs. See
    # casting_utils._duckdb_padding_prefilter_regex.
    DateFormat(
        "YYYY-MM-DD HH:MM:SS.SSSSSS",
        "%Y-%m-%d %H:%M:%S.%f",
        FormatType.DATETIME,
        "ISO 8601 datetime with microseconds",
    ),
    DateFormat(
        "YYYY-MM-DD HH:MM:SS.SSS",
        "%Y-%m-%d %H:%M:%S.%f",
        FormatType.DATETIME,
        "ISO 8601 datetime with milliseconds",
    ),
    # Time only formats
    DateFormat("HH:MM:SS", "%H:%M:%S", FormatType.TIME, "24-hour time with seconds"),
    DateFormat("HH:MM", "%H:%M", FormatType.TIME, "24-hour time without seconds"),
    DateFormat("hh:mm:ss A", "%I:%M:%S %p", FormatType.TIME, "12-hour time with AM/PM"),
    DateFormat("hh:mm A", "%I:%M %p", FormatType.TIME, "12-hour time with AM/PM"),
    DateFormat(
        "h:mm a", "%-I:%M %p", FormatType.TIME, "12-hour time no padding with am/pm"
    ),
)

# Build lookup dictionaries for fast access
_FORMAT_BY_UMF: dict[str, DateFormat] = {
    fmt.umf_format: fmt for fmt in SUPPORTED_DATE_FORMATS
}

# Case-insensitive lookup (normalize common variations)
_FORMAT_BY_UMF_NORMALIZED: dict[str, DateFormat] = {}
for fmt in SUPPORTED_DATE_FORMATS:
    # Add the exact format
    _FORMAT_BY_UMF_NORMALIZED[fmt.umf_format] = fmt
    # Also add normalized versions for common case variations
    # This handles cases like "YYYY-MM-DD" vs "yyyy-mm-dd"


def get_supported_umf_formats() -> list[str]:
    """Get list of all supported UMF format strings."""
    return list(_FORMAT_BY_UMF.keys())


def is_supported_format(umf_format: str | None) -> bool:
    """Check if a UMF format string is supported.

    Args:
        umf_format: The UMF format string to check

    Returns:
        True if the format is supported, False otherwise

    """
    if not umf_format:
        return False
    return umf_format in _FORMAT_BY_UMF


def get_strftime_format(umf_format: str) -> str | None:
    """Get the Python strftime format for a UMF format string.

    Args:
        umf_format: The UMF format string

    Returns:
        The corresponding strftime format, or None if not supported

    """
    fmt = _FORMAT_BY_UMF.get(umf_format)
    return fmt.strftime_format if fmt else None


def get_format_type(umf_format: str) -> FormatType | None:
    """Get the format type (date, datetime, or time) for a UMF format string.

    Args:
        umf_format: The UMF format string

    Returns:
        The FormatType, or None if not supported

    """
    fmt = _FORMAT_BY_UMF.get(umf_format)
    return fmt.format_type if fmt else None


def validate_format_for_data_type(umf_format: str, data_type: str) -> str | None:
    """Validate that a format is appropriate for the given data type.

    Args:
        umf_format: The UMF format string
        data_type: The UMF data type (e.g., "DateType", "TimestampType", "StringType")

    Returns:
        Error message if validation fails, None if valid

    """
    if not umf_format:
        return None  # No format specified is OK

    fmt = _FORMAT_BY_UMF.get(umf_format)
    if fmt is None:
        supported = get_supported_umf_formats()
        return (
            f"Unsupported date/datetime format: '{umf_format}'. "
            f"Supported formats: {', '.join(sorted(supported))}"
        )

    # Check format type matches data type
    data_type_lower = data_type.lower() if data_type else ""

    if "date" in data_type_lower and "time" not in data_type_lower:
        # DateType should use DATE format
        if fmt.format_type != FormatType.DATE:
            return (
                f"Format '{umf_format}' is a {fmt.format_type.value} format, "
                f"but column data_type is {data_type}. Use a date format instead."
            )
    elif "timestamp" in data_type_lower or (
        "date" in data_type_lower and "time" in data_type_lower
    ):
        # TimestampType or DateTimeType can use DATE or DATETIME format
        if fmt.format_type not in (FormatType.DATE, FormatType.DATETIME):
            return (
                f"Format '{umf_format}' is a {fmt.format_type.value} format, "
                f"but column data_type is {data_type}. Use a date or datetime format instead."
            )

    return None  # Valid


def suggest_format_for_example(example: str) -> str | None:
    """Suggest a format based on an example value.

    Args:
        example: An example date/datetime value

    Returns:
        Suggested UMF format, or None if no match

    """
    from datetime import datetime

    if not example:
        return None

    # Try each supported format
    for fmt in SUPPORTED_DATE_FORMATS:
        try:
            datetime.strptime(example, fmt.strftime_format)
            return fmt.umf_format
        except ValueError:
            continue

    return None
