"""Date format conversion and constraint extraction utilities for sample data generation."""

from datetime import datetime
import logging
import re
from typing import Any

from tablespec.date_formats import get_strftime_format, is_supported_format
from tablespec.expectation_utils import expectation_dicts_from_umf_data

logger = logging.getLogger(__name__)

# Cache for formats that have already been warned about (to avoid log spam)
_warned_formats: set[str] = set()


def convert_umf_format_to_strftime(umf_format: str | None) -> str | None:
    """Convert UMF date format specification to Python strftime format.

    First checks if the format is a known supported format (from date_formats module),
    and if so, uses the pre-defined mapping. Falls back to dynamic conversion for
    formats that aren't in the supported list.

    Args:
        umf_format: UMF date format string (e.g., "MM/DD/YYYY", "YYYY-MM-DD HH:mm:ss")

    Returns:
        Python strftime format string, or None if input is None/empty

    """
    if not umf_format:
        return None

    # First, try to get from the supported formats registry
    if is_supported_format(umf_format):
        result = get_strftime_format(umf_format)
        if result:
            return result

    # Check if this is clearly NOT a date format (phone numbers, descriptions, etc.)
    # Skip warning and return None for non-date format patterns
    non_date_patterns = ["XXX", "(", ")", "#", "@", "phone", "fax"]
    # Also skip descriptive format strings (not actual date format specifiers)
    descriptive_phrases = [
        "alphanumeric",
        "letters",
        "integer",
        "digits",
        "text",
        "string",
        "free",
    ]
    if any(pattern in umf_format for pattern in non_date_patterns):
        return None
    if any(phrase in umf_format.lower() for phrase in descriptive_phrases):
        return None

    # Fall back to dynamic conversion for unknown formats
    # Only log warning once per unique format to avoid spam
    if umf_format not in _warned_formats:
        _warned_formats.add(umf_format)
        logger.warning(
            f"Date format '{umf_format}' is not in the supported formats list. "
            f"Consider adding it to tablespec.date_formats.SUPPORTED_DATE_FORMATS"
        )

    return _dynamic_format_conversion(umf_format)


def _dynamic_format_conversion(umf_format: str) -> str:
    """Dynamically convert UMF format to strftime (fallback for unknown formats).

    This is used when a format isn't in the supported formats list. It provides
    best-effort conversion but may not handle all edge cases correctly.

    Args:
        umf_format: UMF date format string

    Returns:
        Python strftime format string

    """
    result = umf_format

    # First, handle time portion where uppercase MM/SS may be used
    # Convert patterns like "HH:MM:SS" to use placeholders to avoid conflicts
    # with date MM (month)

    # Replace time patterns - be case-sensitive to distinguish 24h (HH) from 12h (hh)
    # HH = 24-hour format, hh = 12-hour format
    result = re.sub(r"HH:MM:SS", "%H:%M:%S", result)  # 24-hour with seconds
    result = re.sub(r"HH:MM", "%H:%M", result)  # 24-hour without seconds
    result = re.sub(r"hh:mm:ss", "%I:%M:%S", result)  # 12-hour with seconds
    result = re.sub(r"hh:mm", "%I:%M", result)  # 12-hour without seconds
    result = re.sub(r":SS", ":%S", result)  # Standalone :SS at end
    result = re.sub(r":ss", ":%S", result)  # Standalone :ss at end

    # Common UMF format to strftime mapping
    # Order matters - replace longer patterns first to avoid partial matches
    format_map = [
        ("YYYY", "%Y"),  # 4-digit year (uppercase)
        ("yyyy", "%Y"),  # 4-digit year (lowercase)
        ("YY", "%y"),  # 2-digit year (uppercase)
        ("yy", "%y"),  # 2-digit year (lowercase)
        ("MMMM", "%B"),  # Full month name
        ("MMM", "%b"),  # Abbreviated month name
        ("MM", "%m"),  # 2-digit month (only remaining MM after time handling)
        ("DD", "%d"),  # 2-digit day (zero-padded, uppercase)
        ("dd", "%d"),  # 2-digit day (zero-padded, lowercase)
        ("HH", "%H"),  # 24-hour hour
        ("hh", "%I"),  # 12-hour hour (zero-padded)
        (
            "mma",
            "%M%p",
        ),  # Minutes + am/pm marker (combined to avoid partial match issues)
        ("mmA", "%M%p"),  # Minutes + AM/PM marker
        ("mm", "%M"),  # Minutes (lowercase variant)
        ("ss", "%S"),  # Seconds (lowercase variant)
        ("AM", "%p"),  # AM/PM (uppercase)
        ("PM", "%p"),  # AM/PM (uppercase)
        ("am", "%p"),  # am/pm (lowercase)
        ("pm", "%p"),  # am/pm (lowercase)
    ]

    for umf_code, strftime_code in format_map:
        result = result.replace(umf_code, strftime_code)

    # Single-character patterns need regex to avoid matching already-converted codes
    # Only match standalone A/D/M/h/a/d not preceded by % or %- or followed by same char
    # The (?<!%-) lookbehind prevents double-conversion of already-converted codes like %-d
    result = re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])A(?![A-Za-z])", "%p", result
    )  # AM/PM marker (uppercase)
    result = re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])a(?![A-Za-z])", "%p", result
    )  # am/pm marker (lowercase)
    result = re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])D(?![A-Za-z])", "%-d", result
    )  # Day (no zero, uppercase)
    result = re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])d(?![A-Za-z])", "%-d", result
    )  # Day (no zero, lowercase)
    result = re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])M(?![A-Za-z])", "%-m", result
    )  # Month (no zero)
    return re.sub(
        r"(?<!%)(?<!%-)(?<![A-Za-z])h(?![A-Za-z])", "%-I", result
    )  # Hour 12h (no zero)


def extract_date_constraints(
    col_name: str, umf_data: dict[str, Any]
) -> dict[str, str] | None:
    """Extract min/max date constraints from validation expectations.

    Looks for expect_column_values_to_be_between expectations and pending
    validation rules that contain date range constraints.

    Args:
        col_name: Name of the column
        umf_data: UMF data dictionary

    Returns:
        Dictionary with min_value and/or max_value keys if found, else None

    """
    for expectation in expectation_dicts_from_umf_data(umf_data):
        exp_type = expectation.get("type", "")
        kwargs = expectation.get("kwargs", {})

        # Check if this expectation is for our column
        if kwargs.get("column") != col_name:
            continue

        # Check for expect_column_values_to_be_between
        if exp_type == "expect_column_values_to_be_between":
            result = {}
            if "min_value" in kwargs:
                result["min_value"] = kwargs["min_value"]
            if "max_value" in kwargs:
                result["max_value"] = kwargs["max_value"]
            if result:
                return result

        # Check for pending validation rules with date constraints
        # These are created when GX can't handle date ranges
        if exp_type == "expect_validation_rule_pending_implementation":
            meta = expectation.get("meta", {})
            sanitization_note = meta.get("sanitization_note", "")

            # Look for converted expect_column_values_to_be_between
            if "expect_column_values_to_be_between" in sanitization_note:
                # Try to extract min/max from the sanitization note
                # Format: "min/max values (1900-01-01, 2025-10-17)"
                pattern = r"values \(([^,]+),\s*([^)]+)\)"
                match = re.search(pattern, sanitization_note)
                if match:
                    min_val = match.group(1).strip()
                    max_val = match.group(2).strip()
                    return {"min_value": min_val, "max_value": max_val}

        # Check for value_sets with dates - extract min/max range
        # These are typically warning-level expectations meant as outlier detection
        # But they provide useful date ranges for sample data generation
        if exp_type == "expect_column_values_to_be_in_set":
            value_set = kwargs.get("value_set", [])
            if not value_set:
                continue

            # Try to parse as dates to extract min/max range
            parsed_dates = []
            for val in value_set:
                try:
                    # Try common date formats
                    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d", "%m-%d-%Y"]:
                        try:
                            parsed = datetime.strptime(str(val), fmt)
                            parsed_dates.append((parsed, fmt))
                            break
                        except ValueError:
                            continue
                except Exception as e:
                    logger.debug(
                        f"Could not parse value_set value '{val}' as date for {col_name}: {e}"
                    )
                    continue

            if parsed_dates:
                # Extract min/max dates
                min_date = min(d[0] for d in parsed_dates)
                max_date = max(d[0] for d in parsed_dates)
                date_format = parsed_dates[0][1]  # Use format from first parsed date

                return {
                    "min_value": min_date.strftime(date_format),
                    "max_value": max_date.strftime(date_format),
                }

    return None
