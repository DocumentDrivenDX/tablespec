# @covers US-036-AC2
"""Tests for LLM response applier."""

from __future__ import annotations

import pytest

from tablespec.authoring.apply_response import ApplyResult, apply_validation_response
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]


def _make_umf(
    table_name: str = "t",
    columns: list[dict] | None = None,
    validation_rules: dict | None = None,
    quality_checks: dict | None = None,
    expectations: dict | None = None,
) -> UMF:
    """Build a minimal UMF for testing."""
    if columns is None:
        columns = [{"name": "id", "data_type": "INTEGER"}]
    data: dict = {
        "version": "1.0",
        "table_name": table_name,
        "columns": columns,
    }
    if validation_rules is not None:
        data["validation_rules"] = validation_rules
    if quality_checks is not None:
        data["quality_checks"] = quality_checks
    if expectations is not None:
        data["expectations"] = expectations
    return UMF(**data)


class TestApplyValidationResponse:
    def test_adds_new_expectations(self):
        umf = _make_umf(
            columns=[{"name": "ssn", "data_type": "VARCHAR", "max_length": 11}]
        )
        response = [
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {"column": "ssn", "regex": r"^\d{3}-\d{2}-\d{4}$"},
            }
        ]
        result = apply_validation_response(umf, response)
        assert len(result.added) == 1
        assert result.added[0]["meta"]["generated_from"] == "llm"
        assert result.added[0]["meta"]["validation_stage"] == "raw"
        assert result.updated_umf is not None
        assert len(result.updated_umf.expectations.expectations) == 1

    def test_deduplicates_existing(self):
        umf = _make_umf(
            columns=[{"name": "id", "data_type": "INTEGER"}],
            validation_rules={
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            },
        )
        response = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            }
        ]
        result = apply_validation_response(umf, response)
        assert len(result.deduplicated) == 1
        assert len(result.added) == 0

    def test_rejects_unknown_type(self):
        umf = _make_umf()
        response = [{"type": "expect_column_to_fly", "kwargs": {"column": "id"}}]
        result = apply_validation_response(umf, response)
        assert len(result.invalid) == 1
        assert "Unknown" in result.invalid[0][1]

    def test_rejects_missing_type(self):
        umf = _make_umf()
        response = [{"kwargs": {"column": "id"}}]
        result = apply_validation_response(umf, response)
        assert len(result.invalid) == 1
        assert "Missing" in result.invalid[0][1]

    def test_classifies_ingested_type(self):
        umf = _make_umf(columns=[{"name": "age", "data_type": "INTEGER"}])
        response = [
            {
                "type": "expect_column_values_to_be_between",
                "kwargs": {"column": "age", "min_value": 0, "max_value": 150},
            }
        ]
        result = apply_validation_response(umf, response)
        assert len(result.added) == 1
        assert result.added[0]["meta"]["validation_stage"] == "ingested"

    def test_empty_response(self):
        umf = _make_umf()
        result = apply_validation_response(umf, [])
        assert len(result.added) == 0
        assert len(result.deduplicated) == 0
        assert len(result.invalid) == 0

    def test_multiple_mixed(self):
        umf = _make_umf(
            columns=[
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "VARCHAR", "max_length": 50},
            ]
        )
        response = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            },
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {"column": "name", "regex": ".*"},
            },
            {
                "type": "expect_fake_thing",
                "kwargs": {"column": "id"},
            },
        ]
        result = apply_validation_response(umf, response)
        assert len(result.added) == 2
        assert len(result.invalid) == 1

    def test_dedup_within_response(self):
        """Duplicate entries within the same response should be deduped."""
        umf = _make_umf()
        response = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            },
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            },
        ]
        result = apply_validation_response(umf, response)
        assert len(result.added) == 1
        assert len(result.deduplicated) == 1

    def test_dedup_against_quality_checks(self):
        """Expectations already in quality_checks should be deduped."""
        umf = _make_umf(
            columns=[{"name": "age", "data_type": "INTEGER"}],
            quality_checks={
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {
                                "column": "age",
                                "min_value": 0,
                                "max_value": 150,
                            },
                        },
                        "severity": "warning",
                    }
                ]
            },
        )
        response = [
            {
                "type": "expect_column_values_to_be_between",
                "kwargs": {"column": "age", "min_value": 0, "max_value": 200},
            }
        ]
        result = apply_validation_response(umf, response)
        assert len(result.deduplicated) == 1
        assert len(result.added) == 0

    def test_legacy_expectation_type_field(self):
        """Support 'expectation_type' as a legacy alias for 'type'."""
        umf = _make_umf()
        response = [
            {
                "expectation_type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            }
        ]
        result = apply_validation_response(umf, response)
        assert len(result.added) == 1
        assert result.added[0]["meta"]["generated_from"] == "llm"

    def test_result_dataclass_defaults(self):
        result = ApplyResult()
        assert result.added == []
        assert result.deduplicated == []
        assert result.invalid == []
        assert result.warnings == []
        assert result.updated_umf is None

    def test_updates_expectation_suite_and_clears_legacy_fields(self):
        umf = _make_umf(
            validation_rules={
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            }
        )
        response = [
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {"column": "id", "regex": "^\\d+$"},
            }
        ]

        result = apply_validation_response(umf, response)

        assert result.updated_umf is not None
        assert len(result.updated_umf.expectations.expectations) == 2
        assert result.updated_umf.validation_rules is None
        assert result.updated_umf.quality_checks is None

    def test_dedup_does_not_create_updated_umf(self):
        umf = _make_umf(
            expectations={
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                        "meta": {"validation_stage": "raw"},
                    }
                ]
            }
        )
        response = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "id"},
            }
        ]

        result = apply_validation_response(umf, response)

        assert len(result.deduplicated) == 1
        assert result.updated_umf is None
