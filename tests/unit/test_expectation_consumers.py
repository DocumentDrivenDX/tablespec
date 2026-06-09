"""Consumers should prefer ADR-005 ExpectationSuite over legacy fields."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_spark


def _umf_data_with_unified_and_legacy_expectations() -> dict:
    return {
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["active"]},
                    "meta": {"severity": "info"},
                },
                {
                    "type": "expect_column_values_to_be_between",
                    "kwargs": {
                        "column": "signup_date",
                        "min_value": "2026-01-01",
                        "max_value": "2026-12-31",
                    },
                },
            ]
        },
        "validation_rules": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["legacy"]},
                    "meta": {"severity": "critical", "blocking": True},
                }
            ]
        },
    }


def test_expectation_dicts_from_umf_data_prefers_expectation_suite() -> None:
    from tablespec.expectation_utils import expectation_dicts_from_umf_data

    expectations = expectation_dicts_from_umf_data(
        _umf_data_with_unified_and_legacy_expectations()
    )

    assert len(expectations) == 2
    assert expectations[0]["kwargs"]["value_set"] == ["active"]


def test_schema_facts_reads_accepted_values_from_expectation_suite_first() -> None:
    from tablespec.core.schema_facts import accepted_values_tests

    tests = accepted_values_tests(_umf_data_with_unified_and_legacy_expectations())

    assert len(tests) == 1
    assert tests[0].column == "status"
    assert tests[0].values == ("active",)


def test_ldp_violation_meta_reads_expectation_suite_first() -> None:
    from tablespec.ldp.expectations import _accepted_values_meta

    meta = _accepted_values_meta(_umf_data_with_unified_and_legacy_expectations())

    assert meta["status"] == {"severity": "info"}


def test_sample_data_date_constraints_read_expectation_suite_first() -> None:
    from tablespec.sample_data.date_processing import extract_date_constraints

    constraints = extract_date_constraints(
        "signup_date", _umf_data_with_unified_and_legacy_expectations()
    )

    assert constraints == {"min_value": "2026-01-01", "max_value": "2026-12-31"}
