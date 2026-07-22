"""Filename generation from UMF patterns."""

import logging
import re
from typing import Any


class FilenameGenerator:
    """Handles filename generation from UMF patterns.

    Responsible for:
    - Parsing filename patterns with capture groups
    - Extracting capture group patterns for specific columns
    - Generating filenames from UMF patterns and record data
    - Validating generated filenames against patterns
    """

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize the filename generator.

        Args:
            logger: Logger for filename generation operations

        """
        self.logger = logger

    def get_capture_group_pattern_for_column(
        self, col_name: str, captures: dict[str, Any], filename_pattern: str
    ) -> str | None:
        """Extract the regex pattern for a specific column's capture group.

        Args:
            col_name: Column name to find pattern for
            captures: Capture group mapping (e.g., {"1": "source_vendor_prefix", "2": "source_file_date"})
            filename_pattern: Full filename regex pattern

        Returns:
            Regex pattern for the capture group, or None if not found

        """
        # Find which capture group index corresponds to this column
        capture_idx = None
        for idx_str, col_name_or_meta in captures.items():
            # Handle both string column names and dict metadata
            if isinstance(col_name_or_meta, dict):
                captured_col_name = col_name_or_meta.get(
                    "column"
                ) or col_name_or_meta.get("name")
            else:
                captured_col_name = col_name_or_meta

            if captured_col_name == col_name:
                capture_idx = int(idx_str)
                break

        if capture_idx is None:
            return None

        # Extract the Nth capturing group pattern from the full regex
        # Strategy: Parse the regex and extract the Nth capturing group
        pattern = filename_pattern.lstrip("^").rstrip("$")

        # Find all capturing groups (not non-capturing like (?:...))
        capture_patterns = []
        i = 0
        while i < len(pattern):
            if pattern[i] == "(":
                # Check if it's a capturing group (not (?:...) or (?=...) etc.)
                if i + 1 < len(pattern) and pattern[i + 1] == "?":
                    # Non-capturing or lookahead/lookbehind - skip
                    i += 1
                    continue

                # Find the matching closing parenthesis
                start = i + 1  # Start after opening paren
                depth = 1
                end = start
                for j in range(start, len(pattern)):
                    if pattern[j] == "\\":
                        # Skip escaped characters
                        end = j + 2
                        continue
                    if pattern[j] == "(":
                        depth += 1
                    elif pattern[j] == ")":
                        depth -= 1
                        if depth == 0:
                            end = j
                            break

                # Extract the pattern between parentheses
                capture_pattern = pattern[start:end]
                capture_patterns.append(capture_pattern)
                i = end + 1
            else:
                i += 1

        # Return the pattern for the requested capture group (1-indexed)
        if 1 <= capture_idx <= len(capture_patterns):
            return capture_patterns[capture_idx - 1]

        return None

    def generate_filename_from_pattern(
        self, table_name: str, umf_data: dict[str, Any], records: list[dict]
    ) -> str:
        """Generate filename using pattern from UMF file_format.

        Args:
            table_name: Name of the table
            umf_data: UMF specification
            records: Generated records (to extract filename column values)

        Returns:
            Generated filename with pattern or simple {table_name}.txt as fallback

        """
        # Check if UMF has filename pattern
        file_format = umf_data.get("file_format", {})
        filename_pattern_field = file_format.get("filename_pattern")

        # Handle both flat (legacy YAML) and nested (Pydantic model_dump) structures
        # Flat structure: file_format.filename_pattern = "regex...", file_format.captures = {...}
        # Nested structure: file_format.filename_pattern = {"regex": "...", "captures": {...}}
        if isinstance(filename_pattern_field, dict):
            # Nested structure after Pydantic normalization
            filename_pattern = filename_pattern_field.get("regex")
            captures = filename_pattern_field.get("captures", {})
        else:
            # Flat/legacy structure from raw YAML
            filename_pattern = filename_pattern_field
            captures = file_format.get("captures", {})

        if not filename_pattern:
            # No pattern - use simple naming
            return f"{table_name}.txt"

        if not records:
            return f"{table_name}.txt"

        # Extract values from first record for filename-sourced columns
        sample_record = records[0]
        filename_values = {}

        for capture_idx_str, col_name_or_meta in captures.items():
            # Handle both string column names and dict metadata
            # String format: col_name = "column_name"
            # Dict format: col_name = {"column": "column_name", ...} or {"name": "column_name", ...}
            if isinstance(col_name_or_meta, dict):
                # Extract column name from dict metadata
                col_name = col_name_or_meta.get("column") or col_name_or_meta.get(
                    "name"
                )
                if not col_name:
                    self.logger.warning(
                        f"{table_name}: capture {capture_idx_str} has dict metadata but no 'column' or 'name' key: {col_name_or_meta}"
                    )
                    filename_values[int(capture_idx_str)] = "UNKNOWN"
                    continue
            else:
                # Assume it's a string column name
                col_name = col_name_or_meta

            # For filename-sourced columns, use sample_values from UMF instead of data record
            # (filename columns aren't in the data rows - they're extracted FROM the filename)
            col_def = next(
                (c for c in umf_data.get("columns", []) if c["name"] == col_name), None
            )
            if col_def and col_def.get("source") == "filename":
                # Use first sample value from UMF
                sample_values = col_def.get("sample_values", [])
                value = sample_values[0] if sample_values else "UNKNOWN"
            else:
                # For data columns, get from sample record
                value = sample_record.get(col_name, "UNKNOWN")

            # Convert to string and handle None
            filename_values[int(capture_idx_str)] = (
                str(value) if value is not None else "UNKNOWN"
            )

        # Parse the regex pattern to extract the template structure
        # Pattern example: ^(VENDOR)_(STATE)_(LOB)_OutreachList_(\d{4})_(\d{8})(?:_([MODE]))?\.txt$
        # We need to identify capture groups vs literals and reconstruct the filename

        umf_data.get("canonical_name", table_name)

        if not filename_pattern:
            return f"{table_name}.txt"

        # Remove anchors, inline flags, and extension from pattern
        pattern = filename_pattern
        # Remove inline flags like (?i), (?m), etc.
        pattern = re.sub(r"^\(\?[iLmsux]+\)", "", pattern)
        # Remove anchors
        pattern = pattern.lstrip("^").rstrip("$")
        # Extract file extension from pattern before removing it
        # Look for common patterns like \.txt, \.csv, \.xlsx at the end
        file_extension = ".txt"  # default
        ext_match = re.search(r"\\\.([a-zA-Z0-9]+)$", pattern)
        if ext_match:
            file_extension = f".{ext_match.group(1)}"
        # Remove file extension from pattern for processing
        pattern = re.sub(r"\\?\.[a-zA-Z0-9]+$", "", pattern)

        # Parse pattern to build template
        # Strategy: Replace each capturing group with {N}, keeping literals
        template_pattern = pattern
        capture_idx = 1

        # First pass: Replace all capturing groups (not non-capturing) with placeholders
        # A capturing group is (...) but NOT (?:...) or (?=...) or (?!...) etc.
        while True:
            # Find the next capturing group (parenthesis not followed by ?)
            match = re.search(r"\((?!\?)", template_pattern)
            if not match:
                break

            # Find the matching closing parenthesis
            start = match.start()
            depth = 0
            end = start
            for i in range(start, len(template_pattern)):
                if template_pattern[i] == "(":
                    depth += 1
                elif template_pattern[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

            # Replace this capturing group with placeholder
            template_pattern = (
                template_pattern[:start]
                + f"{{{capture_idx}}}"
                + template_pattern[end + 1 :]
            )
            capture_idx += 1

        # Second pass: Remove optional non-capturing groups that don't contain capture placeholders
        # Pattern: (?:...)?  where ... doesn't contain {N}
        # These are truly optional parts with no data, so they should be omitted from filenames
        while True:
            # Find optional non-capturing groups: (?:...)?
            match = re.search(r"\(\?:[^)]*\)\?", template_pattern)
            if not match:
                break

            # Check if this group contains any capture placeholders {N}
            group_content = match.group(0)
            if not re.search(r"\{\d+\}", group_content):
                # No capture placeholders - this is a truly optional part, remove it
                template_pattern = (
                    template_pattern[: match.start()] + template_pattern[match.end() :]
                )
            else:
                # Has capture placeholders - keep it for now, will process later
                # Move past this match to avoid infinite loop
                # Replace the match with a temporary marker and continue
                temp_marker = f"__OPTIONAL_GROUP_{match.start()}__"
                template_pattern = (
                    template_pattern[: match.start()]
                    + temp_marker
                    + template_pattern[match.end() :]
                )

        # Third pass: Unwrap non-capturing groups but keep their content
        # Pattern: (?:content) -> content
        while "(?:" in template_pattern:
            # Find (?:...)
            match = re.search(r"\(\?:", template_pattern)
            if not match:
                break

            # Find matching closing paren
            start = match.start()
            depth = 0
            end = start
            for i in range(start, len(template_pattern)):
                if template_pattern[i] == "(":
                    depth += 1
                elif template_pattern[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

            # Extract content between (?:...) and handle alternation
            content = template_pattern[start + 3 : end]  # +3 to skip "(?:"
            # If content contains alternation (pipe), pick first option
            if "|" in content:
                content = content.split("|")[0]  # Take first alternative
            template_pattern = (
                template_pattern[:start] + content + template_pattern[end + 1 :]
            )

        # Restore temporary markers for optional groups with captures
        # (These were preserved because they contain capture placeholders)
        template_pattern = re.sub(r"__OPTIONAL_GROUP_\d+__", "", template_pattern)

        # Fourth pass: Remove regex quantifiers (?, *, +, {n,m})
        # Note: Don't remove single-digit placeholders like {1}, {2}, etc.
        template_pattern = re.sub(r"[?*+]", "", template_pattern)
        # Only remove quantifiers with commas or ranges (e.g., {2,5}, {3,}), not {N}
        template_pattern = re.sub(r"\{[0-9]+,[0-9]*\}", "", template_pattern)

        # Fifth pass: Expand regex shorthand classes and character classes
        # outside capture groups into representative characters.
        # Must preserve capture placeholders {1}, {2}, etc. already in template.
        # Handle quantified forms first (\d{4} -> 0000), then bare forms (\d -> 0).
        template_pattern = re.sub(
            r"\\d\{(\d+)\}", lambda m: "0" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(r"\\d", "0", template_pattern)
        template_pattern = re.sub(
            r"\[0-9\]\{(\d+)\}", lambda m: "0" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(r"\[0-9\]", "0", template_pattern)
        template_pattern = re.sub(
            r"\[A-Z\]\{(\d+)\}", lambda m: "A" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(r"\[A-Z\]", "A", template_pattern)
        template_pattern = re.sub(
            r"\[a-z\]\{(\d+)\}", lambda m: "a" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(r"\[a-z\]", "a", template_pattern)
        template_pattern = re.sub(
            r"\[A-Za-z0-9\]\{(\d+)\}", lambda m: "A" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(
            r"\[A-Za-z\]\{(\d+)\}", lambda m: "A" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(
            r"\\w\{(\d+)\}", lambda m: "a" * int(m.group(1)), template_pattern
        )
        template_pattern = re.sub(r"\\w", "a", template_pattern)
        template_pattern = re.sub(r"\\s", " ", template_pattern)

        # Now substitute the captured values into the template
        filename = template_pattern
        for idx, value in filename_values.items():
            filename = filename.replace(f"{{{idx}}}", str(value))

        # Clean up any remaining unreplaced placeholders (for truly optional fields)
        filename = re.sub(r"_\{\d+\}", "", filename)
        filename = re.sub(r"\{\d+\}_", "", filename)
        filename = re.sub(r"\{\d+\}", "", filename)

        # Add file extension (extracted from pattern, defaults to .txt)
        filename = filename + file_extension

        # Validate generated filename matches the original pattern
        # Use case-insensitive matching since customers aren't consistent with casing
        if filename_pattern:
            pattern_match = re.fullmatch(filename_pattern, filename, re.IGNORECASE)
            if not pattern_match:
                # Log detailed error about the mismatch
                self.logger.error(
                    f"Generated filename '{filename}' for table '{table_name}' "
                    + f"does NOT match the expected pattern: {filename_pattern}"
                )
                # Extract which capture groups were used
                capture_details = []
                for idx_str, col_name_or_meta in captures.items():
                    if isinstance(col_name_or_meta, dict):
                        col_name = col_name_or_meta.get(
                            "column"
                        ) or col_name_or_meta.get("name")
                    else:
                        col_name = col_name_or_meta
                    value = filename_values.get(int(idx_str), "UNKNOWN")
                    capture_details.append(
                        f"  Capture {idx_str} ({col_name}): '{value}'"
                    )

                # Log warning but don't fail - allow generation to continue
                self.logger.warning(
                    f"Filename validation failed for table '{table_name}':\n"
                    + f"  Generated filename: {filename}\n"
                    + f"  Expected pattern:   {filename_pattern}\n"
                    + "  Capture group values:\n"
                    + "\n".join(capture_details)
                    + "\n"
                    + "This usually means sample_values don't match the filename pattern regex. "
                    + "File will be generated but may not match during loading."
                )
            self.logger.debug(
                f"Generated filename '{filename}' matches pattern {filename_pattern}"
            )

        self.logger.info(f"Generated filename for {table_name}: {filename}")
        return filename

        # Fallback to simple naming
        return f"{table_name}.txt"
