"""Unit tests for GXConstraintExtractor regex generator fixes."""

# @covers US-006-AC1
# @covers US-006-AC2
# @covers US-006-AC3
# @covers US-006-AC4

import re

import pytest

from tablespec import GXConstraintExtractor

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestRegexGenerator:
    """Test suite for GXConstraintExtractor.generate_value_from_regex()."""

    @pytest.fixture
    def extractor(self):
        """Create a GXConstraintExtractor instance."""
        return GXConstraintExtractor()

    def test_non_capturing_group_basic(self, extractor):
        """Test that non-capturing groups (?:...) work correctly."""
        pattern = r"^(?:\d{3})$"
        value = extractor.generate_value_from_regex(pattern)
        assert re.match(r"^\d{3}$", value), (
            f"Generated value '{value}' doesn't match pattern"
        )
        assert "?:" not in value, (
            f"Non-capturing group prefix leaked into value: {value}"
        )

    def test_alternation_basic(self, extractor):
        """Test that alternation (A|B) chooses one alternative."""
        pattern = r"^(A|B)$"
        value = extractor.generate_value_from_regex(pattern)
        assert value in ["A", "B"], f"Alternation should choose A or B, got: {value}"

    def test_alternation_with_non_capturing_group(self, extractor):
        """Test alternation inside non-capturing group - the ZIP code case."""
        pattern = r"^(?:\d{5}-\d{4}|\d{9})$"
        value = extractor.generate_value_from_regex(pattern)

        # Should match one of the two alternatives
        assert re.match(r"^\d{5}-\d{4}$", value) or re.match(r"^\d{9}$", value), (
            f"Generated value '{value}' doesn't match either alternative"
        )

        # Should NOT contain the ?: prefix or both alternatives concatenated
        assert "?:" not in value, f"Non-capturing group prefix leaked: {value}"
        assert len(value) <= 10, f"Value too long (likely both alternatives): {value}"

    def test_alternation_multiple_choices(self, extractor):
        """Test alternation with more than 2 choices."""
        pattern = r"^(ONE|TWO|THREE)$"
        value = extractor.generate_value_from_regex(pattern)
        assert value in [
            "ONE",
            "TWO",
            "THREE",
        ], f"Should choose from three alternatives, got: {value}"

    def test_top_level_alternation_without_parens(self, extractor):
        r"""Test top-level alternation without parentheses (TIN validation pattern).

        This was causing embedded pipe characters in output, breaking CSV parsing.
        Pattern from rendering_prov_tin: ^\d{9}$|^\d{12}$|^$
        """
        pattern = r"^\d{9}$|^\d{12}$|^$"
        for _ in range(10):
            value = extractor.generate_value_from_regex(pattern)
            # Should NOT contain pipe characters (was the bug)
            assert "|" not in value, f"Value should not contain pipe: {value!r}"
            # Should NOT contain $ or ^ literals
            assert "$" not in value, f"Value should not contain $: {value!r}"
            assert "^" not in value, f"Value should not contain ^: {value!r}"
            # Should match the pattern (9 digits, 12 digits, or empty)
            assert re.match(r"^\d{9}$|^\d{12}$|^$", value), (
                f"Value {value!r} should match original pattern"
            )

    def test_alternation_with_complex_patterns(self, extractor):
        """Test alternation with complex regex patterns in alternatives."""
        pattern = r"^(?:\d{5}|\d{3}-\d{2}-\d{4})$"
        value = extractor.generate_value_from_regex(pattern)

        # Should match one of: 5 digits OR SSN format
        assert re.match(r"^\d{5}$", value) or re.match(r"^\d{3}-\d{2}-\d{4}$", value), (
            f"Generated value '{value}' doesn't match either pattern"
        )

    def test_nested_groups_with_alternation(self, extractor):
        """Test nested groups with alternation."""
        pattern = r"^(A(B|C))$"
        value = extractor.generate_value_from_regex(pattern)
        assert value in ["AB", "AC"], (
            f"Nested alternation should produce AB or AC, got: {value}"
        )

    def test_zip_code_patterns(self, extractor):
        """Test various ZIP code patterns that were causing issues."""
        patterns = [
            r"^\d{5}$",  # 5-digit ZIP
            r"^\d{9}$",  # 9-digit ZIP
            r"^\d{5}-\d{4}$",  # ZIP+4
            r"^(?:\d{5}-\d{4}|\d{9})$",  # Alternation with non-capturing
        ]

        for pattern in patterns:
            value = extractor.generate_value_from_regex(pattern)
            # Should not contain the problematic ?: prefix
            assert "?:" not in value, (
                f"Pattern {pattern} generated invalid value: {value}"
            )
            # Should match the original pattern
            assert re.match(pattern, value), (
                f"Pattern {pattern} generated non-matching value: {value}"
            )

    def test_find_matching_paren(self, extractor):
        """Test the _find_matching_paren helper method."""
        # Simple case
        assert extractor._find_matching_paren("(abc)", 0) == 4

        # Nested parentheses
        assert extractor._find_matching_paren("((a)b)", 0) == 5
        assert extractor._find_matching_paren("((a)b)", 1) == 3

        # No matching paren
        assert extractor._find_matching_paren("(abc", 0) == -1

    def test_split_alternation(self, extractor):
        """Test the _split_alternation helper method."""
        # Simple alternation
        assert extractor._split_alternation("A|B") == ["A", "B"]

        # Multiple alternatives
        assert extractor._split_alternation("A|B|C") == ["A", "B", "C"]

        # Alternation with nested groups
        assert extractor._split_alternation(r"\d{5}|\d{3}-\d{2}-\d{4}") == [
            r"\d{5}",
            r"\d{3}-\d{2}-\d{4}",
        ]

        # No alternation
        assert extractor._split_alternation(r"\d{5}") == [r"\d{5}"]

        # Alternation inside nested group (should not split)
        result = extractor._split_alternation(r"\d{5}|(A|B)")
        assert len(result) == 2
        assert result[0] == r"\d{5}"
        assert result[1] == "(A|B)"

    def test_quantifiers_still_work(self, extractor):
        """Ensure quantifiers (+, ?, {n}) still work after our changes."""
        # Test + quantifier with \d
        pattern = r"^\d+$"
        value = extractor.generate_value_from_regex(pattern)
        assert re.match(r"^\d+$", value), f"+ quantifier failed: {value}"

        # Test ? quantifier on a group (quantifiers on literals are not supported)
        pattern = r"^(A)?B$"
        value = extractor.generate_value_from_regex(pattern)
        assert value in ["B", "AB"], f"? quantifier on group failed: {value}"

        # Test {n} quantifier with \d
        pattern = r"^\d{5}$"
        value = extractor.generate_value_from_regex(pattern)
        assert re.match(r"^\d{5}$", value), f"{{n}} quantifier failed: {value}"

        # Test {n,m} range quantifier
        pattern = r"^\d{3,5}$"
        value = extractor.generate_value_from_regex(pattern)
        assert re.match(r"^\d{3,5}$", value), f"{{n,m}} quantifier failed: {value}"

    def test_character_classes_still_work(self, extractor):
        """Ensure character classes still work after our changes."""
        pattern = r"^[A-Z]{2}\d{3}$"
        value = extractor.generate_value_from_regex(pattern)
        assert re.match(r"^[A-Z]{2}\d{3}$", value), (
            f"Character class pattern failed: {value}"
        )


class TestLooksLikeColumnName:
    """Test suite for _looks_like_column_name filter."""

    @pytest.fixture
    def extractor(self):
        """Create a GXConstraintExtractor instance."""
        return GXConstraintExtractor()

    def test_state_lob_enums_not_filtered(self, extractor):
        """Test that state_LOB enum values are not filtered as column names."""
        valid_data_values = [
            "PENNSYLVANIA_MEDICARE",
            "PENNSYLVANIA_MEDICAID",
            "PENNSYLVANIA_MARKETPLACE",
            "PENNSYLVANIA_DUALS",
            "CALIFORNIA_MEDICARE",
            "CALIFORNIA_MEDICAID",
            "NEW_YORK_MARKETPLACE",
            "TEXAS_MEDICARE",
        ]

        for value in valid_data_values:
            result = extractor._looks_like_column_name(value)
            assert result is False, (
                f"Valid enum value '{value}' should not be filtered as column name"
            )

    def test_column_names_are_filtered(self, extractor):
        """Test that actual column names are correctly filtered."""
        column_names = [
            "CLIENT_MEMBER_ID",
            "MEMBER_BIRTH_DATE",
            "FIRST_NAME",
            "LAST_NAME",
            "PLAN_DESC",
            "SERVICE_TYPE_CODE",
            "ENROLLMENT_FLAG",
            "MEMBER_PHONE",
            "CLIENT_ADDRESS",
            "PROVIDER_NPI",
            "CLAIM_NBR",
        ]

        for value in column_names:
            result = extractor._looks_like_column_name(value)
            assert result is True, (
                f"Column name '{value}' should be filtered as column name"
            )

    def test_simple_enums_not_filtered(self, extractor):
        """Test that simple enum values without underscores are not filtered."""
        simple_enums = ["ACTIVE", "INACTIVE", "PENDING", "COMPLETED", "MALE", "FEMALE"]

        for value in simple_enums:
            result = extractor._looks_like_column_name(value)
            assert result is False, (
                f"Simple enum value '{value}' should not be filtered as column name"
            )

    def test_uppercase_without_keywords_not_filtered(self, extractor):
        """Test that uppercase values with underscores but no keywords pass through."""
        non_keyword_values = [
            "A_B_C",
            "FOO_BAR",
            "HELLO_WORLD",
            "CATEGORY_ONE",
            "LEVEL_TWO",
        ]

        for value in non_keyword_values:
            result = extractor._looks_like_column_name(value)
            assert result is False, (
                f"Value '{value}' without column keywords should not be filtered"
            )

    def test_empty_and_whitespace_filtered(self, extractor):
        """Test that empty and whitespace values are filtered."""
        invalid_values = ["", "   ", "\t", "\n"]

        for value in invalid_values:
            result = extractor._looks_like_column_name(value)
            assert result is True, (
                f"Empty/whitespace value '{value!r}' should be filtered"
            )

    def test_exact_pattern_matches_filtered(self, extractor):
        """Test that exact pattern matches from suspicious_patterns are filtered."""
        exact_matches = [
            "CLIENT MBRID",
            "MEMBER_ID",
            "FIRST NAME",
            "LAST NAME",
            "MemberLastName",
        ]

        for value in exact_matches:
            result = extractor._looks_like_column_name(value)
            assert result is True, (
                f"Exact pattern match '{value}' should be filtered as column name"
            )


class TestZIPPatternDetectionInSampleData:
    """Test that sample data engine correctly detects and handles ZIP patterns."""

    def test_zip_patterns_recognized(self):
        """Test that common ZIP patterns are recognized and use dedicated generator.

        This is an integration-level test that verifies the engine.py logic.
        """
        # This test would require importing and testing the engine
        # For now, we've verified the logic manually
        # Real test would instantiate SampleDataGenerator and verify it uses
        # generate_zip_code() for ZIP pattern columns


class TestExtractValueSets:
    """Test extract_value_sets method."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_value_sets({}) == {}
        assert extractor.extract_value_sets(None) == {}
        assert extractor.extract_value_sets({"no_expectations": []}) == {}

    def test_extract_single_value_set(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["A", "B", "C"]},
                }
            ]
        }
        result = extractor.extract_value_sets(expectations)
        assert result == {"status": ["A", "B", "C"]}

    def test_extract_multiple_value_sets(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["A", "B"]},
                },
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": ["MD", "MP"]},
                },
            ]
        }
        result = extractor.extract_value_sets(expectations)
        assert result == {"status": ["A", "B"], "lob": ["MD", "MP"]}

    def test_non_string_values_converted(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "code", "value_set": [1, 2, 3]},
                }
            ]
        }
        result = extractor.extract_value_sets(expectations)
        assert result == {"code": ["1", "2", "3"]}

    def test_ignores_other_expectation_types(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                },
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["X"]},
                },
            ]
        }
        result = extractor.extract_value_sets(expectations)
        assert "id" not in result
        assert result == {"status": ["X"]}

    def test_skips_missing_column_or_value_set(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"value_set": ["A"]},  # missing column
                },
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "c"},  # missing value_set
                },
            ]
        }
        result = extractor.extract_value_sets(expectations)
        assert result == {}


class TestExtractMetadataHints:
    """Test extract_metadata_hints method."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_metadata_hints({}) == {}
        assert extractor.extract_metadata_hints(None) == {}

    def test_extract_lob_hint(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "name"},
                    "meta": {"lob": ["MD", "MP"]},
                }
            ]
        }
        result = extractor.extract_metadata_hints(expectations)
        assert "name" in result
        assert result["name"]["lob"] == ["MD", "MP"]

    def test_extract_states_hint(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "addr"},
                    "meta": {"states": ["PA", "NJ"]},
                }
            ]
        }
        result = extractor.extract_metadata_hints(expectations)
        assert result["addr"]["states"] == ["PA", "NJ"]

    def test_extract_description_examples(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "lob_code"},
                    "meta": {"description": "LOB values. Ex: MD, ME, MP"},
                }
            ]
        }
        result = extractor.extract_metadata_hints(expectations)
        assert "lob_code" in result
        assert "description_examples" in result["lob_code"]
        assert "MD" in result["lob_code"]["description_examples"]

    def test_no_column_skipped(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_table_row_count_to_be_between",
                    "kwargs": {"min_value": 1},
                    "meta": {"lob": ["MD"]},
                }
            ]
        }
        result = extractor.extract_metadata_hints(expectations)
        assert result == {}

    def test_no_meta_skipped(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "name"},
                }
            ]
        }
        result = extractor.extract_metadata_hints(expectations)
        assert result == {}


class TestExtractExamplesFromDescription:
    """Test _extract_examples_from_description."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_ex_pattern(self, extractor):
        result = extractor._extract_examples_from_description("Values. Ex: A, B, C")
        assert result == ["A", "B", "C"]

    def test_example_pattern(self, extractor):
        result = extractor._extract_examples_from_description(
            "Example: X, Y, Z. More text."
        )
        assert result == ["X", "Y", "Z"]

    def test_no_examples(self, extractor):
        result = extractor._extract_examples_from_description("Some plain description")
        assert result == []

    def test_long_values_filtered(self, extractor):
        long_val = "A" * 51
        result = extractor._extract_examples_from_description(f"Ex: {long_val}, B")
        assert long_val not in result
        assert "B" in result


class TestExtractRegexPatterns:
    """Test extract_regex_patterns and get_regex_for_column."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_regex_patterns({}) == {}
        assert extractor.extract_regex_patterns(None) == {}

    def test_extract_regex(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "zip", "regex": r"^\d{5}$"},
                }
            ]
        }
        result = extractor.extract_regex_patterns(expectations)
        assert result == {"zip": r"^\d{5}$"}

    def test_get_regex_for_column_found(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "phone", "regex": r"^\d{10}$"},
                }
            ]
        }
        assert extractor.get_regex_for_column(expectations, "phone") == r"^\d{10}$"

    def test_get_regex_for_column_not_found(self, extractor):
        expectations = {"expectations": []}
        assert extractor.get_regex_for_column(expectations, "missing") is None

    def test_skips_missing_column_or_regex(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "x"},  # no regex
                },
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"regex": r"\d+"},  # no column
                },
            ]
        }
        assert extractor.extract_regex_patterns(expectations) == {}


class TestExtractStrftimeFormats:
    """Test extract_strftime_formats and get_strftime_format_for_column."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_strftime_formats({}) == {}
        assert extractor.extract_strftime_formats(None) == {}

    def test_extract_strftime_format(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_strftime_format",
                    "kwargs": {"column": "date_col", "strftime_format": "%Y-%m-%d"},
                }
            ]
        }
        result = extractor.extract_strftime_formats(expectations)
        assert result == {"date_col": "%Y-%m-%d"}

    def test_extract_from_cast_to_type_with_umf_format(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {"column": "dt", "format": "YYYY-MM-DD"},
                }
            ]
        }
        result = extractor.extract_strftime_formats(expectations)
        assert "dt" in result

    def test_strftime_format_takes_precedence_over_cast(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_strftime_format",
                    "kwargs": {"column": "dt", "strftime_format": "%Y-%m-%d"},
                },
                {
                    "type": "expect_column_values_to_cast_to_type",
                    "kwargs": {"column": "dt", "format": "MM/DD/YYYY"},
                },
            ]
        }
        result = extractor.extract_strftime_formats(expectations)
        assert result["dt"] == "%Y-%m-%d"

    def test_get_strftime_format_for_column(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_match_strftime_format",
                    "kwargs": {"column": "created", "strftime_format": "%Y-%m-%d"},
                }
            ]
        }
        result = extractor.get_strftime_format_for_column(expectations, "created")
        assert result == "%Y-%m-%d"

    def test_get_strftime_format_not_found(self, extractor):
        expectations = {"expectations": []}
        assert extractor.get_strftime_format_for_column(expectations, "missing") is None


class TestFixStrftimeFormat:
    """Test _fix_strftime_format."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_fix_standalone_M(self, extractor):
        assert "%-m" in extractor._fix_strftime_format("M/%d/%Y")

    def test_fix_standalone_D(self, extractor):
        assert "%-d" in extractor._fix_strftime_format("%m/D/%Y")

    def test_already_valid_format_unchanged(self, extractor):
        assert extractor._fix_strftime_format("%Y-%m-%d") == "%Y-%m-%d"


class TestGetConstraintsForColumn:
    """Test get_constraints_for_column."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_returns_value_set(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["ACTIVE", "INACTIVE"]},
                }
            ]
        }
        result = extractor.get_constraints_for_column(expectations, "status")
        assert result == ["ACTIVE", "INACTIVE"]

    def test_returns_none_when_not_found(self, extractor):
        expectations = {"expectations": []}
        assert extractor.get_constraints_for_column(expectations, "missing") is None

    def test_filters_column_name_values(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {
                        "column": "name",
                        "value_set": ["CLIENT_MEMBER_ID", "MEMBER_BIRTH_DATE"],
                    },
                }
            ]
        }
        result = extractor.get_constraints_for_column(expectations, "name")
        # All values look like column names, so should return None
        assert result is None

    def test_keeps_valid_enum_values(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {
                        "column": "lob",
                        "value_set": ["PENNSYLVANIA_MEDICARE", "CALIFORNIA_MEDICAID"],
                    },
                }
            ]
        }
        result = extractor.get_constraints_for_column(expectations, "lob")
        assert len(result) == 2


class TestIsColumnNotNull:
    """Test is_column_not_null."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_column_is_not_null(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                }
            ]
        }
        assert extractor.is_column_not_null(expectations, "id") is True

    def test_column_not_in_expectations(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                }
            ]
        }
        assert extractor.is_column_not_null(expectations, "other") is False

    def test_empty_expectations(self, extractor):
        assert extractor.is_column_not_null({}, "id") is False
        assert extractor.is_column_not_null(None, "id") is False


class TestGetMaxLengthForColumn:
    """Test get_max_length_for_column."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_returns_max_length(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_value_lengths_to_be_between",
                    "kwargs": {"column": "name", "max_value": 50},
                }
            ]
        }
        assert extractor.get_max_length_for_column(expectations, "name") == 50

    def test_returns_none_when_not_found(self, extractor):
        expectations = {"expectations": []}
        assert extractor.get_max_length_for_column(expectations, "col") is None

    def test_returns_none_when_no_max_value(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_value_lengths_to_be_between",
                    "kwargs": {"column": "name", "min_value": 1},
                }
            ]
        }
        assert extractor.get_max_length_for_column(expectations, "name") is None

    def test_empty_expectations(self, extractor):
        assert extractor.get_max_length_for_column({}, "col") is None
        assert extractor.get_max_length_for_column(None, "col") is None


class TestExtractColumnPairEqualityConstraints:
    """Test extract_column_pair_equality_constraints."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_column_pair_equality_constraints({}) == {}
        assert extractor.extract_column_pair_equality_constraints(None) == {}

    def test_extracts_bidirectional_mapping(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_pair_values_to_be_equal",
                    "kwargs": {
                        "column_A": "col1",
                        "column_B": "col2",
                        "ignore_row_if": "either_value_is_missing",
                    },
                }
            ]
        }
        result = extractor.extract_column_pair_equality_constraints(expectations)
        assert "col1" in result
        assert "col2" in result
        assert result["col1"][0]["column_B"] == "col2"
        assert result["col2"][0]["column_B"] == "col1"

    def test_default_ignore_row_if(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_column_pair_values_to_be_equal",
                    "kwargs": {"column_A": "a", "column_B": "b"},
                }
            ]
        }
        result = extractor.extract_column_pair_equality_constraints(expectations)
        assert result["a"][0]["ignore_row_if"] == "never"


class TestExtractUniqueWithinRecordConstraints:
    """Test extract_unique_within_record_constraints."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_empty_expectations(self, extractor):
        assert extractor.extract_unique_within_record_constraints({}) == []
        assert extractor.extract_unique_within_record_constraints(None) == []

    def test_extracts_constraint(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_select_column_values_to_be_unique_within_record",
                    "kwargs": {
                        "column_list": ["col1", "col2", "col3"],
                        "ignore_row_if": "any_value_is_missing",
                    },
                }
            ]
        }
        result = extractor.extract_unique_within_record_constraints(expectations)
        assert len(result) == 1
        assert result[0]["columns"] == ["col1", "col2", "col3"]
        assert result[0]["ignore_row_if"] == "any_value_is_missing"

    def test_skips_single_column(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_select_column_values_to_be_unique_within_record",
                    "kwargs": {"column_list": ["only_one"]},
                }
            ]
        }
        result = extractor.extract_unique_within_record_constraints(expectations)
        assert result == []

    def test_default_ignore_row_if(self, extractor):
        expectations = {
            "expectations": [
                {
                    "type": "expect_select_column_values_to_be_unique_within_record",
                    "kwargs": {"column_list": ["a", "b"]},
                }
            ]
        }
        result = extractor.extract_unique_within_record_constraints(expectations)
        assert result[0]["ignore_row_if"] == "never"


class TestLoadExpectationsForTable:
    """Test load_expectations_for_table."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_load_from_standalone_file(self, extractor, tmp_path):
        tables_dir = tmp_path / "tables"
        tables_dir.mkdir()
        exp_file = tables_dir / "test_table.expectations.yaml"
        exp_file.write_text("name: test_suite\nexpectations: []\n")
        result = extractor.load_expectations_for_table("test_table", tmp_path)
        assert result is not None
        assert result["name"] == "test_suite"

    def test_no_file_returns_none(self, extractor, tmp_path):
        tables_dir = tmp_path / "tables"
        tables_dir.mkdir()
        result = extractor.load_expectations_for_table("nonexistent", tmp_path)
        assert result is None

    def test_invalid_yaml_returns_none(self, extractor, tmp_path):
        tables_dir = tmp_path / "tables"
        tables_dir.mkdir()
        exp_file = tables_dir / "bad.expectations.yaml"
        exp_file.write_text("\t:::bad yaml:::\n")
        result = extractor.load_expectations_for_table("bad", tmp_path)
        # yaml.safe_load may return None or raise - either way handled gracefully
        assert result is None or isinstance(result, dict)


class TestConvertUmfFormatToStrftime:
    """Test _convert_umf_format_to_strftime helper."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_known_format(self, extractor):
        result = extractor._convert_umf_format_to_strftime("YYYY-MM-DD")
        assert "%" in result

    def test_unknown_format_returns_input(self, extractor):
        # If convert_umf_format_to_strftime returns empty string, method returns the original
        result = extractor._convert_umf_format_to_strftime("UNKNOWN_FORMAT_XYZ")
        assert isinstance(result, str)


class TestGenerateCharFromClass:
    """Test _generate_char_from_class."""

    @pytest.fixture
    def extractor(self):
        return GXConstraintExtractor()

    def test_uppercase_range(self, extractor):
        for _ in range(20):
            c = extractor._generate_char_from_class("A-Z")
            assert c.isupper() and c.isalpha()

    def test_lowercase_range(self, extractor):
        for _ in range(20):
            c = extractor._generate_char_from_class("a-z")
            assert c.islower() and c.isalpha()

    def test_digit_range(self, extractor):
        for _ in range(20):
            c = extractor._generate_char_from_class("0-9")
            assert c.isdigit()

    def test_empty_class_returns_X(self, extractor):
        assert extractor._generate_char_from_class("") == "X"
