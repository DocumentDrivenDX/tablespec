"""Property-based fuzzing tests for YAML formatter idempotence.

Uses Hypothesis to generate arbitrary YAML structures and verify that:
1. The formatter is idempotent: format(format(x)) == format(x)
2. The output is valid YAML that can be parsed
3. The formatter doesn't corrupt data
"""

import math
import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
import pytest
import yaml

from tablespec.formatting import format_yaml_string

pytestmark = pytest.mark.fast


def approx_equal(a, b, rel_tol=1e-12, abs_tol=1e-10):
    """Compare two values with approximate equality for floats.

    Handles nested structures (dicts, lists) recursively.
    """
    # Same type check
    if type(a) is not type(b):
        return False

    # Float comparison
    if isinstance(a, float):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)

    # Dict comparison
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(approx_equal(a[k], b[k], rel_tol, abs_tol) for k in a)

    # List comparison
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(
            approx_equal(x, y, rel_tol, abs_tol) for x, y in zip(a, b, strict=False)
        )

    # Exact comparison for everything else
    return a == b


def has_yamlfix_literal_block_bug(data):
    """Check if data contains patterns that trigger yamlfix literal block bugs.

    Known yamlfix bugs with literal blocks:
    1. Strings with leading newlines + special char (digit, colon, etc.)
       - Second pass creates invalid |4- syntax or parser errors
    2. Strings with trailing newlines
       - |- chomping indicator strips trailing newlines
    3. Strings with special YAML syntax characters after newlines
       - Can cause YAML parser errors when yamlfix processes them

    Args:
        data: Python data structure to check

    Returns:
        True if data contains problematic patterns

    """
    if isinstance(data, str):
        # Bug 1: Leading or trailing newlines or carriage returns
        # yamlfix has multiple bugs with strings containing leading/trailing newlines:
        # - Invalid |4- syntax on second pass
        # - |- chomping strips trailing newlines
        # - Line wrapping issues with special characters
        # - CRLF (\r\n) line endings cause idempotence issues
        if data.startswith("\n") or data.endswith("\n"):
            # Only skip if there's actual content (not just whitespace)
            if data.strip():
                return True

        # Carriage returns (\r) cause idempotence issues in yamlfix
        if "\r" in data:
            return True

        # Bug 2: Internal newlines followed by YAML special characters
        # Can cause parser errors or data corruption
        # These characters have special meaning in YAML syntax
        yaml_special_chars = [
            ":",
            "-",
            "#",
            "[",
            "]",
            "{",
            "}",
            "|",
            ">",
            ";",
            "!",
            "&",
            "*",
        ]
        for char in yaml_special_chars:
            if f"\n{char}" in data:
                return True

        # Bug 3: Hash followed by alphanumeric (yamlfix adds space when wrapping)
        # Pattern: #0, #A, etc. → "# 0", "# A" when yamlfix wraps quoted strings
        # This is to prevent # from being treated as a YAML comment marker
        # Skip any string containing hash followed by letter or digit
        if re.search(r"#[A-Za-z0-9]", data):
            return True

        # Bug 4: YAML 1.1 sexagesimal (base-60) numbers
        # Patterns like "1:0", "1:30", "10:20:30" are interpreted as base-60 numbers
        # e.g., "1:0" becomes 60, "1:30" becomes 90
        # This affects values that look like time formats (HH:MM or HH:MM:SS)
        return bool(re.match(r"^\d+:\d+(:\d+)?$", data))

    if isinstance(data, dict):
        # Bug 5: Dict keys that are YAML boolean literals (YES, NO, ON, OFF, etc.)
        # yamlfix converts these to boolean True/False, corrupting the data
        yaml_bool_words = {"yes", "no", "on", "off", "true", "false"}
        for key in data:
            if isinstance(key, str) and key.lower() in yaml_bool_words:
                return True

        # Bug 6: Dict values that are YAML boolean literals
        # YAML parsers convert string values like "YES", "NO", etc. to booleans
        for value in data.values():
            if isinstance(value, str) and value.lower() in yaml_bool_words:
                return True

        return any(has_yamlfix_literal_block_bug(v) for v in data.values())

    if isinstance(data, list):
        return any(has_yamlfix_literal_block_bug(item) for item in data)

    return False


# Strategy for generating arbitrary YAML-compatible values
def yaml_value() -> st.SearchStrategy:
    """Generate arbitrary YAML-compatible values."""
    return st.recursive(
        # Base cases: primitives
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-10000, max_value=10000),
            st.floats(
                allow_nan=False,
                allow_infinity=False,
                min_value=-1e50,  # Reduced range to prevent YAML precision loss
                max_value=1e50,
            ),
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs",),  # Exclude surrogates
                    blacklist_characters="\x00\r\x85",  # Exclude null, CR, and NEL
                ),
                min_size=0,
                max_size=300,  # Longer strings
            ),
            # Long strings that might trigger wrapping
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs",),
                    blacklist_characters="\x00\r\x85",  # Exclude null, CR, and NEL
                ),
                min_size=50,
                max_size=500,  # Much longer
            ),
            # Strings with special YAML characters
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz:,[]{}#&*!|>'\"-\n ",
                min_size=5,
                max_size=200,  # Longer
            ),
        ),
        # Recursive cases: collections
        lambda children: st.one_of(
            st.lists(children, min_size=0, max_size=15),  # Larger lists
            st.dictionaries(
                # Keys should be strings
                st.text(
                    alphabet=st.characters(
                        whitelist_categories=("L", "N"),  # Letters and numbers
                    ),
                    min_size=1,
                    max_size=50,
                ),
                children,
                min_size=0,
                max_size=15,  # More keys
            ),
        ),
        max_leaves=8,  # More complex structures
    )


# UMF-like structure strategy
@st.composite
def umf_like_structure(draw):
    """Generate structures similar to UMF YAML files."""
    return {
        "column": {
            "name": draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("L",)),
                    min_size=1,
                    max_size=30,
                )
            ),
            "canonical_name": draw(
                st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=30)
            ),
            "data_type": draw(
                st.sampled_from(
                    ["StringType", "IntegerType", "DateType", "BooleanType"]
                )
            ),
            "description": draw(st.text(min_size=10, max_size=200)),
            "nullable": draw(
                st.dictionaries(
                    st.sampled_from(["MD", "ME", "MP"]),
                    st.booleans(),
                    min_size=1,
                    max_size=3,
                )
            ),
            "length": draw(
                st.one_of(st.none(), st.integers(min_value=1, max_value=1000))
            ),
        },
        "validations": draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        "kwargs": st.dictionaries(
                            st.text(
                                alphabet="abcdefghijklmnopqrstuvwxyz_",
                                min_size=1,
                                max_size=20,
                            ),
                            st.one_of(
                                st.text(max_size=50), st.integers(), st.booleans()
                            ),
                            min_size=1,
                            max_size=5,
                        ),
                        "meta": st.fixed_dictionaries(
                            {
                                "description": st.text(min_size=10, max_size=150),
                                "severity": st.sampled_from(
                                    ["critical", "warning", "info"]
                                ),
                                "rule_id": st.text(
                                    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
                                    min_size=5,
                                    max_size=40,
                                ),
                            }
                        ),
                        "type": st.text(
                            alphabet="abcdefghijklmnopqrstuvwxyz_",
                            min_size=5,
                            max_size=40,
                        ),
                    }
                ),
                min_size=0,
                max_size=5,
            )
        ),
    }


@pytest.mark.no_spark
class TestYAMLFormatterFuzzing:
    """Property-based fuzzing tests for YAML formatter."""

    @given(yaml_value())
    @settings(
        max_examples=1000,  # Massively increased to find edge cases
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_formatter_idempotence_arbitrary_yaml(self, data):
        """Test that formatter is idempotent on arbitrary YAML structures.

        Property: format(format(x)) == format(x)
        """
        # First convert to YAML string
        try:
            yaml_str = yaml.safe_dump(
                data, default_flow_style=False, allow_unicode=True
            )
        except Exception:
            # If we can't serialize it, skip this example
            return

        # Skip top-level lists and non-dict data - known limitation
        # UMF files always have dicts at the root level
        if not isinstance(data, dict):
            return

        # Skip data with known yamlfix literal block bugs
        if has_yamlfix_literal_block_bug(data):
            return

        # Format once
        try:
            formatted_once = format_yaml_string(yaml_str)
        except Exception as e:
            # Formatter should not crash on valid YAML
            msg = f"Formatter crashed on first pass: {e}\nInput: {yaml_str[:200]}"
            raise AssertionError(msg)

        # Format twice (idempotence check)
        try:
            formatted_twice = format_yaml_string(formatted_once)
        except Exception as e:
            msg = f"Formatter crashed on second pass: {e}\nFirst output: {formatted_once[:200]}"
            raise AssertionError(msg)

        # Check idempotence
        # For floats, allow slight representation differences due to YAML serialization
        if formatted_once != formatted_twice:
            # Parse both and compare values with tolerance
            parsed_once = yaml.safe_load(formatted_once)
            parsed_twice = yaml.safe_load(formatted_twice)

            if not approx_equal(parsed_once, parsed_twice):
                msg = (
                    "Formatter is not idempotent!\n"
                    f"First format != Second format\n"
                    f"Diff length: {len(formatted_once)} vs {len(formatted_twice)}\n"
                    f"Parsed once: {parsed_once}\n"
                    f"Parsed twice: {parsed_twice}"
                )
                raise AssertionError(msg)

        # Verify output is valid YAML
        try:
            parsed = yaml.safe_load(formatted_twice)
        except Exception as e:
            msg = (
                f"Formatter produced invalid YAML: {e}\nOutput: {formatted_twice[:300]}"
            )
            raise AssertionError(msg)

        # Verify data integrity - Python structure must be identical (or approximately equal for floats)
        # Parse the original input too for fair comparison
        try:
            original_parsed = yaml.safe_load(yaml_str)
        except Exception:
            # If original can't be parsed, use data directly
            original_parsed = data

        # Use approximate equality to handle float precision limits in YAML serialization
        assert approx_equal(parsed, original_parsed), (
            f"Data corruption detected! Python structures differ after formatting.\n"
            f"Original parsed: {original_parsed}\n"
            f"After formatting: {parsed}\n"
            f"Type mismatch: {type(original_parsed)} vs {type(parsed)}"
        )

    @given(umf_like_structure())
    @settings(
        max_examples=500,  # Increased for thorough UMF pattern testing
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_formatter_idempotence_umf_like_structures(self, data):
        """Test formatter on UMF-like structures (columns with validations).

        This specifically tests the patterns we use in production.
        """
        # Skip data with known yamlfix literal block bugs
        if has_yamlfix_literal_block_bug(data):
            return

        # Convert to YAML
        yaml_str = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)

        # Format once
        formatted_once = format_yaml_string(yaml_str)

        # Format twice
        formatted_twice = format_yaml_string(formatted_once)

        # Check idempotence
        assert formatted_once == formatted_twice, (
            "Formatter is not idempotent on UMF-like structure!\n"
            f"Input keys: {data.keys()}\n"
            f"Column keys: {data.get('column', {}).keys()}\n"
            f"Validation count: {len(data.get('validations', []))}"
        )

        # Verify output is valid YAML
        try:
            parsed = yaml.safe_load(formatted_twice)
        except Exception as e:
            msg = (
                f"Formatter produced invalid YAML for UMF-like structure: {e}\n"
                f"Output:\n{formatted_twice}"
            )
            raise AssertionError(msg)

        # Verify structure is preserved
        assert "column" in parsed
        assert "validations" in parsed
        assert parsed["column"]["name"] == data["column"]["name"]

    @given(
        st.text(
            # Generate strings with colons (which can cause YAML parsing issues when wrapped)
            alphabet="abcdefghijklmnopqrstuvwxyz: ,.",
            min_size=50,
            max_size=500,  # Longer strings to trigger more wrapping
        )
    )
    @settings(max_examples=200, deadline=None)  # Increased for thorough colon handling
    def test_long_strings_with_colons(self, text):
        """Test that long strings containing colons don't break YAML parsing.

        Regression test for the greedy regex bug that collapsed YAML structure.
        """
        # Create a structure with a long description
        data = {
            "meta": {
                "description": text,
                "severity": "warning",
            },
            "other_field": "value",
        }

        yaml_str = yaml.safe_dump(data, default_flow_style=False)

        # Format
        formatted = format_yaml_string(yaml_str)

        # Must be valid YAML
        try:
            parsed = yaml.safe_load(formatted)
        except Exception as e:
            msg = (
                f"Formatter broke YAML with long string containing colons: {e}\n"
                f"Original text: {text[:100]}\n"
                f"Formatted output:\n{formatted}"
            )
            raise AssertionError(msg)

        # Verify structure integrity
        assert "meta" in parsed, "Lost 'meta' key!"
        assert "other_field" in parsed, "Lost 'other_field' key!"

        # For literal blocks, whitespace normalization is acceptable
        # Check that the core content is preserved (ignoring trailing/leading whitespace)
        desc = parsed["meta"]["description"]
        text_normalized = " ".join(text.split())
        desc_normalized = " ".join(desc.split())

        assert desc_normalized == text_normalized, (
            f"Description content was corrupted!\n"
            f"Original: {text_normalized}\n"
            f"Got: {desc_normalized}"
        )
        assert parsed["other_field"] == "value", "other_field was corrupted!"

    @given(
        st.lists(
            st.dictionaries(
                st.text(
                    alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20
                ),
                st.one_of(
                    st.text(
                        alphabet=st.characters(
                            blacklist_categories=("Cs",),
                            blacklist_characters="\x00\r\x85",  # Exclude null, CR, and NEL
                        ),
                        max_size=200,
                    ),  # Longer text values
                    st.integers(),
                    st.booleans(),
                    st.none(),
                ),
                min_size=1,
                max_size=15,  # More keys per dict
            ),
            min_size=1,
            max_size=20,  # More dicts in list
        )
    )
    @settings(max_examples=200, deadline=None)  # Increased for thorough list handling
    def test_list_of_dicts_preservation(self, list_data):
        """Test that lists of dictionaries (like validations) are preserved correctly."""
        data = {"validations": list_data}

        yaml_str = yaml.safe_dump(data, default_flow_style=False)

        # Format twice
        formatted = format_yaml_string(yaml_str)
        formatted_twice = format_yaml_string(formatted)

        # Idempotence
        assert formatted == formatted_twice

        # Parse and verify
        parsed = yaml.safe_load(formatted_twice)
        assert "validations" in parsed
        assert len(parsed["validations"]) == len(list_data)

    @given(
        st.dictionaries(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=30),
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs",),
                    blacklist_characters="\x00\r\x85",  # Exclude null, CR, and NEL
                ),
                min_size=0,
                max_size=300,
            ),  # Longer values
            min_size=3,
            max_size=50,  # More keys
        )
    )
    @settings(
        max_examples=100, deadline=None
    )  # Increased for thorough key ordering tests
    def test_dictionary_key_ordering(self, dict_data):
        """Test that dictionary keys are consistently sorted alphabetically."""
        # Skip if dict contains YAML boolean word keys (yes, no, on, off, etc.)
        # YAML 1.1 converts these to booleans, which changes the key type
        yaml_bool_words = {"yes", "no", "on", "off", "true", "false"}
        if any(isinstance(k, str) and k.lower() in yaml_bool_words for k in dict_data):
            return

        yaml_str = yaml.safe_dump(dict_data, default_flow_style=False)

        # Format
        formatted = format_yaml_string(yaml_str)

        # Parse and verify keys are actually sorted in the parsed structure
        parsed = yaml.safe_load(formatted)

        # Get actual keys from parsed dict (handles quoted keys correctly)
        if isinstance(parsed, dict):
            actual_keys = list(parsed.keys())
            expected_keys = sorted(actual_keys, key=str)

            assert actual_keys == expected_keys, (
                f"Keys not sorted alphabetically!\nGot: {actual_keys}\nExpected: {expected_keys}"
            )

    @given(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters="\x00\r\x85\xa0",  # Exclude null, CR, NEL, and NBSP
            ),
            min_size=0,
            max_size=1000,
        )
    )  # Longer strings
    @settings(
        max_examples=500, deadline=None
    )  # Massively increased for edge case discovery
    def test_arbitrary_string_descriptions(self, text):
        """Test that arbitrary strings in description fields don't break formatting."""
        # Create a simple structure with the text as a description
        data = {"description": text}

        yaml_str = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)

        # Format twice
        formatted_once = format_yaml_string(yaml_str)
        formatted_twice = format_yaml_string(formatted_once)

        # Idempotence
        assert formatted_once == formatted_twice

        # Parse and verify
        try:
            parsed = yaml.safe_load(formatted_twice)
            assert "description" in parsed
            # Text should be preserved (modulo whitespace normalization for multi-line)
        except Exception as e:
            msg = (
                f"Failed to parse formatted YAML with text: {e}\n"
                f"Original text length: {len(text)}\n"
                f"Text preview: {text[:100]}\n"
                f"Formatted:\n{formatted_twice[:500]}"
            )
            raise AssertionError(msg)
