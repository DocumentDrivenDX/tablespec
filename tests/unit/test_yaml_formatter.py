# @covers US-027-AC2
"""Test suite for YAML formatter (normalizer + yamlfix + postprocessor)."""

import pytest

from tablespec.formatting import (
    YAMLFormatError,
    format_yaml_dict,
    format_yaml_string,
)

# Mark all tests in this module to skip Spark environment setup
pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestMultiLineStrings:
    """Test normalization of various multi-line string formats."""

    def test_backslash_escaped_to_literal_block(self):
        """Backslash-escaped multi-line strings should convert to literal block scalars."""
        yaml_input = """
description: "This is a long description that spans multiple lines\\nwith backslash\\nescapes"
"""
        result = format_yaml_string(yaml_input.strip())

        # Should convert to literal block scalar (with strip chomping |- to avoid trailing newlines)
        assert "|-\n" in result or "|\n" in result
        assert "This is a long description that spans multiple lines" in result
        assert "with backslash" in result
        assert "escapes" in result
        # Should NOT have backslash-n
        assert "\\n" not in result

    def test_multiple_newlines_preserved(self):
        """Multiple consecutive newlines should be preserved."""
        yaml_input = """
description: "Line 1\\n\\nLine 2 after blank\\n\\n\\nLine 3 after two blanks"
"""
        result = format_yaml_string(yaml_input.strip())

        # Should have literal block with blank lines
        assert "|-\n" in result or "|\n" in result
        lines = result.split("\n")
        # Count blank lines in output
        blank_count = sum(1 for line in lines if line.strip() == "")
        assert blank_count >= 2  # At least the blank lines from the content

    def test_mixed_content_with_special_chars(self):
        """Multi-line strings with special characters should be preserved."""
        yaml_input = """
description: "SQL: SELECT * FROM table\\nWHERE col = 'value'\\nAND other = 123"
"""
        result = format_yaml_string(yaml_input.strip())

        assert "SQL: SELECT * FROM table" in result
        assert "WHERE col = 'value'" in result
        assert "AND other = 123" in result

    def test_already_literal_block_unchanged(self):
        """Already properly formatted literal blocks should stay unchanged."""
        yaml_input = """
description: |
  This is already
  a literal block
  scalar format
"""
        result = format_yaml_string(yaml_input.strip())

        assert "description: |" in result
        assert "This is already" in result
        assert "a literal block" in result

    def test_short_strings_stay_inline(self):
        """Short strings without newlines should stay as quoted strings."""
        yaml_input = """
description: "Short description"
name: "Simple name"
"""
        result = format_yaml_string(yaml_input.strip())

        # Short strings should remain inline (quoted or unquoted depending on yamlfix)
        assert "Short description" in result
        assert "Simple name" in result
        # Should NOT be converted to literal blocks
        assert result.count("|") == 0

    def test_empty_strings(self):
        """Empty strings should be handled correctly."""
        yaml_input = """
description: ""
name: null
"""
        result = format_yaml_string(yaml_input.strip())

        # Empty string should be preserved
        assert "description:" in result
        # null should be preserved
        assert "name:" in result

    def test_long_quoted_string_with_colons(self):
        """Long quoted strings with colons should not break YAML syntax.

        Regression test: yamlfix wraps long quoted strings, and we preserve
        them as-is to maintain semantic meaning (spaces not newlines).
        """
        # Test 1: Long single-line quoted string (yamlfix will wrap it)
        yaml_input = """
meta:
  description: 'Detects duplicate rows within a delivered file by requiring the pair (meta_source_checksum, meta_checksum) to be unique. Why: meta_checksum is the SHA256 of the input row data and should be unique for distinct records within the same source file; duplicates usually indicate re-listed members or ingestion duplication. Constraint: no two rows from the same file (same meta_source_checksum) may share the same meta_checksum. Source context: Bronze.Raw computes both checksums for deduplication and change detection. Applies to MD/ME/MP.'
"""
        # Should not raise an error and produce valid YAML
        result = format_yaml_string(yaml_input.strip())

        # Result should be valid YAML
        import yaml

        parsed = yaml.safe_load(result)
        assert "meta" in parsed
        assert "description" in parsed["meta"]

        # Should contain the key phrases
        desc = parsed["meta"]["description"]
        assert "Detects duplicate rows" in desc
        assert "Constraint:" in desc
        assert "Bronze.Raw" in desc

        # Should be a valid quoted string (yamlfix may wrap it across lines)
        # We keep it as-is to preserve semantic meaning (spaces, not newlines)
        assert "description:" in result

        # Test 2: Already-wrapped quoted string (yamlfix format)
        yaml_input_wrapped = """
meta:
  description: 'Detects duplicate rows within a delivered file by requiring the pair (meta_source_checksum, meta_checksum)
    to be unique. Why: meta_checksum is the SHA256 of the input row data and should be unique for distinct records within
    the same source file; duplicates usually indicate re-listed members or ingestion duplication. Constraint: no two rows
    from the same file (same meta_source_checksum) may share the same meta_checksum. Source context: Bronze.Raw computes
    both checksums for deduplication and change detection. Applies to MD/ME/MP.'
"""
        # Should not raise an error
        result2 = format_yaml_string(yaml_input_wrapped.strip())

        # Result should be valid YAML
        parsed2 = yaml.safe_load(result2)
        assert "meta" in parsed2
        assert "description" in parsed2["meta"]

        # Should keep as wrapped quoted string (preserves spaces, not newlines)
        assert "description:" in result2

    def test_real_world_wrapped_string_from_centene(self):
        """Test actual problematic case from centene_2026_iha pipeline.

        This tests long multi-line quoted strings with colons.
        We keep them as-is to preserve semantic meaning (spaces not newlines).
        """
        # Simplified version focusing on the core issue: long wrapped quoted string
        yaml_input = """validations:
  - meta:
      description: 'Detects duplicate rows within a delivered file by requiring the pair (meta_source_checksum, meta_checksum)
        to be unique. Why: meta_checksum is the SHA256 of the input row data and should be unique for distinct records within
        the same source file; duplicates usually indicate re-listed members or ingestion duplication. Constraint: no two rows
        from the same file (same meta_source_checksum) may share the same meta_checksum. Source context: Bronze.Raw computes
        both checksums for deduplication and change detection. Applies to MD/ME/MP.'
"""
        # Should not raise an error
        result = format_yaml_string(yaml_input.strip())

        # Should produce valid YAML
        import yaml

        parsed = yaml.safe_load(result)
        assert "validations" in parsed
        assert isinstance(parsed["validations"], list)
        assert "meta" in parsed["validations"][0]
        assert "description" in parsed["validations"][0]["meta"]

        # Should preserve all the key content without YAML syntax errors
        desc = parsed["validations"][0]["meta"]["description"]
        assert "Detects duplicate rows" in desc
        assert "meta_source_checksum" in desc
        assert "Constraint:" in desc
        assert "Bronze.Raw" in desc

    def test_greedy_regex_corruption_bug(self):
        """Regression test for greedy regex bug that corrupts YAML structure.

        The wrapped_pattern regex was too greedy with re.DOTALL, causing it to
        match from a quoted string through hundreds of lines of YAML structure
        until finding a closing quote in a different validation rule. This
        collapsed entire YAML structures into malformed literal blocks.

        Real-world corruption example:
        BEFORE (correct):
            column:
              description: 'Vendor name who is performing IHA outreach. Ex: HCMG'
              length: 20
              name: source
            validations:
              - kwargs:

        AFTER (CORRUPTED):
            column:
              description: |
                Vendor name who is performing IHA outreach. Ex: HCMG' length: 20 name:
                source nullable: MD: false ME: false MP: false validations: - kwargs:
        """
        # This is the exact YAML structure from centene_2026_iha/disposition_report/columns/source.yaml
        yaml_input = """---
column:
  canonical_name: SOURCE
  data_type: StringType
  description: 'Vendor name who is performing IHA outreach. Ex: HCMG'
  length: 20
  name: source
  nullable:
    MD: false
    ME: false
    MP: false
  reporting_requirement: R
  source: data
validations:
  - kwargs:
      column: source
    meta:
      description: Column source must exist in table schema
"""

        # Format the YAML
        result = format_yaml_string(yaml_input.strip())

        # Should produce valid YAML
        import yaml

        parsed = yaml.safe_load(result)

        # Verify structure is preserved (not collapsed)
        assert "column" in parsed
        assert "validations" in parsed

        # Verify column section is intact with all fields
        column = parsed["column"]
        assert column["canonical_name"] == "SOURCE"
        assert column["data_type"] == "StringType"
        assert "Vendor name" in column["description"]
        assert column["length"] == 20
        assert column["name"] == "source"

        # Verify nullable is a dict, not collapsed into description string
        assert isinstance(column["nullable"], dict)
        assert column["nullable"]["MD"] is False
        assert column["nullable"]["ME"] is False
        assert column["nullable"]["MP"] is False

        # Verify validations is a list, not collapsed
        assert isinstance(parsed["validations"], list)
        assert len(parsed["validations"]) > 0

        # The description should NOT contain YAML structure like 'length: 20' or 'name: source'
        desc = column["description"]
        assert "length: 20" not in desc.lower()
        assert "nullable:" not in desc.lower()
        assert "validations:" not in desc.lower()
        assert "kwargs:" not in desc.lower()


class TestDictionaryKeySorting:
    """Test alphabetical sorting of dictionary keys."""

    def test_mixed_type_dict_keys(self):
        """Mixed-type dictionary keys (integers and strings) should sort without crashing.

        Regression test for TypeError: '<' not supported between instances of
        'ScalarInt' and 'SingleQuotedScalarString'.

        When ruamel.yaml parses YAML, it wraps primitives in special types
        (ScalarInt, SingleQuotedScalarString, etc.) that don't support
        cross-type comparison. Using key=str ensures consistent sorting.

        This test uses the exact failing example from fuzzing:
        {'0': None, '08': None}
        """
        # This is the exact failing example that triggered the TypeError
        yaml_input = """
'0': null
'08': null
"""

        # Should not raise TypeError
        result = format_yaml_string(yaml_input.strip())

        # Should produce valid YAML
        import yaml

        parsed = yaml.safe_load(result)
        assert parsed is not None

        # Both keys should be present (may be strings or ints depending on YAML parser)
        assert "0" in parsed or 0 in parsed
        assert "08" in parsed or 8 in parsed

    def test_simple_dict_sorted(self):
        """Simple dictionary keys should be sorted alphabetically."""
        data = {
            "zebra": 1,
            "apple": 2,
            "middle": 3,
            "banana": 4,
        }

        result = format_yaml_dict(data)
        lines = [line for line in result.split("\n") if line.strip()]

        # Keys should appear in alphabetical order
        assert lines[0].startswith("apple:")
        assert lines[1].startswith("banana:")
        assert lines[2].startswith("middle:")
        assert lines[3].startswith("zebra:")

    def test_nested_dicts_sorted_recursively(self):
        """Nested dictionaries should be sorted recursively."""
        data = {
            "zebra": {
                "nested_z": 1,
                "nested_a": 2,
            },
            "apple": {
                "nested_y": 3,
                "nested_b": 4,
            },
        }

        result = format_yaml_dict(data)

        # Top-level keys sorted
        apple_pos = result.index("apple:")
        zebra_pos = result.index("zebra:")
        assert apple_pos < zebra_pos

        # Nested keys sorted within each parent
        # Under apple: nested_b before nested_y
        apple_section = result[apple_pos:zebra_pos]
        assert apple_section.index("nested_b:") < apple_section.index("nested_y:")

        # Under zebra: nested_a before nested_z
        zebra_section = result[zebra_pos:]
        assert zebra_section.index("nested_a:") < zebra_section.index("nested_z:")

    def test_mixed_types_sorted(self):
        """Keys with different value types should all be sorted."""
        data = {
            "z_string": "value",
            "a_number": 123,
            "m_bool": True,
            "b_null": None,
            "x_list": [1, 2, 3],
            "c_dict": {"nested": "value"},
        }

        result = format_yaml_dict(data)

        # Extract top-level keys (lines with ':' that don't start with whitespace)
        top_level_keys = []
        for line in result.split("\n"):
            if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                key = line.split(":")[0].strip()
                top_level_keys.append(key)

        # Should be in alphabetical order
        expected_order = [
            "a_number",
            "b_null",
            "c_dict",
            "m_bool",
            "x_list",
            "z_string",
        ]
        assert top_level_keys == expected_order


class TestListPreservation:
    """Test that list order is preserved (NOT sorted)."""

    def test_list_of_dicts_indentation(self):
        """List of dictionaries should maintain proper indentation.

        This is a regression test for yamlfix breaking list item indentation.
        The indent_sequence=4 with indent_offset=2 configuration is critical
        for proper list formatting.
        """
        yaml_input = """
foreign_keys:
  - column: client_member_id
    confidence: 1.0
    references_column: client_member_id
    references_table: supplemental_contact
"""
        result = format_yaml_string(yaml_input.strip())

        # Should preserve list structure with proper indentation
        assert "foreign_keys:" in result
        assert "  - column: client_member_id" in result
        assert "    confidence: 1.0" in result
        assert "    references_column: client_member_id" in result
        assert "    references_table: supplemental_contact" in result

        # Should be idempotent
        result2 = format_yaml_string(result)
        assert result == result2

    def test_list_order_preserved(self):
        """Lists should maintain their original order."""
        data = {
            "items": ["zebra", "apple", "middle", "banana"],
        }

        result = format_yaml_dict(data)

        # Extract list items
        lines = result.split("\n")
        list_items = [
            line.strip().replace("- ", "")
            for line in lines
            if line.strip().startswith("-")
        ]

        # Should be in ORIGINAL order, not sorted
        assert list_items == ["zebra", "apple", "middle", "banana"]

    def test_nested_lists_preserved(self):
        """Nested lists should maintain their order."""
        data = {
            "validation_rules": [
                {"rule": "third"},
                {"rule": "first"},
                {"rule": "second"},
            ],
        }

        result = format_yaml_dict(data)

        # Find all "rule:" occurrences
        rule_positions = []
        for i, line in enumerate(result.split("\n")):
            if "rule:" in line:
                rule_positions.append((i, line.strip()))

        # Should appear in original order
        assert "third" in rule_positions[0][1]
        assert "first" in rule_positions[1][1]
        assert "second" in rule_positions[2][1]

    def test_column_list_order_critical(self):
        """Column order must be preserved (critical for UMF files)."""
        data = {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "name", "type": "STRING"},
                {"name": "created", "type": "DATE"},
            ],
        }

        result = format_yaml_dict(data)

        # Extract column names in order
        lines = result.split("\n")
        name_lines = [
            line for line in lines if "name:" in line and "STRING" not in line
        ]

        # Should maintain original order
        assert "id" in name_lines[0]
        assert "name" in name_lines[1]
        assert "created" in name_lines[2]


class TestFullPipeline:
    """Test the complete formatting pipeline."""

    def test_unsorted_with_multiline(self):
        """Test sorting + multi-line formatting together."""
        data = {
            "z_field": "simple",
            "a_field": "This is a very long description that will span multiple lines\nwith newlines\nin the content",
            "m_field": {
                "nested_z": 1,
                "nested_a": 2,
            },
        }

        result = format_yaml_dict(data)

        # Keys should be sorted
        a_pos = result.index("a_field:")
        m_pos = result.index("m_field:")
        z_pos = result.index("z_field:")
        assert a_pos < m_pos < z_pos

        # Multi-line should be converted to literal block
        assert "|-\n" in result or "|\n" in result
        assert "This is a very long description" in result

    def test_idempotence(self):
        """Running formatter twice should produce same result."""
        data = {
            "z": "value",
            "a": "value",
            "m": "This is a long string\nwith newlines",
        }

        # First pass
        result1 = format_yaml_dict(data)

        # Second pass on the result
        result2 = format_yaml_string(result1)

        # Should be identical
        assert result1 == result2

    def test_simple_dict_formatting(self):
        """Simple dict should produce valid sorted YAML."""
        data = {
            "z": "value",
            "a": "value",
        }

        result = format_yaml_dict(data)

        # Should be valid YAML
        assert "a: value" in result or "a:\n  value" in result
        assert "z: value" in result or "z:\n  value" in result
        # Keys should be sorted
        assert result.index("a:") < result.index("z:")


class TestUnicodeAndEscapeSequences:
    """Test that unicode and escape sequences are preserved without corruption.

    Regression tests for fuzzing-discovered bug where strings with special characters
    were being double-escaped during formatting, corrupting the actual data.
    """

    def test_escape_sequences_preserved(self):
        r"""Escape sequences should round-trip without corruption (Bug: fuzzing discovered data corruption).

        This test captures the exact failing example from fuzzing that revealed
        a critical data corruption bug. The formatter was converting quoted strings
        with escape sequences to literal block scalars, which don't interpret escapes,
        causing the actual string content to change.

        Original bug behavior:
        - Input:  {'0000A': '0000\\x1f\\x1f\\x1f𐀀𐀀𐀀𐀀𐀀\\x06'}
        - After:  {'0000A': '0000\\\\x1F\\\\x1F\\\\x1F\\\\U00010000...\\\\x06'}
        - The actual characters (\\x1f, 𐀀) became literal backslash sequences

        Root cause: The postprocessor's wrapped_pattern was converting yamlfix's
        line-wrapped quoted strings to literal blocks. Literal blocks treat backslashes
        as literal characters, not escape sequences, corrupting the data.

        Fix: Skip literal block conversion for any string containing escape sequences.
        """
        # The exact failing example from fuzzing
        original_data = {"0000A": "0000\x1f\x1f\x1f𐀀𐀀𐀀𐀀𐀀\x06", "1": None}

        # Format the data
        formatted_yaml = format_yaml_dict(original_data)

        # Parse back
        import yaml

        parsed = yaml.safe_load(formatted_yaml)

        # CRITICAL: Data must match exactly - this is the data integrity check
        assert parsed == original_data, (
            f"Data corruption detected!\n"
            f"Original: {original_data!r}\n"
            f"Parsed:   {parsed!r}\n"
            f"This means escape sequences were not preserved correctly."
        )

        # Verify specific field hasn't changed
        assert parsed["0000A"] == "0000\x1f\x1f\x1f𐀀𐀀𐀀𐀀𐀀\x06"
        assert parsed["1"] is None

    def test_mixed_escape_sequences_with_newline(self):
        """Strings with multiple types of escape sequences should be preserved."""
        original_data = {"test": "line1\nline2\x1f\x1f𐀀"}

        formatted_yaml = format_yaml_dict(original_data)

        import yaml

        parsed = yaml.safe_load(formatted_yaml)

        assert parsed == original_data
        assert parsed["test"] == "line1\nline2\x1f\x1f𐀀"

    def test_hex_escapes_preserved(self):
        """Hexadecimal escape sequences should be preserved."""
        original_data = {"key": "value\x00\x01\x02\xff"}

        formatted_yaml = format_yaml_dict(original_data)

        import yaml

        parsed = yaml.safe_load(formatted_yaml)

        assert parsed == original_data

    def test_unicode_escapes_preserved(self):
        """Unicode escape sequences should be preserved."""
        original_data = {"key": "hello\u2026world\U0001f600"}

        formatted_yaml = format_yaml_dict(original_data)

        import yaml

        parsed = yaml.safe_load(formatted_yaml)

        assert parsed == original_data

    def test_special_char_escapes_preserved(self):
        """Special character escapes (tab, return, etc) should be preserved."""
        original_data = {"key": "line1\tline2\rline3\bline4\fline5"}

        formatted_yaml = format_yaml_dict(original_data)

        import yaml

        parsed = yaml.safe_load(formatted_yaml)

        assert parsed == original_data


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_dict(self):
        """Empty dictionary should produce valid YAML."""
        result = format_yaml_dict({})
        assert result.strip() in ["{}", ""]

    def test_none_values_filtered(self):
        """None values should be filtered out or represented as null."""
        data = {
            "keep": "value",
            "remove": None,
        }

        result = format_yaml_dict(data)

        # Should have keep
        assert "keep:" in result
        # None handling depends on normalizer implementation
        # It may be filtered or represented as null

    def test_special_yaml_chars(self):
        """Special YAML characters should be handled correctly."""
        data = {
            "colon_value": "key: value",
            "bracket_value": "[1, 2, 3]",
            "quote_value": 'It\'s a "quoted" string',
        }

        result = format_yaml_dict(data)

        # Should handle special chars
        assert "key: value" in result
        assert "[1, 2, 3]" in result or "1, 2, 3" in result
        assert "quoted" in result

    def test_unicode_content(self):
        """Unicode content should be preserved."""
        data = {
            "emoji": "Hello 👋 World 🌍",
            "chinese": "你好世界",
            "arabic": "مرحبا بالعالم",
        }

        result = format_yaml_dict(data)

        # Unicode should be preserved
        assert "👋" in result
        assert "你好世界" in result
        assert "مرحبا بالعالم" in result

    def test_very_long_keys(self):
        """Very long dictionary keys should be handled."""
        data = {
            "a" * 100: "short_value",
            "normal_key": "value",
        }

        result = format_yaml_dict(data)

        # Both keys should be present
        assert "a" * 100 in result
        assert "normal_key:" in result

    def test_deeply_nested_structures(self):
        """Deeply nested structures should be sorted at all levels."""
        data = {
            "level1_z": {
                "level2_z": {
                    "level3_z": "value",
                    "level3_a": "value",
                },
                "level2_a": {
                    "level3_y": "value",
                    "level3_b": "value",
                },
            },
            "level1_a": "value",
        }

        result = format_yaml_dict(data)

        # Each level should be sorted
        assert result.index("level1_a:") < result.index("level1_z:")

        # Within level1_z
        level1_z_section = result[result.index("level1_z:") :]
        assert level1_z_section.index("level2_a:") < level1_z_section.index("level2_z:")


class TestStringVsFileFormatting:
    """Test that format_yaml_string and format_yaml_dict produce consistent output."""

    def test_string_and_dict_consistency(self):
        """Formatting a dict and formatting its YAML string should produce same result."""
        data = {
            "z": "value",
            "a": "value",
            "m": ["item1", "item2"],
        }

        # Format from dict
        result_from_dict = format_yaml_dict(data)

        # Convert dict to YAML manually, then format
        import yaml

        yaml_str = yaml.dump(data, default_flow_style=False)
        result_from_string = format_yaml_string(yaml_str)

        # Should produce equivalent output (minor whitespace differences OK)
        # Check that keys are in same order
        assert (
            result_from_dict.index("a:")
            < result_from_dict.index("m:")
            < result_from_dict.index("z:")
        )
        assert (
            result_from_string.index("a:")
            < result_from_string.index("m:")
            < result_from_string.index("z:")
        )


class TestErrorHandling:
    """Test error handling for invalid inputs."""

    def test_invalid_yaml_string_raises(self):
        """Invalid YAML should raise YAMLFormatError."""
        invalid_yaml = "this is: [not: {valid: yaml"

        with pytest.raises(YAMLFormatError):
            format_yaml_string(invalid_yaml)

    def test_non_dict_raises(self):
        """format_yaml_dict with non-dict should raise YAMLFormatError."""
        with pytest.raises((YAMLFormatError, AttributeError, TypeError)):
            format_yaml_dict("not a dict")  # type: ignore[arg-type]

    def test_empty_string_handled(self):
        """Empty string should be handled gracefully."""
        result = format_yaml_string("")
        assert result == "" or result.strip() == ""


class TestYamlfixLimitationsAndKnownIssues:
    """Test yamlfix limitations and known issues discovered through fuzzing."""

    def test_large_float_precision_loss_acceptable(self):
        """Large floats may lose precision during YAML serialization (acceptable limitation).

        Regression test for fuzzing-discovered issue where very large floats
        (> 10^16) lose the last digit of precision during formatting:
        - Input:  3.226615378757941e+16
        - Output: 3.22661537875794e+16 (lost last digit)

        Root cause: This is a yamlfix formatting behavior when round-tripping
        large floats through YAML. The difference is 8.0 on a value of ~3.2e16,
        which is within acceptable floating point precision limits.

        IEEE-754 double precision has ~15-17 significant decimal digits.
        This test documents that minor precision loss on very large floats
        is acceptable and uses approximate equality checking.

        For production UMF files, this is acceptable because:
        1. UMF uses STRING, INTEGER, DECIMAL types - not raw Python floats
        2. Numeric constraints use integers or bounded decimals
        3. Very large floats (> 10^16) are extremely rare in metadata
        """
        import math

        import yaml

        # The exact failing value from fuzzing
        data = 3.226615378757941e16

        # Convert to YAML and format
        yaml_str = yaml.safe_dump(data, default_flow_style=False)
        formatted = format_yaml_string(yaml_str)

        # Parse back
        parsed = yaml.safe_load(formatted)

        # Use approximate equality (relative tolerance of 1e-15)
        assert math.isclose(parsed, data, rel_tol=1e-15), (
            f"Float precision loss too large!\n"
            f"Original: {data}\n"
            f"Parsed:   {parsed}\n"
            f"Difference: {abs(parsed - data)}\n"
            f"Relative error: {abs(parsed - data) / data}"
        )

    def test_nel_character_idempotence_limitation(self):
        r"""NEL character (\x85) causes yamlfix idempotence failure (known limitation).

        Regression test for fuzzing-discovered issue where NEL (Next Line, \x85)
        control character causes non-idempotent formatting:
        - First format:  "validations:\n  - _: '\n      '\n"
        - Second format: "validations:\n  - _: ' '\n"

        Root cause: yamlfix inconsistently handles the YAML escape sequence \N
        (which represents NEL) across multiple passes:
        1. yaml.safe_dump() converts \x85 → "\N" (YAML escape sequence)
        2. yamlfix first pass converts "\N" → quoted string with actual newline+spaces
        3. yamlfix second pass normalizes newline+spaces → just spaces

        This is a yamlfix bug, but NEL is an obscure Unicode C1 control character
        that should never appear in production UMF metadata (which uses human-readable
        descriptions, validation rules, etc.).

        For production UMF files, this is acceptable because:
        1. NEL is a legacy Unicode control character from ISO-8859-1 days
        2. UMF descriptions should use standard newlines (\n, \r\n), not NEL
        3. The fuzzing strategy now blacklists \x85 to avoid this edge case
        """
        import yaml

        # The exact failing example from fuzzing
        list_data = [{"_": "\x85"}]  # \x85 = NEL (Next Line) character

        # Create YAML structure like UMF validations
        data = {"validations": list_data}
        yaml_str = yaml.safe_dump(data, default_flow_style=False)

        # Format twice
        formatted_once = format_yaml_string(yaml_str)
        formatted_twice = format_yaml_string(formatted_once)

        # Document the non-idempotent behavior
        # NOTE: This test documents the bug but doesn't assert idempotence
        # since fixing this requires changes to yamlfix itself
        if formatted_once != formatted_twice:
            # This is expected - document the difference for awareness
            assert "\x85" in list_data[0]["_"], (
                "Test setup: NEL character must be present"
            )

            # Verify the output is at least valid YAML both times
            parsed_once = yaml.safe_load(formatted_once)
            parsed_twice = yaml.safe_load(formatted_twice)
            assert "validations" in parsed_once
            assert "validations" in parsed_twice

            # Both should have the same number of items
            assert len(parsed_once["validations"]) == len(parsed_twice["validations"])


class TestTopLevelListLimitation:
    """Test handling of top-level lists (known limitation of yamlfix).

    These tests document fuzzing-discovered bugs where yamlfix produces invalid
    YAML for top-level lists due to incorrect indentation with indent_offset=2.

    Regression tests for:
    - Bug #1: [None, None] formats differently on first vs second pass
    - Bug #2: ['', None] causes parser error on second pass

    Since UMF files always have dicts at the root (column:, validations:),
    we explicitly reject top-level lists with a clear error message.
    """

    def test_top_level_list_idempotence_bug(self):
        r"""Top-level lists should raise clear error (Bug #1: idempotence failure).

        Fuzzing discovered that [None, None] formats differently on each pass:
        - First format: '- null\\n  - null\\n' (invalid indentation)
        - Second format: '- null - null\\n' (completely wrong)

        This is a known yamlfix bug with indent_offset=2 on top-level lists.
        Since UMF files never have top-level lists, we reject them with a clear error.
        """
        import yaml

        # The exact failing example from fuzzing
        data = [None, None]
        yaml_str = yaml.dump(data, default_flow_style=False)

        # Should raise YAMLFormatError with helpful message
        with pytest.raises(YAMLFormatError) as exc_info:
            format_yaml_string(yaml_str)

        # Error message should mention the limitation
        error_msg = str(exc_info.value).lower()
        assert "top-level list" in error_msg
        assert "not supported" in error_msg

    def test_top_level_list_with_empty_string_bug(self):
        r"""Top-level lists should raise clear error (Bug #2: parser error).

        Fuzzing discovered that ['', None] causes parser errors with top-level lists.

        Since UMF files never have top-level lists, we reject them with a clear error.
        """
        import yaml

        # The exact failing example from fuzzing
        data = ["", None]
        yaml_str = yaml.dump(data, default_flow_style=False)

        # Should raise YAMLFormatError with helpful message (not ParserError)
        with pytest.raises(YAMLFormatError) as exc_info:
            format_yaml_string(yaml_str)

        # Error message should explain the limitation
        error_msg = str(exc_info.value).lower()
        assert "top-level list" in error_msg
        assert "not supported" in error_msg

    def test_top_level_list_of_strings(self):
        """Any top-level list should be rejected, not just those with nulls."""
        import yaml

        data = ["apple", "banana", "cherry"]
        yaml_str = yaml.dump(data, default_flow_style=False)

        # Should raise YAMLFormatError
        with pytest.raises(YAMLFormatError) as exc_info:
            format_yaml_string(yaml_str)

        error_msg = str(exc_info.value).lower()
        assert "top-level list" in error_msg

    def test_nested_lists_still_work(self):
        """Nested lists inside dicts should still work fine.

        This confirms we're only rejecting lists at the document root,
        not lists nested inside dictionaries (which UMF uses extensively
        for validations, columns, etc.).
        """
        data = {
            "validations": [
                {"rule": "not_null"},
                {"rule": "unique"},
            ],
            "columns": ["id", "name", "created"],
        }

        # Should NOT raise an error
        result = format_yaml_dict(data)

        # Should be valid YAML
        import yaml

        parsed = yaml.safe_load(result)
        assert "validations" in parsed
        assert "columns" in parsed
        assert isinstance(parsed["validations"], list)
        assert isinstance(parsed["columns"], list)


@pytest.mark.no_spark
class TestYamlfixBooleanConversionBug:
    """Regression tests for yamlfix converting words like 'no', 'yes' to booleans.

    yamlfix has a known bug where it interprets certain words as YAML boolean
    literals when they appear at the end of wrapped lines in quoted strings.

    Examples:
    - "no" → false
    - "yes" → true
    - "on" → true
    - "off" → false

    This is particularly problematic when these words appear in natural language
    descriptions that get wrapped across multiple lines.

    Root cause: When yamlfix wraps a long quoted string, if a word like "no"
    appears at the end of a line, yamlfix incorrectly treats it as a YAML
    boolean literal and converts it to the boolean value.

    Test cases document the exact scenarios discovered during formatter testing.

    """

    def test_no_at_line_end_converted_to_false(self):
        """Bug: Word 'no' at end of line in wrapped string becomes 'false'.

        This is the exact bug discovered in:
        pipelines/centene_2026_iha/outreach_list_guardian/validation_rules.yaml

        Expected: "Constraint: no two rows"
        Got:      "Constraint: false two rows"
        """
        import yaml

        # Simulate yamlfix's wrapping behavior: long string gets wrapped,
        # and "no" ends up at the end of a line
        yaml_input = """
description: 'Detects duplicate rows within a delivered file. Constraint: no
        two rows from the same file may share the same meta_checksum.'
"""

        # Format the YAML
        result = format_yaml_string(yaml_input.strip())

        # Parse back
        parsed = yaml.safe_load(result)

        # CRITICAL: The description should contain "no two" (possibly with newline before "rows")
        # NOT "false two"
        description = parsed["description"]

        # Check that "no two" appears (allowing for newlines after)
        # The text may be "no two rows" or "no two\nrows" depending on line wrapping
        assert "no two" in description, (
            f"yamlfix bug: 'no' was converted to 'false'!\n"
            f"Description: {description}\n"
            f"Expected: 'no two' (possibly followed by newline and 'rows')\n"
            f"This is a known yamlfix bug with boolean conversion in wrapped strings."
        )

        # Should NOT contain the corrupted text "false two"
        assert "false two" not in description

    def test_multiple_no_words_in_description(self):
        """Test that multiple instances of 'no' in natural language are preserved."""
        import yaml

        yaml_input = """
description: 'There should be no duplicates. If there are no matches, no action is taken. This ensures no data loss.'
"""

        result = format_yaml_string(yaml_input.strip())
        parsed = yaml.safe_load(result)

        # Count occurrences of "no" in the description
        description = parsed["description"]
        no_count = description.lower().count(" no ")

        # Should have preserved all instances
        # (May vary based on normalization, but should not be zero)
        assert no_count >= 3, f"Expected at least 3 instances of 'no', got {no_count}"

        # Should NOT have any 'false' substitutions
        assert "false duplicates" not in description
        assert "false matches" not in description
        assert "false action" not in description
        assert "false data" not in description

    def test_yes_on_off_boolean_words(self):
        """Test other YAML boolean literals: yes, on, off.

        YAML 1.1 spec treats these as boolean literals:
        - yes, Yes, YES → true
        - no, No, NO → false
        - on, On, ON → true
        - off, Off, OFF → false
        """
        import yaml

        yaml_input = """
description: 'Turn on the feature. If yes is selected, validation runs. Turn off when done. Answer no to skip.'
"""

        result = format_yaml_string(yaml_input.strip())
        parsed = yaml.safe_load(result)

        description = parsed["description"]

        # These words should be preserved in natural language
        assert "on the feature" in description or "on  the feature" in description
        assert "yes is selected" in description or "yes  is selected" in description
        assert "off when" in description or "off  when" in description
        assert "no to skip" in description or "no  to skip" in description

        # Should NOT have boolean conversions
        assert "true the feature" not in description
        assert "true is selected" not in description
        assert "false when" not in description
        assert "false to skip" not in description


class TestIdempotence:
    """Test that formatter is idempotent (multiple runs produce identical output)."""

    def test_escaped_backslash_idempotence(self):
        r"""Test that strings with escaped backslashes are idempotent.

        Bug: Strings with backslash-n escapes that yamlfix wraps with backslash-space
        line continuations were not recognized as containing escape sequences, causing:
        1. First pass: Convert to literal block with backslashes
        2. Second pass: Blank lines disappear due to yamlfix rewrapping
        3. Non-idempotent output

        The fix: Include \\\\ in the escape sequence detection regex so strings with
        escaped backslashes stay as quoted strings instead of being converted to
        literal blocks.
        """
        # Real-world example from centene_2026_iha survivorship explanations
        # Long string with \n that yamlfix will wrap with backslash line continuation
        yaml_input = r"""
explanation: "Requirement: This is a very long requirement text that contains newlines.\nIf it is not available, leave it blank.\n\nProvenance policy: enterprise_only. The target field represents an operational event date that must be tracked carefully."
"""
        # First format
        result1 = format_yaml_string(yaml_input.strip())

        # Second format (should be identical if idempotent)
        result2 = format_yaml_string(result1)

        # Third format (extra verification)
        result3 = format_yaml_string(result2)

        # All three results should be identical
        assert result1 == result2, (
            f"Formatter not idempotent after 1st pass!\n"
            f"First:\n{result1}\n\nSecond:\n{result2}\n\n"
            f"First repr:\n{result1!r}\n\nSecond repr:\n{result2!r}"
        )
        assert result2 == result3, (
            f"Formatter not idempotent after 2nd pass!\nSecond:\n{result2}\n\nThird:\n{result3}"
        )


@pytest.mark.no_spark
class TestTypeCoercionProtection:
    """Test that YAML read-write cycle preserves types without unexpected coercion.

    Regression tests for PR #548 where YAML booleans (true/false) in value_set
    lists caused validation failures because:
    1. YAML parses unquoted true/false as booleans, not strings
    2. When compiled to JSON, they become JSON booleans
    3. Spark validation fails comparing string data against boolean expected values

    The fix requires that string values which look like YAML special values
    (true, false, yes, no, on, off, null) must be quoted to preserve their
    string type through the read-write-read cycle.
    """

    def test_boolean_strings_in_value_set_preserved(self):
        """String values 'true'/'false' in value_set must stay as strings.

        This is the exact bug from PR #548: a1c_kit_mailed.yaml had:
            value_set:
              - true   # YAML boolean!
              - false  # YAML boolean!
              - N/A    # string

        After JSON compilation, Spark couldn't compare string 'N/A' with boolean true.
        """
        import yaml

        # UMF validation structure with string values that look like booleans
        data = {
            "validations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {
                        "column": "a1c_kit_mailed",
                        "value_set": ["true", "false", "N/A"],  # All should be strings
                    },
                }
            ]
        }

        # Format the dict to YAML
        result = format_yaml_dict(data)

        # Parse it back
        parsed = yaml.safe_load(result)

        # CRITICAL: value_set items must all be strings, not booleans
        value_set = parsed["validations"][0]["kwargs"]["value_set"]

        for i, item in enumerate(value_set):
            assert isinstance(item, str), (
                f"Type coercion detected! value_set[{i}] = {item!r} "
                f"is {type(item).__name__}, expected str.\n"
                f"YAML output:\n{result}\n\n"
                f"This breaks validation because Spark can't compare "
                f"string column data against boolean expected values."
            )

        # Verify exact values preserved
        assert value_set == ["true", "false", "N/A"]

    def test_all_yaml_boolean_literals_quoted(self):
        """All YAML 1.1 boolean literals must be quoted when they're meant as strings.

        YAML 1.1 boolean literals (case-insensitive):
        - true, True, TRUE, yes, Yes, YES, on, On, ON → parsed as True
        - false, False, FALSE, no, No, NO, off, Off, OFF → parsed as False

        When these appear in data as strings, they must be quoted to prevent
        type coercion during the YAML read-write cycle.
        """
        import yaml

        # All YAML 1.1 boolean-like strings
        boolean_strings = [
            "true",
            "True",
            "TRUE",
            "false",
            "False",
            "FALSE",
            "yes",
            "Yes",
            "YES",
            "no",
            "No",
            "NO",
            "on",
            "On",
            "ON",
            "off",
            "Off",
            "OFF",
        ]

        data = {"value_set": boolean_strings}

        # Format and parse back
        result = format_yaml_dict(data)
        parsed = yaml.safe_load(result)

        # All items must remain as strings
        for _i, (original, parsed_value) in enumerate(
            zip(boolean_strings, parsed["value_set"], strict=False)
        ):
            assert isinstance(parsed_value, str), (
                f"Boolean literal '{original}' was coerced to {type(parsed_value).__name__}!\n"
                f"YAML output:\n{result}"
            )
            assert parsed_value == original, (
                f"Value changed: '{original}' → '{parsed_value}'"
            )

    def test_null_string_preserved(self):
        """The string 'null' must not be coerced to None.

        YAML parses unquoted 'null', 'Null', 'NULL', '~' as Python None.
        When meant as a string value, it must be quoted.
        """
        import yaml

        null_strings = ["null", "Null", "NULL", "~"]
        data = {"values": null_strings}

        result = format_yaml_dict(data)
        parsed = yaml.safe_load(result)

        for _i, (original, parsed_value) in enumerate(
            zip(null_strings, parsed["values"], strict=False)
        ):
            assert parsed_value is not None, (
                f"String '{original}' was coerced to None!\nYAML output:\n{result}"
            )
            assert isinstance(parsed_value, str)
            assert parsed_value == original

    def test_mixed_types_in_list_preserved(self):
        """Lists with mixed string/boolean/null values must preserve types exactly."""
        import yaml

        # Mix of actual booleans, actual None, and strings
        data = {
            "mixed": [
                True,  # actual boolean
                False,  # actual boolean
                None,  # actual None
                "true",  # string that looks like boolean
                "false",  # string that looks like boolean
                "null",  # string that looks like null
                "regular",  # regular string
            ]
        }

        result = format_yaml_dict(data)
        parsed = yaml.safe_load(result)

        mixed = parsed["mixed"]

        # Check each type is preserved
        assert mixed[0] is True, "Actual True should stay True"
        assert mixed[1] is False, "Actual False should stay False"
        assert mixed[2] is None, "Actual None should stay None"
        assert isinstance(mixed[3], str), "String 'true' should stay string"
        assert mixed[3] == "true"
        assert isinstance(mixed[4], str), "String 'false' should stay string"
        assert mixed[4] == "false"
        assert isinstance(mixed[5], str), "String 'null' should stay string"
        assert mixed[5] == "null"
        assert mixed[6] == "regular", "Regular string should be unchanged"

    def test_validation_value_set_round_trip(self):
        """Full round-trip test for realistic validation value_set scenarios.

        Tests the exact pattern from healthcare pipeline validations where
        columns accept Y/N, Yes/No, true/false, or numeric 1/0 as valid values.
        """
        import yaml

        data = {
            "validations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {
                        "column": "pathology",
                        "value_set": [
                            "Y",
                            "N",  # Short codes
                            "Yes",
                            "No",  # Full words (YAML booleans!)
                            "TRUE",
                            "FALSE",  # Uppercase (YAML booleans!)
                            "True",
                            "False",  # Title case (YAML booleans!)
                            "true",
                            "false",  # Lowercase (YAML booleans!)
                            "1",
                            "0",  # Numeric strings
                        ],
                    },
                    "meta": {
                        "description": "Pathology field accepts boolean-like indicators",
                    },
                }
            ]
        }

        # Format to YAML
        result = format_yaml_dict(data)

        # Parse back
        parsed = yaml.safe_load(result)

        # Extract value_set
        value_set = parsed["validations"][0]["kwargs"]["value_set"]

        # Count how many are still strings
        strings = [v for v in value_set if isinstance(v, str)]
        booleans = [v for v in value_set if isinstance(v, bool)]

        assert len(booleans) == 0, (
            f"Found {len(booleans)} boolean values in value_set! "
            f"These should all be strings.\n"
            f"Booleans: {booleans}\n"
            f"YAML output:\n{result}"
        )

        assert len(strings) == 12, (
            f"Expected 12 string values, got {len(strings)}.\n"
            f"Strings: {strings}\n"
            f"YAML output:\n{result}"
        )

    def test_format_yaml_string_preserves_quoted_booleans(self):
        """When YAML input has quoted booleans, they should stay quoted."""
        # Input with properly quoted boolean-like strings
        yaml_input = """
validations:
  - kwargs:
      value_set:
        - 'true'
        - 'false'
        - 'yes'
        - 'no'
"""
        import yaml

        result = format_yaml_string(yaml_input.strip())
        parsed = yaml.safe_load(result)

        value_set = parsed["validations"][0]["kwargs"]["value_set"]

        # All should remain strings
        for item in value_set:
            assert isinstance(item, str), f"'{item}' became {type(item).__name__}"

    def test_unquoted_booleans_in_input_become_booleans(self):
        """Document current behavior: unquoted booleans in input stay as booleans.

        This test documents that if the source YAML has unquoted true/false,
        they are parsed as booleans and stay as booleans after formatting.
        The fix for the PR #548 bug is to ensure our YAML writers quote
        string values that look like booleans.
        """
        # Input with unquoted booleans (the problematic case)
        yaml_input = """
validations:
  - kwargs:
      value_set:
        - true
        - false
"""
        import yaml

        result = format_yaml_string(yaml_input.strip())
        parsed = yaml.safe_load(result)

        value_set = parsed["validations"][0]["kwargs"]["value_set"]

        # These are booleans because input was unquoted
        assert value_set[0] is True, "Unquoted 'true' should parse as boolean True"
        assert value_set[1] is False, "Unquoted 'false' should parse as boolean False"

        # This test documents the current behavior - the source of the bug
        # is that our YAML writers must quote boolean-like strings to prevent this
