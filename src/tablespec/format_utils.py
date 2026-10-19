# SPDX-License-Identifier: MIT OR Apache-2.0
"""Format conversion utilities for UMF metadata.

This module provides utilities to convert between different date/time format specifications,
particularly UMF format strings and Python/Spark format strings.
"""

from __future__ import annotations

import re


def convert_umf_format_to_strftime(umf_format: str) -> str:
    """Convert UMF date format string to Python strftime format.

    Handles the ambiguous MM token which can mean either month or minutes
    depending on context (date vs time component). Also handles single-character
    formats (M, D) for non-zero-padded month/day.

    Args:
    ----
        umf_format: UMF date format (e.g., "YYYY-MM-DD", "M/D/YYYY", "YYYY-MM-DD HH:MM:SS")

    Returns:
    -------
        strftime format string (e.g., "%Y-%m-%d", "%-m/%-d/%Y", "%Y-%m-%d %H:%M:%S")

    Examples:
    --------
        >>> convert_umf_format_to_strftime("YYYY-MM-DD")
        '%Y-%m-%d'
        >>> convert_umf_format_to_strftime("YYYY-MM-DD HH:MM:SS")
        '%Y-%m-%d %H:%M:%S'
        >>> convert_umf_format_to_strftime("MM/DD/YYYY")
        '%m/%d/%Y'
        >>> convert_umf_format_to_strftime("DD/MM/YYYY")
        '%d/%m/%Y'
        >>> convert_umf_format_to_strftime("M/D/YYYY")
        '%-m/%-d/%Y'

    Note:
    ----
        MM is ambiguous in UMF specs - it can mean month or minutes. This function
        disambiguates by replacing MM in time contexts (after HH:) with minutes (%M),
        and MM in date contexts with month (%m).

    """
    # Handle non-ambiguous tokens first (order matters - longer patterns first)
    result = umf_format
    result = result.replace("YYYY", "%Y")
    result = result.replace("YY", "%y")
    result = result.replace("DD", "%d")
    result = result.replace("HH", "%H")
    result = result.replace("SS", "%S")

    # Handle MM ambiguity based on context
    # If we have time components (HH:), MM after : is minutes, otherwise MM is month
    # Replace MM after HH: with %M (minutes)
    result = re.sub(r"%H:MM", "%H:%M", result)

    # Replace any remaining MM with %m (month in date context)
    result = result.replace("MM", "%m")

    # Handle single-character formats for non-zero-padded values
    # Must use regex to avoid replacing M/D that are part of strftime codes (%m, %d)
    # (?<!%) ensures we don't match after a % (already converted)
    # (?![A-Za-z]) ensures we don't match if followed by letters (e.g., MM already handled)
    result = re.sub(r"(?<!%)(?<![A-Za-z])D(?![A-Za-z])", "%-d", result)
    return re.sub(r"(?<!%)(?<![A-Za-z])M(?![A-Za-z])", "%-m", result)
