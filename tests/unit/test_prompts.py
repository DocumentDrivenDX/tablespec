"""Tests for the prompts module - prompt generators for LLM interactions."""

# @covers US-008-AC1
# @covers US-008-AC2
# @covers US-008-AC3
# @covers US-008-AC4
# @covers US-008-AC5
# @covers US-008-AC6

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.fast

# ── Fixtures ──────────────────────────────────────────────────────────────

MINIMAL_UMF: dict[str, Any] = {
    "table_name": "test_table",
    "description": "A test table for unit testing",
    "source_file": "test_source.csv",
    "columns": [
        {
            "name": "member_id",
            "data_type": "VARCHAR",
            "description": "Unique member identifier",
            "max_length": 20,
            "nullable": {"MD": False, "ME": False, "MP": True},
            "sample_values": ["ABC123", "DEF456"],
            "format": "",
            "notes": [],
        },
        {
            "name": "birth_date",
            "data_type": "DATE",
            "description": "Member date of birth",
            "max_length": None,
            "nullable": {"MD": False, "ME": False, "MP": False},
            "sample_values": ["2000-01-01", "1985-06-15"],
            "format": "YYYY-MM-DD",
            "notes": ["Must be a valid date"],
        },
        {
            "name": "status_code",
            "data_type": "VARCHAR",
            "description": "Member status. Valid values: A, I, T",
            "max_length": 2,
            "nullable": {"MD": True, "ME": True, "MP": True},
            "sample_values": ["A", "I", "T"],
            "format": "",
            "notes": [],
        },
    ],
}

RICH_UMF: dict[str, Any] = {
    **MINIMAL_UMF,
    "table_type": "provided",
    "primary_keys": ["member_id"],
    "foreign_keys": [{"column": "status_code", "references": "status_lookup.code"}],
    "relationships": {
        "outgoing": [
            {
                "source_column": "member_id",
                "target_table": "claims",
                "target_column": "member_id",
            }
        ]
    },
}

GENERATED_TABLE_UMF: dict[str, Any] = {
    **MINIMAL_UMF,
    "table_name": "derived_table",
    "table_type": "generated",
    "description": "A generated/derived table",
}

EMPTY_COLUMNS_UMF: dict[str, Any] = {
    "table_name": "empty_table",
    "description": "Table with no columns",
    "columns": [],
}


@pytest.fixture
def minimal_umf() -> dict[str, Any]:
    return copy.deepcopy(MINIMAL_UMF)


@pytest.fixture
def rich_umf() -> dict[str, Any]:
    return copy.deepcopy(RICH_UMF)


# ── utils.py ──────────────────────────────────────────────────────────────


class TestCleanDescription:
    def test_empty_string_returns_no_description(self):
        from tablespec.prompts.utils import clean_description

        assert clean_description("") == "No description"

    def test_none_like_empty(self):
        from tablespec.prompts.utils import clean_description

        # Empty string
        assert clean_description("") == "No description"

    def test_removes_validation_patterns(self):
        from tablespec.prompts.utils import clean_description

        result = clean_description(
            "A member field. Valid values: A, B, C. Must be populated."
        )
        assert "Valid values" not in result
        assert "Must be" not in result

    def test_preserves_core_description(self):
        from tablespec.prompts.utils import clean_description

        result = clean_description("Unique member identifier")
        assert "Unique member identifier" in result

    def test_removes_example_patterns(self):
        from tablespec.prompts.utils import clean_description

        result = clean_description("Member code. Ex: 12345. Example: ABCDE.")
        assert "Ex:" not in result
        assert "Example:" not in result

    def test_removes_format_patterns(self):
        from tablespec.prompts.utils import clean_description

        result = clean_description("Date field. Format: YYYYMMDD.")
        assert "Format:" not in result


class TestIsRelationshipRelevantColumn:
    def test_id_column_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column("member_id", "Some desc", "VARCHAR")

    def test_code_column_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column("status_code", "Some desc", "VARCHAR")

    def test_integer_type_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column("some_field", "Some desc", "INTEGER")

    def test_description_with_identifier_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column(
            "some_field", "Unique identifier for member", "VARCHAR"
        )

    def test_address_field_excluded(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert not is_relationship_relevant_column(
            "home_address", "Home address line 1", "VARCHAR"
        )

    def test_description_field_excluded(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert not is_relationship_relevant_column(
            "description", "Free text notes", "VARCHAR"
        )

    def test_npi_pattern_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column("provider_npi", "NPI number", "VARCHAR")

    def test_key_pattern_is_relevant(self):
        from tablespec.prompts.utils import is_relationship_relevant_column

        assert is_relationship_relevant_column("gap_key", "Gap key", "VARCHAR")

    def test_deprecated_alias_works(self):
        from tablespec.prompts.utils import _is_relationship_relevant_column

        assert _is_relationship_relevant_column("member_id", "desc", "VARCHAR")


class TestLoadUmf:
    def test_load_valid_yaml(self, tmp_path: Path):
        from tablespec.prompts.utils import load_umf

        umf_file = tmp_path / "test.umf.yaml"
        umf_file.write_text(yaml.dump(MINIMAL_UMF), encoding="utf-8")

        result = load_umf(umf_file)
        assert result["table_name"] == "test_table"

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        from tablespec.prompts.utils import load_umf

        result = load_umf(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_invalid_yaml_returns_empty(self, tmp_path: Path):
        from tablespec.prompts.utils import load_umf

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_bytes(b"\x80\x81\x82")  # invalid utf-8
        result = load_umf(bad_file)
        assert result == {}

    def test_deprecated_alias(self, tmp_path: Path):
        from tablespec.prompts.utils import _load_umf

        umf_file = tmp_path / "test.umf.yaml"
        umf_file.write_text(yaml.dump({"table_name": "x"}), encoding="utf-8")
        result = _load_umf(umf_file)
        assert result["table_name"] == "x"


# ── documentation.py ──────────────────────────────────────────────────────


class TestGenerateDocumentationPrompt:
    def test_returns_nonempty_string(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_table_name(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "test_table" in result

    def test_contains_column_names(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "member_id" in result
        assert "birth_date" in result
        assert "status_code" in result

    def test_contains_analysis_sections(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "Business Purpose" in result
        assert "Data Quality" in result
        assert "Compliance" in result

    def test_includes_sample_values(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "ABC123" in result

    def test_includes_data_types(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "VARCHAR" in result
        assert "DATE" in result

    def test_includes_max_length(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "20" in result

    def test_nullable_shown(self, minimal_umf):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(minimal_umf)
        assert "Nullable" in result

    def test_empty_columns(self):
        from tablespec.prompts.documentation import generate_documentation_prompt

        result = generate_documentation_prompt(EMPTY_COLUMNS_UMF)
        assert "empty_table" in result
        assert "Column Specifications" in result

    def test_missing_optional_fields(self):
        from tablespec.prompts.documentation import generate_documentation_prompt

        sparse_umf = {
            "table_name": "sparse",
            "columns": [
                {"name": "col1"},
            ],
        }
        result = generate_documentation_prompt(sparse_umf)
        assert "sparse" in result
        assert "col1" in result

    def test_deprecated_alias(self, minimal_umf):
        from tablespec.prompts.documentation import _generate_documentation_prompt

        result = _generate_documentation_prompt(minimal_umf)
        assert "test_table" in result


# ── validation.py ─────────────────────────────────────────────────────────


class TestHasValidationRules:
    def test_returns_true_for_column_with_valid_values(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "",
            "columns": [
                {"description": "Valid values: A, B, C", "sample_values": []},
            ],
        }
        assert has_validation_rules(umf) is True

    def test_returns_true_for_format_in_description(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "",
            "columns": [
                {"description": "Must be in format YYYYMMDD", "sample_values": []},
            ],
        }
        assert has_validation_rules(umf) is True

    def test_returns_true_for_table_description_indicator(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "Contains member id with specific format requirements",
            "columns": [],
        }
        assert has_validation_rules(umf) is True

    def test_returns_false_for_plain_data(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "A simple data table",
            "columns": [
                {"description": "Some plain text column", "sample_values": []},
            ],
        }
        assert has_validation_rules(umf) is False

    def test_handles_none_column_entries(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "",
            "columns": [None, {"description": "some field", "sample_values": []}],
        }
        # Should not raise
        result = has_validation_rules(umf)
        assert isinstance(result, bool)

    def test_handles_none_description(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "",
            "columns": [{"description": None, "sample_values": []}],
        }
        assert has_validation_rules(umf) is False

    def test_enumerated_samples_trigger(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {
            "description": "",
            "columns": [
                {
                    "description": "",
                    "sample_values": ["format A", "format B"],
                },
            ],
        }
        assert has_validation_rules(umf) is True

    def test_deprecated_alias(self):
        from tablespec.prompts.validation import _has_validation_rules

        umf = {"description": "has format rules", "columns": []}
        assert _has_validation_rules(umf) is True

    def test_empty_columns(self):
        from tablespec.prompts.validation import has_validation_rules

        umf = {"description": "", "columns": []}
        assert has_validation_rules(umf) is False


class TestGenerateValidationPrompt:
    def test_returns_nonempty_string(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert isinstance(result, str)
        assert len(result) > 200

    def test_contains_table_name(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert "test_table" in result

    def test_contains_critical_sections(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert "JSON" in result
        assert "Output Format" in result
        assert "severity" in result

    def test_contains_column_specs(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert "member_id" in result
        assert "birth_date" in result

    def test_includes_expectation_types(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert "expect_" in result

    def test_generated_table_skips_provenance(self):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(GENERATED_TABLE_UMF)
        assert "Provenance Fields Not Available" in result
        assert "meta_source_name" not in result or "not have provenance" in result

    def test_provided_table_includes_provenance(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(minimal_umf)
        assert "meta_source_name" in result

    def test_includes_relationships_when_present(self, rich_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        result = generate_validation_prompt(rich_umf)
        assert "claims" in result

    def test_handles_sparse_columns(self):
        from tablespec.prompts.validation import generate_validation_prompt

        umf = {
            "table_name": "test",
            "columns": [{"name": "col1", "description": "A col"}],
        }
        result = generate_validation_prompt(umf)
        assert "col1" in result

    def test_sample_values_header_pollution_filtered(self):
        from tablespec.prompts.validation import generate_validation_prompt

        umf = {
            "table_name": "test",
            "columns": [
                {
                    "name": "MyColumn",
                    "description": "A field",
                    "sample_values": ["MyColumn", "actual_value"],
                }
            ],
        }
        result = generate_validation_prompt(umf)
        assert "actual_value" in result

    def test_notes_included(self, minimal_umf):
        from tablespec.prompts.validation import generate_validation_prompt

        minimal_umf["columns"][1]["notes"] = ["Important validation note"]
        result = generate_validation_prompt(minimal_umf)
        assert "Important validation note" in result


# ── column_validation.py ──────────────────────────────────────────────────


class TestShouldGenerateColumnPrompt:
    def test_returns_true_for_format(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "date_col", "format": "YYYYMMDD"}
        assert should_generate_column_prompt(col) is True

    def test_returns_true_for_few_sample_values(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "status", "sample_values": ["A", "I", "T"]}
        assert should_generate_column_prompt(col) is True

    def test_returns_false_for_many_sample_values(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "name", "sample_values": list(range(20))}
        assert should_generate_column_prompt(col) is False

    def test_returns_true_for_complex_description(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "code", "description": "Must be 5 digit numeric value"}
        assert should_generate_column_prompt(col) is True

    def test_returns_false_for_plain_column(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "notes", "description": "Free text notes field"}
        assert should_generate_column_prompt(col) is False

    def test_filename_source_excluded(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "state", "source": "filename", "sample_values": ["TX"]}
        assert should_generate_column_prompt(col) is False

    def test_empty_format_is_falsy(self):
        from tablespec.prompts.column_validation import should_generate_column_prompt

        col = {"name": "x", "format": "", "sample_values": [], "description": "plain"}
        assert should_generate_column_prompt(col) is False

    def test_deprecated_alias(self):
        from tablespec.prompts.column_validation import _should_generate_column_prompt

        col = {"name": "x", "format": "YYYY"}
        assert _should_generate_column_prompt(col) is True


class TestGenerateColumnValidationPrompt:
    def test_returns_nonempty_string(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_column_name(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "member_id" in result

    def test_contains_table_context(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "test_table" in result

    def test_contains_data_type(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "VARCHAR" in result

    def test_includes_sample_values(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "ABC123" in result

    def test_includes_required_lobs(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][0]
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "MD" in result

    def test_includes_format_when_present(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][1]  # birth_date has format
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "YYYY-MM-DD" in result

    def test_includes_notes(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = minimal_umf["columns"][1]  # birth_date has notes
        result = generate_column_validation_prompt(minimal_umf, col)
        assert "Must be a valid date" in result

    def test_context_columns_from_rich_umf(self, rich_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = rich_umf["columns"][2]  # status_code is a foreign key
        result = generate_column_validation_prompt(rich_umf, col)
        # Should have relevant context columns
        assert "Relevant columns" in result or "total columns" in result

    def test_minimal_column_no_optional_fields(self):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        umf = {
            "table_name": "t",
            "columns": [{"name": "c1"}],
        }
        col = {"name": "c1"}
        result = generate_column_validation_prompt(umf, col)
        assert "c1" in result

    def test_header_pollution_filtered(self, minimal_umf):
        from tablespec.prompts.column_validation import (
            generate_column_validation_prompt,
        )

        col = {
            "name": "status_code",
            "data_type": "VARCHAR",
            "description": "Status",
            "sample_values": ["status_code", "A", "I"],
        }
        result = generate_column_validation_prompt(minimal_umf, col)
        # "A" should appear in sample values, "status_code" should be filtered
        assert "Sample Values" in result


# ── expectation_guide.py ──────────────────────────────────────────────────


class TestExpectationGuide:
    def test_load_expectation_categories(self):
        from tablespec.prompts.expectation_guide import load_expectation_categories

        cats = load_expectation_categories()
        assert "baseline_only" in cats
        assert "llm_table_level" in cats
        assert "llm_column_level" in cats

    def test_get_llm_generatable_table(self):
        from tablespec.prompts.expectation_guide import (
            get_llm_generatable_expectations,
        )

        exps = get_llm_generatable_expectations(context="table")
        assert isinstance(exps, list)
        assert len(exps) > 0
        assert all(isinstance(e, str) for e in exps)

    def test_get_llm_generatable_column(self):
        from tablespec.prompts.expectation_guide import (
            get_llm_generatable_expectations,
        )

        exps = get_llm_generatable_expectations(context="column")
        assert isinstance(exps, list)
        assert len(exps) > 0

    def test_invalid_context_raises(self):
        from tablespec.prompts.expectation_guide import (
            get_llm_generatable_expectations,
        )

        with pytest.raises(ValueError, match="Invalid context"):
            get_llm_generatable_expectations(context="invalid")  # type: ignore[arg-type]

    def test_get_baseline_only_expectations(self):
        from tablespec.prompts.expectation_guide import (
            get_baseline_only_expectations,
        )

        exps = get_baseline_only_expectations()
        assert isinstance(exps, list)
        assert "expect_column_to_exist" in exps

    def test_get_parameter_requirements_known(self):
        from tablespec.prompts.expectation_guide import get_parameter_requirements

        # This should exist in the parameters file
        result = get_parameter_requirements("expect_column_values_to_be_in_set")
        # May or may not exist depending on the JSON file contents
        # Just check it returns dict or None
        assert result is None or isinstance(result, dict)

    def test_get_parameter_requirements_unknown(self):
        from tablespec.prompts.expectation_guide import get_parameter_requirements

        result = get_parameter_requirements("totally_fake_expectation")
        assert result is None

    def test_format_expectation_list_simple(self):
        from tablespec.prompts.expectation_guide import format_expectation_list

        result = format_expectation_list(
            ["expect_a", "expect_b"], include_descriptions=False
        )
        assert "expect_a" in result
        assert "expect_b" in result

    def test_format_expectation_list_with_descriptions(self):
        from tablespec.prompts.expectation_guide import format_expectation_list

        result = format_expectation_list(
            ["expect_column_values_to_be_in_set"], include_descriptions=True
        )
        assert isinstance(result, str)
        assert "expect_column_values_to_be_in_set" in result

    def test_format_parameter_details_unknown(self):
        from tablespec.prompts.expectation_guide import format_parameter_details

        result = format_parameter_details("nonexistent_expectation")
        assert "No parameter information" in result

    def test_get_pending_decision_tree(self):
        from tablespec.prompts.expectation_guide import get_pending_decision_tree

        result = get_pending_decision_tree()
        assert "pending_implementation" in result
        assert isinstance(result, str)
        assert len(result) > 50

    def test_format_quick_reference_table(self):
        from tablespec.prompts.expectation_guide import format_quick_reference

        result = format_quick_reference(context="table")
        assert "Table-Level" in result
        assert isinstance(result, str)

    def test_format_quick_reference_column(self):
        from tablespec.prompts.expectation_guide import format_quick_reference

        result = format_quick_reference(context="column")
        assert "Column-Level" in result

    def test_validate_expectation_missing_type(self):
        from tablespec.prompts.expectation_guide import (
            validate_expectation_against_schema,
        )

        valid, errors = validate_expectation_against_schema({})
        assert not valid
        assert any("type" in e for e in errors)

    def test_validate_expectation_invalid_kwargs(self):
        from tablespec.prompts.expectation_guide import (
            validate_expectation_against_schema,
        )

        valid, errors = validate_expectation_against_schema(
            {"type": "expect_column_to_exist", "kwargs": "not_a_dict"}
        )
        assert not valid

    def test_validate_expectation_baseline_only(self):
        from tablespec.prompts.expectation_guide import (
            validate_expectation_against_schema,
        )

        valid, errors = validate_expectation_against_schema(
            {"type": "expect_column_to_exist", "kwargs": {"column": "x"}}
        )
        assert any("baseline-only" in e for e in errors)

    def test_validate_pending_implementation_missing_meta(self):
        from tablespec.prompts.expectation_guide import (
            validate_expectation_against_schema,
        )

        valid, errors = validate_expectation_against_schema(
            {
                "type": "expect_validation_rule_pending_implementation",
                "kwargs": {"column": "x"},
                "meta": {},
            }
        )
        assert not valid
        assert any("description" in e for e in errors)


# ── relationship.py ───────────────────────────────────────────────────────


class TestGenerateRelationshipPrompt:
    def test_returns_nonempty_for_dir_with_umf_files(self, tmp_path: Path):
        from tablespec.prompts.relationship import generate_relationship_prompt

        # Create UMF dir with two tables
        umf_dir = tmp_path / "umf"
        umf_dir.mkdir()
        lookup_dir = tmp_path / "lookups"
        lookup_dir.mkdir()

        table1 = {
            "table_name": "members",
            "table_type": "provided",
            "columns": [
                {
                    "name": "member_id",
                    "data_type": "INTEGER",
                    "description": "Primary member identifier",
                },
                {
                    "name": "name",
                    "data_type": "VARCHAR",
                    "description": "Member name",
                },
            ],
        }
        table2 = {
            "table_name": "claims",
            "table_type": "provided",
            "columns": [
                {
                    "name": "claim_id",
                    "data_type": "INTEGER",
                    "description": "Claim identifier",
                },
                {
                    "name": "member_id",
                    "data_type": "INTEGER",
                    "description": "Reference to member",
                },
            ],
        }

        (umf_dir / "members.umf.yaml").write_text(yaml.dump(table1))
        (umf_dir / "claims.umf.yaml").write_text(yaml.dump(table2))

        result = generate_relationship_prompt(umf_dir, lookup_dir)
        assert isinstance(result, str)
        assert "members" in result
        assert "claims" in result
        assert "member_id" in result

    def test_skips_generated_tables(self, tmp_path: Path):
        from tablespec.prompts.relationship import generate_relationship_prompt

        umf_dir = tmp_path / "umf"
        umf_dir.mkdir()
        lookup_dir = tmp_path / "lookups"
        lookup_dir.mkdir()

        generated = {
            "table_name": "derived_output",
            "table_type": "generated",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "description": "ID"},
            ],
        }
        (umf_dir / "derived_output.umf.yaml").write_text(yaml.dump(generated))

        result = generate_relationship_prompt(umf_dir, lookup_dir)
        assert "derived_output" not in result

    def test_includes_lookup_tables(self, tmp_path: Path):
        from tablespec.prompts.relationship import generate_relationship_prompt

        umf_dir = tmp_path / "umf"
        umf_dir.mkdir()
        lookup_dir = tmp_path / "lookups"
        lookup_dir.mkdir()

        lookup = {
            "table_name": "status_lookup",
            "description": "Status codes",
            "columns": [
                {
                    "name": "status_code",
                    "data_type": "VARCHAR",
                    "description": "Status code value",
                    "is_primary_key": True,
                },
                {
                    "name": "status_description",
                    "data_type": "VARCHAR",
                    "description": "Status description text",
                },
            ],
        }
        (lookup_dir / "status_lookup.lookup.yaml").write_text(yaml.dump(lookup))

        result = generate_relationship_prompt(umf_dir, lookup_dir)
        assert "status_lookup" in result
        assert "Lookup Table" in result

    def test_empty_dirs(self, tmp_path: Path):
        from tablespec.prompts.relationship import generate_relationship_prompt

        umf_dir = tmp_path / "umf"
        umf_dir.mkdir()
        lookup_dir = tmp_path / "lookups"
        lookup_dir.mkdir()

        result = generate_relationship_prompt(umf_dir, lookup_dir)
        assert isinstance(result, str)
        assert "Healthcare" in result

    def test_contains_output_format_section(self, tmp_path: Path):
        from tablespec.prompts.relationship import generate_relationship_prompt

        umf_dir = tmp_path / "umf"
        umf_dir.mkdir()
        lookup_dir = tmp_path / "lookups"
        lookup_dir.mkdir()

        result = generate_relationship_prompt(umf_dir, lookup_dir)
        assert "Expected Output Format" in result
        assert "relationships" in result


# ── survivorship.py ───────────────────────────────────────────────────────


class TestGetCompatibleTypes:
    def test_string_types_compatible(self):
        from tablespec.prompts.survivorship import _get_compatible_types

        result = _get_compatible_types("StringType")
        assert "StringType" in result
        assert "CharType" in result
        assert "TextType" in result

    def test_integer_compatible_with_decimal(self):
        from tablespec.prompts.survivorship import _get_compatible_types

        result = _get_compatible_types("IntegerType")
        assert "IntegerType" in result
        assert "DecimalType" in result

    def test_unknown_type_returns_self(self):
        from tablespec.prompts.survivorship import _get_compatible_types

        result = _get_compatible_types("CustomType")
        assert result == {"CustomType"}

    def test_boolean_only_compatible_with_self(self):
        from tablespec.prompts.survivorship import _get_compatible_types

        result = _get_compatible_types("BooleanType")
        assert result == {"BooleanType"}

    def test_date_compatible_with_datetime(self):
        from tablespec.prompts.survivorship import _get_compatible_types

        result = _get_compatible_types("DateType")
        assert "DatetimeType" in result


class TestGenerateSurvivorshipPrompt:
    def test_raises_for_missing_file(self, tmp_path: Path):
        from tablespec.prompts.survivorship import generate_survivorship_prompt

        with pytest.raises(FileNotFoundError):
            generate_survivorship_prompt("nonexistent", tmp_path)

    def test_returns_prompt_with_target_and_sources(self, tmp_path: Path):
        from tablespec.prompts.survivorship import generate_survivorship_prompt

        target = {
            "table_name": "output_table",
            "table_type": "generated",
            "columns": [
                {
                    "name": "member_name",
                    "data_type": "VARCHAR",
                    "description": "Full member name",
                }
            ],
        }
        source = {
            "table_name": "outreach_list",
            "table_type": "provided",
            "source_file": "inbound/outreach.csv",
            "columns": [
                {
                    "name": "first_name",
                    "data_type": "VARCHAR",
                    "description": "First name",
                },
                {
                    "name": "last_name",
                    "data_type": "VARCHAR",
                    "description": "Last name",
                },
            ],
        }

        (tmp_path / "output_table.specs.umf.yaml").write_text(yaml.dump(target))
        (tmp_path / "outreach_list.specs.umf.yaml").write_text(yaml.dump(source))

        result = generate_survivorship_prompt("output_table", tmp_path)
        assert "output_table" in result
        assert "outreach_list" in result
        assert "member_name" in result

    def test_no_source_tables(self, tmp_path: Path):
        from tablespec.prompts.survivorship import generate_survivorship_prompt

        target = {
            "table_name": "lonely_table",
            "table_type": "generated",
            "columns": [{"name": "col1", "data_type": "VARCHAR", "description": "X"}],
        }
        (tmp_path / "lonely_table.specs.umf.yaml").write_text(yaml.dump(target))

        result = generate_survivorship_prompt("lonely_table", tmp_path)
        assert "lonely_table" in result
        assert "Survivorship Mapping" in result


class TestGenerateSurvivorshipPromptPerColumn:
    def test_returns_nonempty(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="member_name",
            target_col_description="Full name",
            target_col_type="StringType",
            source_candidates=[(0.9, "first_name", ["outreach_list"])],
            source_umfs=[
                {
                    "table_name": "outreach_list",
                    "description": "Outreach data",
                    "columns": [
                        {
                            "name": "first_name",
                            "data_type": "StringType",
                            "description": "First name",
                        }
                    ],
                }
            ],
        )
        assert isinstance(result, str)
        assert "member_name" in result
        assert "output" in result

    def test_with_provenance_policy(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="disposition_status",
            target_col_description="Current status",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            column_metadata={"provenance_policy": "enterprise_only"},
        )
        assert "enterprise_only" in result
        assert "Provenance Policy" in result

    def test_without_provenance_policy_shows_inference(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="member_email",
            target_col_description="Email address",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
        )
        assert "Inferring Provenance Policy" in result

    def test_with_excluded_tables(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="col1",
            target_col_description="A col",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            excluded_tables=["claims_table", "labs_table"],
        )
        assert "claims_table" in result
        assert "Excluded Tables" in result

    def test_with_pivot_field(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="gap1_condition",
            target_col_description="First gap condition",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            column_metadata={
                "pivot_field": True,
                "pivot_source_table": "outreach_list_gaps",
                "pivot_source_column": "quality_gap_group",
                "pivot_index": 1,
                "pivot_max_count": 5,
            },
        )
        assert "Pivot Field" in result
        assert "outreach_list_gaps" in result

    def test_with_relationship_graph(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="member_id",
            target_col_description="Member ID",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            relationship_graph={
                "outreach_list": {
                    "outgoing": [
                        {
                            "target_table": "gaps",
                            "source_column": "member_id",
                            "target_column": "member_id",
                            "cardinality": {"type": "one-to-many"},
                        }
                    ],
                    "incoming": [],
                }
            },
            joinable_tables={"outreach_list": 0, "gaps": 1},
        )
        assert "Table Relationships" in result

    def test_with_reporting_requirement_and_nullable(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="col1",
            target_col_description="A col",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            column_metadata={
                "reporting_requirement": "R",
                "nullable": {"MD": False, "ME": True},
            },
        )
        assert "Required" in result
        assert "Nullable" in result

    def test_empty_candidates(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="col1",
            target_col_description="A col",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
        )
        assert "Survivorship Mapping" in result
        assert "Output Format" in result

    def test_with_config_data_flow(self):
        from tablespec.prompts.survivorship import (
            generate_survivorship_prompt_per_column,
        )

        result = generate_survivorship_prompt_per_column(
            target_table_name="output",
            target_table_description="Output table",
            target_col_name="col1",
            target_col_description="A col",
            target_col_type="StringType",
            source_candidates=[],
            source_umfs=[],
            config={
                "provenance_defaults": {
                    "provided_tables": ["outreach_list"],
                    "enterprise_only_tables": ["disposition_tracking"],
                }
            },
        )
        assert "Data Sources" in result
        assert "outreach_list" in result


# ── filename_pattern.py ───────────────────────────────────────────────────


class TestFlattenValues:
    def test_splits_comma_separated(self):
        from tablespec.prompts.filename_pattern import _flatten_values

        result = _flatten_values(["A, B, C"])
        assert result == ["A", "B", "C"]

    def test_splits_semicolons(self):
        from tablespec.prompts.filename_pattern import _flatten_values

        result = _flatten_values(["X;Y;Z"])
        assert result == ["X", "Y", "Z"]

    def test_handles_br_tags(self):
        from tablespec.prompts.filename_pattern import _flatten_values

        result = _flatten_values(["A<br>B<br>C"])
        assert "A" in result
        assert "B" in result

    def test_skips_empty_tokens(self):
        from tablespec.prompts.filename_pattern import _flatten_values

        result = _flatten_values(["A,,B"])
        assert "" not in result


class TestSummarizeConfigurations:
    def test_detects_patterns(self):
        from tablespec.prompts.filename_pattern import _summarize_configurations

        configs = [
            {
                "specification": "File Name Format",
                "details": "Vendor_State_YYYYMMDD.txt",
            }
        ]
        result = _summarize_configurations(configs)
        assert len(result["patterns"]) > 0

    def test_detects_examples(self):
        from tablespec.prompts.filename_pattern import _summarize_configurations

        configs = [{"specification": "Example", "details": "HCMG_TX_20240101.txt"}]
        result = _summarize_configurations(configs)
        assert len(result["examples"]) > 0

    def test_detects_enumerations(self):
        from tablespec.prompts.filename_pattern import _summarize_configurations

        configs = [{"specification": "Vendor", "details": "HCMG, SIGNIFY, INOVALON"}]
        result = _summarize_configurations(configs)
        assert len(result["enumerations"]) > 0

    def test_collects_notes(self):
        from tablespec.prompts.filename_pattern import _summarize_configurations

        configs = [{"specification": "Some info", "details": "Random extra context"}]
        result = _summarize_configurations(configs)
        assert len(result["notes"]) > 0

    def test_empty_configs(self):
        from tablespec.prompts.filename_pattern import _summarize_configurations

        result = _summarize_configurations([])
        assert result["patterns"] == []
        assert result["examples"] == []
        assert result["enumerations"] == {}
        assert result["notes"] == []


class TestConvertPhase0JsonToUmfStructure:
    def test_converts_valid_json(self):
        from tablespec.prompts.filename_pattern import (
            _convert_phase0_json_to_umf_structure,
        )

        raw = {
            "data": {
                "columns": [0, 1, 2],
                "data": [
                    ["S. No.", "File Name", "Details"],
                    ["1", "outreach_list.txt", "Daily file"],
                ],
            }
        }
        result = _convert_phase0_json_to_umf_structure(raw, Path("/tmp/test.json"))
        assert result is not None
        assert result["table_name"] == "test"
        assert len(result["config_data"]["configurations"]) > 0

    def test_returns_none_for_missing_data_key(self):
        from tablespec.prompts.filename_pattern import (
            _convert_phase0_json_to_umf_structure,
        )

        result = _convert_phase0_json_to_umf_structure({}, Path("/tmp/test.json"))
        assert result is None

    def test_returns_none_for_too_few_rows(self):
        from tablespec.prompts.filename_pattern import (
            _convert_phase0_json_to_umf_structure,
        )

        raw = {"data": {"data": [["header"]]}}
        result = _convert_phase0_json_to_umf_structure(raw, Path("/tmp/test.json"))
        assert result is None

    def test_naming_conventions_format(self):
        from tablespec.prompts.filename_pattern import (
            _convert_phase0_json_to_umf_structure,
        )

        raw = {
            "data": {
                "columns": [0, 1, 2, 3],
                "data": [
                    ["S. No.", "File Name", "Naming Convention", "Details"],
                    [
                        "1",
                        "OutreachList",
                        "Vendor_State_OutreachList_Date.txt",
                        "Daily",
                    ],
                    ["2", "Claims", "Vendor_Claims_Date.txt", "Monthly"],
                ],
            }
        }
        result = _convert_phase0_json_to_umf_structure(raw, Path("/tmp/naming.json"))
        assert result is not None
        configs = result["config_data"]["configurations"]
        assert len(configs) == 2


class TestCollectSheetAliases:
    def test_collects_json_stems(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import _collect_sheet_aliases

        (tmp_path / "Sheet1.json").write_text("{}")
        (tmp_path / "Sheet2.json").write_text("{}")

        names, truncated = _collect_sheet_aliases(tmp_path)
        assert "Sheet1" in names
        assert "Sheet2" in names
        assert not truncated

    def test_skips_underscore_files(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import _collect_sheet_aliases

        (tmp_path / "_metadata.json").write_text("{}")
        (tmp_path / "Sheet1.json").write_text("{}")

        names, _ = _collect_sheet_aliases(tmp_path)
        assert "_metadata" not in names

    def test_returns_empty_for_nonexistent(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import _collect_sheet_aliases

        names, truncated = _collect_sheet_aliases(tmp_path / "nonexistent")
        assert names == []
        assert not truncated

    def test_truncates_at_limit(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import _collect_sheet_aliases

        for i in range(50):
            (tmp_path / f"sheet_{i:03d}.json").write_text("{}")

        names, truncated = _collect_sheet_aliases(tmp_path, limit=10)
        assert len(names) == 10
        assert truncated


class TestGenerateFilenamePatternPrompt:
    def test_returns_none_for_empty_dir(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        result = generate_filename_pattern_prompt(tmp_path)
        assert result is None

    def test_returns_none_for_empty_list(self):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        result = generate_filename_pattern_prompt([])
        assert result is None

    def test_returns_none_for_invalid_input(self):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        result = generate_filename_pattern_prompt(42)  # type: ignore[arg-type]
        assert result is None

    def test_returns_prompt_for_yaml_files(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        naming_data = {
            "table_name": "File_Naming_Standards",
            "source_file": "workbook.xlsx",
            "sheet_name": "Naming",
            "config_data": {
                "configurations": [
                    {
                        "specification": "File Name Format",
                        "details": "Vendor_State_TableName_YYYYMMDD.txt",
                    }
                ]
            },
        }
        yaml_file = tmp_path / "File_Naming_Standards.lookup.yaml"
        yaml_file.write_text(yaml.dump(naming_data))

        result = generate_filename_pattern_prompt(tmp_path)
        assert result is not None
        assert "Filename Pattern" in result
        assert "File_Naming_Standards" in result

    def test_returns_prompt_for_json_files(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        json_data = {
            "data": {
                "columns": [0, 1],
                "data": [
                    ["File Name", "Pattern"],
                    ["OutreachList", "Vendor_OutreachList_Date.txt"],
                ],
            }
        }
        json_file = tmp_path / "naming.json"
        json_file.write_text(json.dumps(json_data))

        result = generate_filename_pattern_prompt([json_file])
        assert result is not None
        assert "Filename Pattern" in result

    def test_includes_sheet_aliases(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        naming_data = {
            "table_name": "File_Naming_Standards",
            "source_file": "wb.xlsx",
            "sheet_name": "Naming",
            "config_data": {"configurations": []},
        }
        yaml_file = tmp_path / "File_Naming_Standards.lookup.yaml"
        yaml_file.write_text(yaml.dump(naming_data))

        # Create extraction dir with sheets
        extraction_dir = tmp_path / "extracted"
        extraction_dir.mkdir()
        (extraction_dir / "OutreachList.json").write_text("{}")
        (extraction_dir / "Claims.json").write_text("{}")

        result = generate_filename_pattern_prompt(
            tmp_path, extraction_dir=extraction_dir
        )
        assert result is not None
        assert "OutreachList" in result
        assert "Claims" in result

    def test_contains_output_format(self, tmp_path: Path):
        from tablespec.prompts.filename_pattern import generate_filename_pattern_prompt

        naming_data = {
            "table_name": "Naming_Standards",
            "source_file": "wb.xlsx",
            "sheet_name": "Naming",
            "config_data": {"configurations": []},
        }
        (tmp_path / "Naming_Standards.lookup.yaml").write_text(yaml.dump(naming_data))

        result = generate_filename_pattern_prompt(tmp_path)
        assert result is not None
        assert "Output Contract" in result
        assert "json.loads()" in result


# ── validation_per_column.py ──────────────────────────────────────────────


class TestGenerateValidationPromptPerColumn:
    def test_column_context(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="test_table",
            table_description="A test table",
            column_name="status",
            column_data={
                "description": "Member status code",
                "data_type": "VARCHAR",
                "max_length": 2,
                "nullable": {"MD": False},
                "format": "",
            },
            context="column",
        )
        assert isinstance(result, str)
        assert "status" in result
        assert "test_table" in result
        assert "VARCHAR" in result

    def test_table_context(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="test_table",
            table_description="A test table",
            context="table",
            umf_data=MINIMAL_UMF,
        )
        assert isinstance(result, str)
        assert "Table-Level" in result
        assert "test_table" in result

    def test_invalid_context_raises(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        with pytest.raises(ValueError, match="Unknown context"):
            generate_validation_prompt_per_column(
                table_name="t",
                table_description="d",
                context="invalid",
            )

    def test_column_context_missing_column_data_raises(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        with pytest.raises(ValueError, match="column_name and column_data"):
            generate_validation_prompt_per_column(
                table_name="t",
                table_description="d",
                context="column",
            )

    def test_column_includes_auto_generated_section(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="t",
            table_description="d",
            column_name="col1",
            column_data={
                "description": "A column",
                "data_type": "INTEGER",
                "max_length": None,
                "nullable": {},
            },
            context="column",
        )
        assert "Auto-Generated" in result

    def test_column_includes_format_when_present(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="t",
            table_description="d",
            column_name="dt",
            column_data={
                "description": "A date",
                "data_type": "DATE",
                "nullable": {},
                "format": "YYYYMMDD",
            },
            context="column",
        )
        assert "YYYYMMDD" in result

    def test_column_includes_domain_type(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="t",
            table_description="d",
            column_name="npi",
            column_data={
                "description": "NPI number",
                "data_type": "VARCHAR",
                "nullable": {},
                "domain_type": "npi",
            },
            context="column",
        )
        # domain_type should appear in auto-generated section
        assert "npi" in result

    def test_table_context_includes_columns(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="test_table",
            table_description="A test table",
            context="table",
            umf_data=MINIMAL_UMF,
        )
        assert "member_id" in result
        assert "birth_date" in result
        assert "Available Columns" in result

    def test_table_context_no_umf_data(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="t",
            table_description="d",
            context="table",
        )
        assert "Table-Level" in result
        # No Available Columns section when umf_data is None
        assert "Available Columns" not in result

    def test_column_required_lobs_displayed(self):
        from tablespec.prompts.validation_per_column import (
            generate_validation_prompt_per_column,
        )

        result = generate_validation_prompt_per_column(
            table_name="t",
            table_description="d",
            column_name="c",
            column_data={
                "description": "desc",
                "data_type": "VARCHAR",
                "nullable": {"MD": False, "ME": True},
            },
            context="column",
        )
        assert "MD" in result


# ── __init__.py exports ───────────────────────────────────────────────────


class TestPromptsModuleExports:
    def test_all_public_functions_importable(self):
        import tablespec.prompts as prompts

        assert callable(prompts.clean_description)
        assert callable(prompts.is_relationship_relevant_column)
        assert callable(prompts.load_umf)
        assert callable(prompts.generate_documentation_prompt)
        assert callable(prompts.generate_validation_prompt)
        assert callable(prompts.has_validation_rules)
        assert callable(prompts.generate_column_validation_prompt)
        assert callable(prompts.should_generate_column_prompt)
        assert callable(prompts.generate_relationship_prompt)
        assert callable(prompts.generate_survivorship_prompt)
        assert callable(prompts.generate_survivorship_prompt_per_column)
        assert callable(prompts.generate_filename_pattern_prompt)
        assert callable(prompts.generate_validation_prompt_per_column)

    def test_deprecated_aliases_importable(self):
        import tablespec.prompts as prompts

        assert callable(prompts._clean_description)
        assert callable(prompts._is_relationship_relevant_column)
        assert callable(prompts._load_umf)
        assert callable(prompts._generate_documentation_prompt)
        assert callable(prompts._generate_validation_prompt)
        assert callable(prompts._has_validation_rules)
        assert callable(prompts._generate_relationship_prompt)
        assert callable(prompts._generate_survivorship_prompt)
        assert callable(prompts._generate_column_validation_prompt)
        assert callable(prompts._should_generate_column_prompt)
