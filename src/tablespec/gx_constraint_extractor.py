"""Great Expectations Constraint Extractor for Phase 5 data generation.

This module extracts enumerated value constraints from GX expectation suites
to generate valid data without hard-coding domain values.
"""

import logging
import random
import re
from pathlib import Path
from typing import Any

import yaml

from tablespec.format_utils import convert_umf_format_to_strftime


class GXConstraintExtractor:
    """Extracts enumerated value constraints from GX expectation suites."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def load_expectations_for_table(
        self, table_name: str, relationships_dir: Path
    ) -> dict[str, Any] | None:
        """Load GX YAML expectation suite for a table.

        Tries to load from UMF validation rules first, then falls back to
        standalone expectation suite files.

        Args:
            table_name: Name of the table
            relationships_dir: Directory containing Phase 4/5 output with expectation suites

        Returns:
            Parsed YAML expectation suite, or None if not found

        """
        # Try UMF-based validation rules first
        umf_file = relationships_dir / "tables" / f"{table_name}.umf.yaml"
        if umf_file.exists():
            try:
                from tablespec.umf_loader import UMFLoader

                loader = UMFLoader()
                umf = loader.load(umf_file)
                umf_data = umf.model_dump()

                # Extract validation rules from UMF
                validation_rules = umf_data.get("validation_rules", {})
                expectations = validation_rules.get("expectations", [])

                if expectations:
                    return {
                        "name": f"{table_name}_suite",
                        "expectations": expectations,
                    }
            except ImportError:
                self.logger.debug("UMFLoader not available, trying YAML fallback")
            except Exception as e:
                self.logger.warning(f"Failed to load UMF for {table_name}: {e}")

        # Fallback to standalone expectations file
        expectations_file = (
            relationships_dir / "tables" / f"{table_name}.expectations.yaml"
        )

        if not expectations_file.exists():
            self.logger.debug(f"No GX expectations found for {table_name}")
            return None

        try:
            with expectations_file.open() as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load GX expectations for {table_name}: {e}")
            return None

    def extract_value_sets(self, expectations: dict[str, Any]) -> dict[str, list[str]]:
        """Extract column -> value_set mappings from expect_column_values_to_be_in_set.

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            Dictionary mapping column names to allowed value lists

        """
        value_sets = {}

        if not expectations or "expectations" not in expectations:
            return value_sets

        for expectation in expectations["expectations"]:
            if expectation.get("type") == "expect_column_values_to_be_in_set":
                kwargs = expectation.get("kwargs", {})
                column = kwargs.get("column")
                value_set = kwargs.get("value_set", [])

                if column and value_set:
                    # Convert all values to strings for consistency
                    value_sets[column] = [str(v) for v in value_set]

        return value_sets

    def extract_metadata_hints(
        self, expectations: dict[str, Any]
    ) -> dict[str, dict[str, list[str]]]:
        """Extract hints from expectation metadata as fallback constraints.

        Looks for metadata fields like `meta.lob`, `meta.states`, etc. that
        document allowed values but aren't in formal value_set constraints.

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            Dictionary mapping column names to metadata hints

        """
        metadata_hints = {}

        if not expectations or "expectations" not in expectations:
            return metadata_hints

        for expectation in expectations["expectations"]:
            kwargs = expectation.get("kwargs", {})
            column = kwargs.get("column")
            meta = expectation.get("meta", {})

            if not column:
                continue

            # Extract common metadata hint patterns
            hints = {}

            # Check for LOB values in metadata
            if "lob" in meta and isinstance(meta["lob"], list):
                hints["lob"] = [str(v) for v in meta["lob"]]

            # Check for state codes in metadata
            if "states" in meta and isinstance(meta["states"], list):
                hints["states"] = [str(v) for v in meta["states"]]

            # Check description for examples like "Ex: MD, ME, MP"
            description = meta.get("description", "")
            if description:
                hints["description_examples"] = self._extract_examples_from_description(
                    description
                )

            if hints:
                if column not in metadata_hints:
                    metadata_hints[column] = {}
                metadata_hints[column].update(hints)

        return metadata_hints

    def _extract_examples_from_description(self, description: str) -> list[str]:
        """Extract example values from description text.

        Looks for patterns like "Ex: MD, ME, MP" or "Example: A, B, C".

        Args:
            description: Description text from GX expectation

        Returns:
            List of extracted example values

        """
        examples = []

        # Look for "Ex:" or "Example:" patterns
        if "Ex:" in description or "Example:" in description:
            # Extract the part after "Ex:" or "Example:"
            parts = description.split("Ex:")
            if len(parts) < 2:
                parts = description.split("Example:")

            if len(parts) >= 2:
                example_text = parts[1].split(".")[0].strip()  # Get first sentence
                # Split by commas and clean up
                values = [v.strip() for v in example_text.split(",")]
                examples.extend(
                    [v for v in values if v and len(v) <= 50]
                )  # Sanity check

        return examples

    def get_constraints_for_column(
        self, expectations: dict[str, Any], column_name: str
    ) -> list[str] | None:
        """Get all available constraints for a specific column.

        Only uses formal expect_column_values_to_be_in_set constraints.
        Does NOT use metadata hints (meta.lob, meta.states) as these indicate
        which LOBs/states the rule applies to, not valid column values.

        Args:
            expectations: Parsed GX expectation suite YAML
            column_name: Name of the column

        Returns:
            List of allowed values from value_set constraints, or None if not found

        """
        # Only use formal value_set constraints
        value_sets = self.extract_value_sets(expectations)
        if column_name in value_sets:
            # Filter out obvious column names/placeholders
            filtered_values = [
                v
                for v in value_sets[column_name]
                if not self._looks_like_column_name(v)
            ]
            if filtered_values:
                return filtered_values

        return None

    def _looks_like_column_name(self, value: str) -> bool:
        """Check if a value looks like a column name or placeholder.

        Args:
            value: Value to check

        Returns:
            True if value appears to be a column name, not actual data

        """
        if not value or len(value.strip()) == 0:
            return True

        # Common patterns that indicate column names
        suspicious_patterns = [
            "CLIENT MBRID",
            "MEMBER_ID",
            "FIRST NAME",
            "LAST NAME",
            "MemberLastName",
            "MemberFirstName",
            "CHASE LOAD DATE",
            "LOAD DATE",
            "DATE",
        ]

        # Check for exact matches (case-insensitive)
        if value.upper() in [p.upper() for p in suspicious_patterns]:
            return True

        # Check if value contains common column name suffixes/patterns
        # This is more specific than just "uppercase with underscores"
        # to avoid filtering out valid enum values like "PENNSYLVANIA_MEDICARE"
        column_keywords = [
            "_ID",
            "_KEY",
            "_NBR",
            "_NUM",
            "_NUMBER",
            "_DATE",
            "_DT",
            "_TIME",
            "_DATETIME",
            "_TIMESTAMP",
            "_NAME",
            "_DESC",
            "_CODE",
            "_FLAG",
            "_IND",
            "_ADDR",
            "_ADDRESS",
            "_PHONE",
            "_EMAIL",
            "_AMT",
            "_AMOUNT",
            "_COST",
            "_PRICE",
            "_QTY",
            "_QUANTITY",
            "_COUNT",
            "_CNT",
            "MEMBER_",
            "CLIENT_",
            "PATIENT_",
            "PROVIDER_",
        ]

        # If value is uppercase with underscores AND contains column keywords,
        # it's likely a column name
        if "_" in value and value.upper() == value:
            for keyword in column_keywords:
                if keyword in value.upper():
                    return True

        return False

    def extract_regex_patterns(self, expectations: dict[str, Any]) -> dict[str, str]:
        """Extract column -> regex pattern mappings from expect_column_values_to_match_regex.

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            Dictionary mapping column names to regex patterns

        """
        regex_patterns = {}

        if not expectations or "expectations" not in expectations:
            return regex_patterns

        for expectation in expectations["expectations"]:
            if expectation.get("type") == "expect_column_values_to_match_regex":
                kwargs = expectation.get("kwargs", {})
                column = kwargs.get("column")
                regex = kwargs.get("regex")

                if column and regex:
                    regex_patterns[column] = regex

        return regex_patterns

    def get_regex_for_column(
        self, expectations: dict[str, Any], column_name: str
    ) -> str | None:
        """Get regex pattern for a specific column.

        Args:
            expectations: Parsed GX expectation suite YAML
            column_name: Name of the column

        Returns:
            Regex pattern string, or None if not found

        """
        regex_patterns = self.extract_regex_patterns(expectations)
        return regex_patterns.get(column_name)

    def extract_strftime_formats(self, expectations: dict[str, Any]) -> dict[str, str]:
        """Extract column -> strftime format mappings from validation expectations.

        Checks both expect_column_values_to_match_strftime_format and
        expect_column_values_to_cast_to_type (which has UMF format in kwargs).

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            Dictionary mapping column names to strftime format strings

        """
        strftime_formats: dict[str, str] = {}

        if not expectations or "expectations" not in expectations:
            return strftime_formats

        for expectation in expectations["expectations"]:
            exp_type = expectation.get("type")
            kwargs = expectation.get("kwargs", {})
            column = kwargs.get("column")

            if exp_type == "expect_column_values_to_match_strftime_format":
                strftime_format = kwargs.get("strftime_format")
                if column and strftime_format:
                    strftime_formats[column] = strftime_format

            elif exp_type == "expect_column_values_to_cast_to_type":
                # Also extract format from cast_to_type expectations (UMF format)
                umf_format = kwargs.get("format")
                if column and umf_format and column not in strftime_formats:
                    strftime_format = self._convert_umf_format_to_strftime(umf_format)
                    if strftime_format:
                        strftime_formats[column] = strftime_format

        return strftime_formats

    def _convert_umf_format_to_strftime(self, umf_format: str) -> str:
        """Convert UMF date format to Python strftime format.

        Uses the centralized format_utils for conversion.

        Args:
            umf_format: UMF format string (e.g., "YYYY-MM-DD HH:MM:SS")

        Returns:
            Python strftime format string (e.g., "%Y-%m-%d %H:%M:%S")

        """
        result = convert_umf_format_to_strftime(umf_format)
        return result if result else umf_format

    def get_strftime_format_for_column(
        self, expectations: dict[str, Any], column_name: str
    ) -> str | None:
        """Get strftime format for a specific column.

        Args:
            expectations: Parsed GX expectation suite YAML
            column_name: Name of the column

        Returns:
            Strftime format string, or None if not found

        """
        strftime_formats = self.extract_strftime_formats(expectations)
        fmt = strftime_formats.get(column_name)
        if fmt:
            # Fix invalid strftime formats that contain residual UMF patterns
            fmt = self._fix_strftime_format(fmt)
        return fmt

    def _fix_strftime_format(self, fmt: str) -> str:
        """Fix strftime format strings that may contain invalid UMF patterns.

        Some stored GX expectations have strftime_format values that were not
        properly converted from UMF format (e.g., "M/D/%Y" instead of "%-m/%-d/%Y").
        This method fixes those patterns.

        Args:
            fmt: The strftime format string to fix

        Returns:
            Corrected strftime format string

        """
        # Fix standalone M (month without zero padding) not part of %m
        # (?<!%) ensures we don't match after % (already valid strftime)
        # (?![A-Za-z]) ensures we don't match if followed by letters
        result = re.sub(r"(?<!%)(?<![A-Za-z])M(?![A-Za-z])", "%-m", fmt)
        # Fix standalone D (day without zero padding, uppercase) not part of %d
        result = re.sub(r"(?<!%)(?<![A-Za-z])D(?![A-Za-z])", "%-d", result)
        # Fix standalone d (day without zero padding, lowercase) not part of %d
        result = re.sub(r"(?<!%)(?<!%-)(?<![A-Za-z])d(?![A-Za-z])", "%-d", result)
        # Fix standalone h (12-hour without zero padding) not part of %I
        return re.sub(r"(?<!%)(?<!%-)(?<![A-Za-z])h(?![A-Za-z])", "%-I", result)

    def is_column_not_null(
        self, expectations: dict[str, Any], column_name: str
    ) -> bool:
        """Check if a column has a not-null expectation.

        Args:
            expectations: Parsed GX expectation suite YAML
            column_name: Name of the column

        Returns:
            True if column has expect_column_values_to_not_be_null, False otherwise

        """
        if not expectations or "expectations" not in expectations:
            return False

        for expectation in expectations["expectations"]:
            if expectation.get("type") == "expect_column_values_to_not_be_null":
                kwargs = expectation.get("kwargs", {})
                if kwargs.get("column") == column_name:
                    return True

        return False

    def get_max_length_for_column(
        self, expectations: dict[str, Any], column_name: str
    ) -> int | None:
        """Get max_length expectation for a column.

        Args:
            expectations: Parsed GX expectation suite YAML
            column_name: Name of the column

        Returns:
            Maximum length if found, None otherwise

        """
        if not expectations or "expectations" not in expectations:
            return None

        for expectation in expectations["expectations"]:
            if expectation.get("type") == "expect_column_value_lengths_to_be_between":
                kwargs = expectation.get("kwargs", {})
                if kwargs.get("column") == column_name:
                    max_value = kwargs.get("max_value")
                    if max_value is not None:
                        return int(max_value)
                    return None

        return None

    def generate_value_from_regex(self, regex_pattern: str) -> str:
        r"""Generate a sample value that matches the given regex pattern.

        Supports common regex patterns used in healthcare data:
        - ^[A-Z]{n}$ - n uppercase letters
        - ^\d{n}$ - n digits
        - ^[A-Z]{n}\d{m}$ - n letters followed by m digits
        - Character classes like [A-Za-z], [0-9], etc.
        - + quantifier (one or more)
        - ? quantifier (zero or one)
        - \. for literal dot
        - Top-level alternation (A|B|C)

        Args:
            regex_pattern: Regex pattern to match

        Returns:
            Generated value matching the pattern

        """
        # Handle top-level alternation BEFORE stripping anchors
        # Split on | that are not inside groups, then choose one alternative
        alternatives = self._split_alternation(regex_pattern)
        if len(alternatives) > 1:
            # Choose one alternative randomly (excluding empty alternatives like ^$)
            non_empty = [alt for alt in alternatives if alt.strip("^$")]
            if non_empty:
                regex_pattern = random.choice(non_empty)
            else:
                # All alternatives are empty (like ^$) - return empty string
                return ""

        # Remove anchors for processing - only strip ^ from start and $ from end
        pattern = regex_pattern
        pattern = pattern.removeprefix("^")
        pattern = pattern.removesuffix("$")

        result = []
        i = 0

        while i < len(pattern):
            # Handle escaped characters like \. (literal dot)
            if i + 1 < len(pattern) and pattern[i] == "\\":
                next_char = pattern[i + 1]
                if next_char == ".":
                    result.append(".")
                    i += 2
                    continue
                # \d is handled below

            # Handle character classes like [A-Z], [0-9], [A-Za-z0-9]
            if pattern[i] == "[":
                end_bracket = pattern.find("]", i)
                if end_bracket == -1:
                    # Malformed pattern, skip
                    i += 1
                    continue

                char_class = pattern[i + 1 : end_bracket]

                # Check for quantifiers after the bracket
                repetition = 1
                next_pos = end_bracket + 1

                if next_pos < len(pattern):
                    if pattern[next_pos] == "{":
                        # {n}, {n,}, or {n,m} quantifier
                        end_brace = pattern.find("}", next_pos)
                        if end_brace != -1:
                            quant_str = pattern[next_pos + 1 : end_brace]
                            try:
                                if "," in quant_str:
                                    parts = quant_str.split(",")
                                    min_val = int(parts[0])
                                    # {n,} means n or more, {n,m} means n to m
                                    if len(parts) > 1 and parts[1].strip():
                                        max_val = int(parts[1])
                                        repetition = random.randint(min_val, max_val)
                                    else:
                                        # {n,} - generate between n and n+5
                                        repetition = random.randint(
                                            min_val, min_val + 5
                                        )
                                else:
                                    repetition = int(quant_str)
                                i = end_brace + 1
                            except ValueError:
                                i = next_pos
                        else:
                            i = next_pos
                    elif pattern[next_pos] == "+":
                        # + quantifier: one or more (generate 3-10)
                        repetition = random.randint(3, 10)
                        i = next_pos + 1
                    elif pattern[next_pos] == "?":
                        # ? quantifier: zero or one
                        repetition = random.choice([0, 1])
                        i = next_pos + 1
                    else:
                        i = next_pos
                else:
                    i = next_pos

                # Generate characters matching the class
                for _ in range(repetition):
                    result.append(self._generate_char_from_class(char_class))

            # Handle shorthand \d for digits
            elif pattern[i : i + 2] == r"\d":
                # Check for quantifiers
                repetition = 1
                next_pos = i + 2

                if next_pos < len(pattern):
                    if pattern[next_pos] == "{":
                        # {n}, {n,}, or {n,m} quantifier
                        end_brace = pattern.find("}", next_pos)
                        if end_brace != -1:
                            quant_str = pattern[next_pos + 1 : end_brace]
                            try:
                                if "," in quant_str:
                                    parts = quant_str.split(",")
                                    min_val = int(parts[0])
                                    if len(parts) > 1 and parts[1].strip():
                                        max_val = int(parts[1])
                                        repetition = random.randint(min_val, max_val)
                                    else:
                                        repetition = random.randint(
                                            min_val, min_val + 5
                                        )
                                else:
                                    repetition = int(quant_str)
                                i = end_brace + 1
                            except ValueError:
                                i = next_pos
                        else:
                            i = next_pos
                    elif pattern[next_pos] == "+":
                        # + quantifier: one or more
                        repetition = random.randint(3, 10)
                        i = next_pos + 1
                    elif pattern[next_pos] == "?":
                        # ? quantifier: zero or one
                        repetition = random.choice([0, 1])
                        i = next_pos + 1
                    else:
                        i = next_pos
                else:
                    i = next_pos

                for _ in range(repetition):
                    result.append(str(random.randint(0, 9)))

            # Handle parentheses groups (capturing and non-capturing)
            elif pattern[i] == "(":
                end_paren = self._find_matching_paren(pattern, i)
                if end_paren != -1:
                    # Check for non-capturing group (?:...) or other special groups
                    group_start = i + 1
                    if i + 2 < end_paren and pattern[i + 1 : i + 3] == "?:":
                        # Non-capturing group - skip the "?:" prefix
                        group_start = i + 3
                    elif i + 1 < end_paren and pattern[i + 1] == "?":
                        # Other special groups (lookahead, lookbehind, etc.)
                        # Skip the entire group for now as we don't support these
                        i = end_paren + 1
                        continue

                    group_content = pattern[group_start:end_paren]

                    # Handle alternation (A|B|C) - split and choose one randomly
                    # Only split on | that are not inside nested groups
                    alternatives = self._split_alternation(group_content)
                    if len(alternatives) > 1:
                        # Choose one alternative randomly
                        group_content = random.choice(alternatives)

                    group_result = self.generate_value_from_regex(group_content)

                    # Check for quantifier after the group
                    next_pos = end_paren + 1
                    repetition = 1

                    if next_pos < len(pattern):
                        if pattern[next_pos] == "+":
                            repetition = random.randint(1, 3)
                            i = next_pos + 1
                        elif pattern[next_pos] == "?":
                            repetition = random.choice([0, 1])
                            i = next_pos + 1
                        else:
                            i = next_pos
                    else:
                        i = next_pos

                    for _ in range(repetition):
                        result.append(group_result)
                else:
                    i += 1

            # Skip unhandled regex metacharacters (but not | - handled in groups)
            elif pattern[i] in ".*":
                i += 1

            else:
                # Literal character
                result.append(pattern[i])
                i += 1

        return "".join(result)

    def _find_matching_paren(self, pattern: str, start: int) -> int:
        """Find the index of the closing parenthesis matching the opening one at start.

        Args:
            pattern: The regex pattern string
            start: Index of the opening parenthesis

        Returns:
            Index of matching closing parenthesis, or -1 if not found

        """
        if start >= len(pattern) or pattern[start] != "(":
            return -1

        depth = 0
        for i in range(start, len(pattern)):
            if pattern[i] == "(":
                depth += 1
            elif pattern[i] == ")":
                depth -= 1
                if depth == 0:
                    return i

        return -1

    def _split_alternation(self, pattern: str) -> list[str]:
        """Split pattern on | (alternation) while respecting nested groups.

        Args:
            pattern: The regex pattern to split

        Returns:
            List of alternatives (single item if no alternation)

        """
        alternatives = []
        current = []
        depth = 0

        for char in pattern:
            if char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth -= 1
                current.append(char)
            elif char == "|" and depth == 0:
                # Top-level alternation - split here
                alternatives.append("".join(current))
                current = []
            else:
                current.append(char)

        # Add the last alternative
        if current:
            alternatives.append("".join(current))

        return alternatives if alternatives else [pattern]

    def _generate_char_from_class(self, char_class: str) -> str:
        """Generate a random character from a character class.

        Args:
            char_class: Character class specification (e.g., "A-Z", "0-9", "A-Za-z")

        Returns:
            Random character matching the class

        """
        import string

        # Handle ranges like A-Z, a-z, 0-9
        if "A-Z" in char_class:
            return random.choice(string.ascii_uppercase)
        if "a-z" in char_class:
            return random.choice(string.ascii_lowercase)
        if "0-9" in char_class:
            return str(random.randint(0, 9))

        # Handle combined classes
        chars = []
        if "A-Z" in char_class or "a-z" in char_class:
            chars.extend(string.ascii_letters)
        if "0-9" in char_class:
            chars.extend(string.digits)

        if chars:
            return random.choice(chars)

        # Fallback to literal characters in the class
        return random.choice(char_class) if char_class else "X"

    def extract_column_pair_equality_constraints(
        self, expectations: dict[str, Any]
    ) -> dict[str, list[dict[str, str]]]:
        """Extract expect_column_pair_values_to_be_equal constraints.

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            Dictionary mapping column_A to list of equality constraints:
            {
                'column_A': [
                    {'column_B': 'other_col', 'ignore_row_if': 'either_value_is_missing'},
                    ...
                ],
                ...
            }

        """
        equality_constraints: dict[str, list[dict[str, str]]] = {}

        if not expectations or "expectations" not in expectations:
            return equality_constraints

        for expectation in expectations["expectations"]:
            if expectation.get("type") == "expect_column_pair_values_to_be_equal":
                kwargs = expectation.get("kwargs", {})
                column_a = kwargs.get("column_A")
                column_b = kwargs.get("column_B")
                ignore_row_if = kwargs.get("ignore_row_if", "never")

                if column_a and column_b:
                    # Store bidirectional mapping for easier lookup
                    constraint = {"column_B": column_b, "ignore_row_if": ignore_row_if}
                    if column_a not in equality_constraints:
                        equality_constraints[column_a] = []
                    equality_constraints[column_a].append(constraint)

                    # Also add reverse mapping
                    reverse_constraint = {
                        "column_B": column_a,
                        "ignore_row_if": ignore_row_if,
                    }
                    if column_b not in equality_constraints:
                        equality_constraints[column_b] = []
                    equality_constraints[column_b].append(reverse_constraint)

        return equality_constraints

    def extract_unique_within_record_constraints(
        self, expectations: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Extract expect_select_column_values_to_be_unique_within_record constraints.

        Args:
            expectations: Parsed GX expectation suite YAML

        Returns:
            List of unique-within-record constraints:
            [
                {'columns': ['col1', 'col2'], 'ignore_row_if': 'any_value_is_missing'},
                ...
            ]

        """
        unique_constraints = []

        if not expectations or "expectations" not in expectations:
            return unique_constraints

        for expectation in expectations["expectations"]:
            if (
                expectation.get("type")
                == "expect_select_column_values_to_be_unique_within_record"
            ):
                kwargs = expectation.get("kwargs", {})
                column_list = kwargs.get("column_list", [])
                ignore_row_if = kwargs.get("ignore_row_if", "never")

                if column_list and len(column_list) >= 2:
                    unique_constraints.append(
                        {"columns": column_list, "ignore_row_if": ignore_row_if}
                    )

        return unique_constraints
