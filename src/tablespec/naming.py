# SPDX-License-Identifier: MIT OR Apache-2.0
"""Table naming utilities for canonical name, snake_case conversions, and position sorting."""

import re


def to_spark_identifier(name: str) -> str:
    """Convert any string to a valid Spark/SQL identifier (lowercase snake_case).

    Handles all edge cases:
    - Spaces and special characters → underscores
    - PascalCase/camelCase → snake_case
    - Multiple underscores → single underscore
    - Leading/trailing underscores → removed
    - Starts with digit → prefixed with letter
    - Empty string → fallback value

    Args:
        name: Input string in any format (canonical names, Excel headers, etc.)

    Returns:
        Valid lowercase snake_case identifier for Spark/SQL

    Examples:
        >>> to_spark_identifier("Member ID")
        'member_id'
        >>> to_spark_identifier("Inbound Only-Warm Transfer")
        'inbound_only_warm_transfer'
        >>> to_spark_identifier("ICD9/10")
        'icd9_10'
        >>> to_spark_identifier("OutreachList")
        'outreach_list'
        >>> to_spark_identifier("123_column")
        'col_123_column'

    """
    if not name:
        return "unknown"

    # Step 1: Replace all non-alphanumeric chars (except underscore) with underscore
    # This handles spaces, hyphens, slashes, etc.
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)

    # Step 2: Insert underscore before uppercase letters that follow lowercase letters
    # e.g., OutreachList → Outreach_List
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)

    # Step 3: Insert underscore before uppercase letters that are followed by lowercase
    # e.g., VAP_OutreachListPCP → VAP_Outreach_List_PCP
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)

    # Step 4: Convert to lowercase
    name = name.lower()

    # Step 5: Collapse multiple underscores
    name = re.sub(r"_+", "_", name)

    # Step 6: Remove leading/trailing underscores
    name = name.strip("_")

    # Step 7: Ensure starts with letter (Spark/SQL requirement)
    if name and name[0].isdigit():
        name = "col_" + name

    return name or "unknown"


def to_snake_case(name: str) -> str:
    """Convert PascalCase, camelCase, or mixed case names to snake_case.

    Handles:
    - PascalCase: OutreachList → outreach_list
    - Existing underscores: VAP_OutreachListPCP → vap_outreach_list_pcp
    - Mixed: Centene_Disposition_V_4_0 → centene_disposition_v_4_0
    - Periods: Centene_Disposition_V_4.0 → centene_disposition_v_4_0

    Args:
        name: Input name in any case format

    Returns:
        Lowercase snake_case version

    Examples:
        >>> to_snake_case("OutreachList")
        'outreach_list'
        >>> to_snake_case("VAP_OutreachListPCP")
        'vap_outreach_list_pcp'
        >>> to_snake_case("DisenrollmentFile")
        'disenrollment_file'
        >>> to_snake_case("Centene_Disposition_V_4_0")
        'centene_disposition_v_4_0'
        >>> to_snake_case("Centene_Disposition_V_4.0")
        'centene_disposition_v_4_0'

    """
    # Insert underscore before uppercase letters that follow lowercase letters
    # e.g., OutreachList → Outreach_List
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)

    # Insert underscore before uppercase letters that are followed by lowercase
    # e.g., VAP_OutreachListPCP → VAP_Outreach_List_PCP
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)

    # Convert to lowercase
    name = name.lower()

    # Replace periods with underscores (for version numbers like v4.0)
    name = name.replace(".", "_")

    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)

    # Remove leading/trailing underscores
    return name.strip("_")


def excel_column_to_number(col_str: str) -> int:
    """Convert Excel column letters to number (A=1, Z=26, AA=27, etc.).

    Args:
        col_str: Excel column letters (e.g., "A", "Z", "AA", "AB")

    Returns:
        Numeric position (1-based)

    Examples:
        >>> excel_column_to_number("A")
        1
        >>> excel_column_to_number("Z")
        26
        >>> excel_column_to_number("AA")
        27
        >>> excel_column_to_number("AB")
        28
        >>> excel_column_to_number("AZ")
        52

    """
    result = 0
    for char in col_str.upper():
        if "A" <= char <= "Z":
            result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def position_sort_key(position: str | None, fallback_index: int = 0) -> tuple[int, int]:
    """Create a sort key for UMF column position field.

    Handles multiple position formats:
    - None: Returns high sort priority (positioned at end)
    - Numeric strings: "1", "2", "10" → sorted numerically
    - Excel columns: "A", "B", "AA" → sorted in Excel order (A, B, ..., Z, AA, AB, ...)
    - Other strings: Sorted with high priority

    Args:
        position: Position value from UMF column (can be None)
        fallback_index: Index to use if position cannot be parsed (default: 0)

    Returns:
        Tuple of (priority, numeric_value) for stable sorting
        - priority 0: Valid position (numeric or Excel column)
        - priority 1: No position (None)
        - priority 2: Unparseable string

    Examples:
        >>> position_sort_key("1")
        (0, 1)
        >>> position_sort_key("10")
        (0, 10)
        >>> position_sort_key("A")
        (0, 1)
        >>> position_sort_key("AA")
        (0, 27)
        >>> position_sort_key(None)
        (1, 0)

    """
    if position is None:
        return (1, fallback_index)  # None positions go after valid positions

    # Try parsing as integer (row number)
    try:
        return (0, int(position))
    except (ValueError, TypeError):
        pass

    # Try parsing as Excel column letter(s)
    if re.match(r"^[A-Z]+$", position.upper()):
        return (0, excel_column_to_number(position))

    # Fallback: unparseable string
    return (2, fallback_index)
