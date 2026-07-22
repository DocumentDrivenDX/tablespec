"""Tests for GX schema validator - expectation type validation, schema checks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tablespec.gx_schema_validator import GXSchemaValidator


class TestGenerateMinimalKwargs:
    """Test _generate_minimal_kwargs for various expectation type patterns."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_column_pair_expectation(self, validator):
        """Column pair expectations need column_A and column_B."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_pair_values_to_be_equal"
        )
        assert kwargs["column_A"] == "col_a"
        assert kwargs["column_B"] == "col_b"

    def test_compound_columns_expectation(self, validator):
        """Compound column expectations need column_list."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_compound_columns_to_be_unique"
        )
        assert kwargs["column_list"] == ["col1", "col2"]

    def test_multicolumn_expectation(self, validator):
        """Multicolumn expectations need column_list."""
        kwargs = validator._generate_minimal_kwargs("expect_multicolumn_sum_to_equal")
        assert kwargs["column_list"] == ["col1", "col2"]

    def test_select_column_expectation(self, validator):
        """Select column expectations need column_list."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_select_column_values_to_be_unique_within_record"
        )
        assert kwargs["column_list"] == ["col1", "col2"]

    def test_column_expectation(self, validator):
        """Standard column expectations need a single column."""
        kwargs = validator._generate_minimal_kwargs("expect_column_to_exist")
        assert kwargs["column"] == "test_col"

    def test_table_match_ordered_list(self, validator):
        """Table ordered list needs column_list."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_table_columns_to_match_ordered_list"
        )
        assert kwargs["column_list"] == ["col1", "col2"]

    def test_table_match_set(self, validator):
        """Table match set needs column_set."""
        kwargs = validator._generate_minimal_kwargs("expect_table_columns_to_match_set")
        assert kwargs["column_set"] == ["col1", "col2"]

    def test_table_column_count(self, validator):
        """Table column count needs value."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_table_column_count_to_equal"
        )
        assert kwargs["value"] == 5

    def test_table_basic(self, validator):
        """Basic table expectation has no column kwargs."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_table_row_count_to_be_between"
        )
        # Should have between kwargs
        assert "min_value" in kwargs
        assert "max_value" in kwargs

    def test_in_set_expectation(self, validator):
        """In-set expectations need value_set."""
        kwargs = validator._generate_minimal_kwargs("expect_column_values_to_be_in_set")
        assert kwargs["value_set"] == ["A", "B", "C"]

    def test_in_type_list_expectation(self, validator):
        """In type list expectations need type_list."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_be_in_type_list"
        )
        assert kwargs["type_list"] == ["INTEGER", "STRING"]

    def test_match_regex_expectation(self, validator):
        """Match regex expectations need regex."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_match_regex"
        )
        assert kwargs["regex"] == "^[A-Z]+$"

    def test_match_regex_list_expectation(self, validator):
        """Match regex list expectations need regex_list."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_match_regex_list"
        )
        assert kwargs["regex_list"] == ["^[A-Z]+$", "^\\d+$"]

    def test_between_expectation(self, validator):
        """Between expectations need min and max."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_be_between"
        )
        assert kwargs["min_value"] == 0
        assert kwargs["max_value"] == 100

    def test_strftime_expectation(self, validator):
        """Strftime expectations need strftime_format."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_match_strftime_format"
        )
        assert kwargs["strftime_format"] == "%Y-%m-%d"

    def test_of_type_expectation(self, validator):
        """Of-type expectations need type_."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_be_of_type"
        )
        assert kwargs["type_"] == "INTEGER"

    def test_value_lengths_equal(self, validator):
        """Value lengths equal expectations need value."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_value_lengths_to_equal"
        )
        assert kwargs["value"] == 10

    def test_json_schema_expectation(self, validator):
        """JSON schema expectations need json_schema."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_values_to_match_json_schema"
        )
        assert kwargs["json_schema"] == {"type": "object"}

    def test_z_scores_expectation(self, validator):
        """Z-scores expectations need threshold."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_value_z_scores_to_be_less_than"
        )
        assert kwargs["threshold"] == 3

    def test_kl_divergence_expectation(self, validator):
        """KL divergence expectations need partition_object and threshold."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_column_kl_divergence_to_be_less_than"
        )
        assert "partition_object" in kwargs
        assert kwargs["threshold"] == 0.1

    def test_equal_other_table(self, validator):
        """Equal other table expectations need other_table_name."""
        kwargs = validator._generate_minimal_kwargs(
            "expect_table_row_count_to_equal_other_table"
        )
        assert kwargs["other_table_name"] == "other_table"


class TestValidateExpectationType:
    """Test validate_expectation_type method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_pending_implementation_is_valid_with_mocked_gx(self, validator):
        """Pending implementation should return True when GX is available."""
        import types

        mock_suite_mod = types.ModuleType("great_expectations.core.expectation_suite")
        mock_suite_mod.ExpectationSuite = MagicMock()
        mock_config_mod = types.ModuleType(
            "great_expectations.expectations.expectation_configuration"
        )
        mock_config_mod.ExpectationConfiguration = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "great_expectations.core.expectation_suite": mock_suite_mod,
                "great_expectations.expectations.expectation_configuration": mock_config_mod,
            },
        ):
            is_valid, error = validator.validate_expectation_type(
                "expect_validation_rule_pending_implementation"
            )
        assert is_valid is True
        assert error is None

    def test_validates_known_expectation_type(self, validator):
        """Should return True for a valid, known expectation type when GX is available."""
        is_valid, error = validator.validate_expectation_type("expect_column_to_exist")
        assert is_valid is True
        assert error is None


class TestValidateAllTypesInSchema:
    """Test validate_all_types_in_schema method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_validates_schema_types(self, validator, tmp_path):
        """Should validate all expectation types in a schema file."""
        schema = {
            "properties": {
                "expectations": {
                    "items": {
                        "properties": {
                            "type": {
                                "enum": [
                                    "expect_column_to_exist",
                                    "bad_expectation_type",
                                ]
                            }
                        }
                    }
                }
            }
        }
        schema_path = tmp_path / "test_schema.json"
        schema_path.write_text(json.dumps(schema))

        # Mock validate_expectation_type to control results
        with patch.object(
            validator,
            "validate_expectation_type",
            side_effect=lambda t: (True, None)
            if t == "expect_column_to_exist"
            else (False, "not registered"),
        ):
            results = validator.validate_all_types_in_schema(schema_path)

        assert results["total"] == 2
        assert "expect_column_to_exist" in results["valid"]
        assert len(results["invalid"]) == 1
        assert results["invalid"][0]["type"] == "bad_expectation_type"


class TestGenerateCorrectedSchema:
    """Test generate_corrected_schema method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_generates_corrected_schema(self, validator, tmp_path):
        """Should write schema with only valid expectation types."""
        original_schema = {
            "properties": {
                "expectations": {
                    "items": {
                        "properties": {"type": {"enum": ["type_a", "type_b", "type_c"]}}
                    }
                }
            }
        }
        schema_path = tmp_path / "original.json"
        schema_path.write_text(json.dumps(original_schema))

        output_path = tmp_path / "corrected.json"

        validation_results = {
            "valid": ["type_a", "type_c"],
            "invalid": [{"type": "type_b", "error": "not supported"}],
        }

        validator.generate_corrected_schema(
            schema_path, output_path, validation_results
        )

        with output_path.open() as f:
            corrected = json.load(f)

        enum_types = corrected["properties"]["expectations"]["items"]["properties"][
            "type"
        ]["enum"]
        assert sorted(enum_types) == ["type_a", "type_c"]


class TestValidateExpectationJson:
    """Test validate_expectation_json method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    @pytest.fixture
    def simple_schema(self):
        """A minimal JSON schema for expectations."""
        return {
            "properties": {
                "expectations": {
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "kwargs": {"type": "object"},
                        },
                        "required": ["type", "kwargs"],
                    }
                }
            }
        }

    def test_valid_expectation_json(self, validator, simple_schema):
        """Should validate correct expectation JSON."""
        exp = {"type": "expect_column_to_exist", "kwargs": {"column": "test"}}
        is_valid, errors = validator.validate_expectation_json(exp, simple_schema)
        assert is_valid is True
        assert errors == []

    def test_invalid_expectation_json_missing_required(self, validator, simple_schema):
        """Should report error for missing required fields."""
        exp = {"type": "expect_column_to_exist"}  # missing kwargs
        is_valid, errors = validator.validate_expectation_json(exp, simple_schema)
        assert is_valid is False
        assert len(errors) > 0
        assert "JSON schema validation error" in errors[0]


class TestValidateSuiteAgainstSchema:
    """Test validate_suite_against_schema method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_valid_suite(self, validator):
        """Should validate a conforming suite."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "expectations": {"type": "array"},
            },
            "required": ["name", "expectations"],
        }
        suite = {"name": "test", "expectations": []}
        is_valid, errors = validator.validate_suite_against_schema(suite, schema)
        assert is_valid is True
        assert errors == []

    def test_invalid_suite(self, validator):
        """Should report errors for non-conforming suite."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "expectations": {"type": "array"},
            },
            "required": ["name", "expectations"],
        }
        suite = {"expectations": []}  # missing name
        is_valid, errors = validator.validate_suite_against_schema(suite, schema)
        assert is_valid is False
        assert len(errors) > 0
        assert "JSON schema validation error" in errors[0]


class TestGenerateCompleteExpectationSuite:
    """Test generate_complete_expectation_suite method."""

    @pytest.fixture
    def validator(self):
        return GXSchemaValidator()

    def test_generates_suite_with_all_types(self, validator, tmp_path):
        """Should generate suite containing all non-pending expectation types."""
        schema = {
            "properties": {
                "expectations": {
                    "items": {
                        "properties": {
                            "type": {
                                "enum": [
                                    "expect_column_to_exist",
                                    "expect_validation_rule_pending_implementation",
                                    "expect_column_values_to_not_be_null",
                                ]
                            }
                        }
                    }
                }
            }
        }
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(schema))

        suite = validator.generate_complete_expectation_suite(schema_path)

        assert suite["name"] == "complete_validation_suite"
        assert "meta" in suite

        exp_types = [e["type"] for e in suite["expectations"]]
        # Pending should be skipped
        assert "expect_validation_rule_pending_implementation" not in exp_types
        assert "expect_column_to_exist" in exp_types
        assert "expect_column_values_to_not_be_null" in exp_types

        # Each expectation should have kwargs and meta
        for exp in suite["expectations"]:
            assert "kwargs" in exp
            assert "meta" in exp
            assert "severity" in exp["meta"]
            assert "description" in exp["meta"]
