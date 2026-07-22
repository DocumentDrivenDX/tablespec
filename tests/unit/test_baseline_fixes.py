"""Tests for baseline generator fixes: redundant type removal and profiling expectations."""

from __future__ import annotations

import pytest

from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.models.umf import REDUNDANT_VALIDATION_TYPES

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]


class TestRedundantTypeRemoval:
    """Verify that redundant expectation types are never generated."""

    def test_baseline_never_generates_redundant_types_minimal(self):
        """Test minimal UMF produces no redundant types."""
        umf_data = {
            "table_name": "t",
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "VARCHAR", "max_length": 50},
            ],
        }
        gen = BaselineExpectationGenerator()
        expectations = gen.generate_baseline_expectations(umf_data)
        for exp in expectations:
            assert exp["type"] not in REDUNDANT_VALIDATION_TYPES, (
                f"Generated redundant type: {exp['type']}"
            )

    def test_baseline_never_generates_redundant_types_full(self):
        """Test full UMF with various column types produces no redundant types."""
        umf_data = {
            "table_name": "full_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": {"md": False}},
                {"name": "name", "data_type": "VARCHAR", "max_length": 100},
                {"name": "dob", "data_type": "DATE"},
                {"name": "created", "data_type": "DATETIME"},
                {"name": "score", "data_type": "FLOAT"},
                {"name": "amount", "data_type": "DECIMAL"},
                {"name": "flag", "data_type": "BOOLEAN"},
            ],
        }
        gen = BaselineExpectationGenerator()
        expectations = gen.generate_baseline_expectations(umf_data)
        for exp in expectations:
            assert exp["type"] not in REDUNDANT_VALIDATION_TYPES, (
                f"Generated redundant type: {exp['type']}"
            )

    def test_column_to_exist_no_longer_generated(self):
        umf_data = {
            "table_name": "t",
            "columns": [{"name": "id", "data_type": "INTEGER"}],
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_expectations(umf_data)
        types = [e["type"] for e in exps]
        assert "expect_column_to_exist" not in types

    def test_column_type_no_longer_generated(self):
        umf_data = {
            "table_name": "t",
            "columns": [{"name": "id", "data_type": "INTEGER"}],
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_expectations(umf_data)
        types = [e["type"] for e in exps]
        assert "expect_column_values_to_be_of_type" not in types


class TestProfilingExpectations:
    """Verify profiling-to-expectations generation."""

    def test_unique_column_gets_uniqueness(self):
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"approximate_num_distinct": 1000, "num_records": 1000},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert any(e["type"] == "expect_column_values_to_be_unique" for e in exps)

    def test_non_unique_column_no_uniqueness(self):
        col = {
            "name": "status",
            "data_type": "VARCHAR",
            "profiling": {"approximate_num_distinct": 5, "num_records": 1000},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_be_unique" for e in exps)

    def test_bounded_column_gets_range(self):
        col = {
            "name": "age",
            "data_type": "INTEGER",
            "profiling": {"statistics": {"min": 0, "max": 120}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        between = [e for e in exps if e["type"] == "expect_column_values_to_be_between"]
        assert len(between) == 1
        assert between[0]["kwargs"]["min_value"] == 0
        assert between[0]["kwargs"]["max_value"] == 120

    def test_high_completeness_gets_not_null(self):
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"completeness": 0.995},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert any(e["type"] == "expect_column_values_to_not_be_null" for e in exps)

    def test_low_completeness_no_not_null(self):
        col = {
            "name": "notes",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.5},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_not_be_null" for e in exps)

    def test_boundary_completeness_099_gets_soft_null(self):
        """Completeness of exactly 0.99 triggers soft not-null (>0.99 is hard, 0.95-0.99 is soft)."""
        col = {
            "name": "field",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.99},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(null_exps) == 1
        assert null_exps[0]["kwargs"]["mostly"] == 0.99

    def test_value_set_from_distinct_values(self):
        """Low-cardinality column with distinct_values produces in_set expectation."""
        col = {
            "name": "status",
            "data_type": "VARCHAR",
            "profiling": {"distinct_values": ["Active", "Inactive", "Pending"]},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        in_set = [e for e in exps if e["type"] == "expect_column_values_to_be_in_set"]
        assert len(in_set) == 1
        assert in_set[0]["kwargs"]["value_set"] == ["Active", "Inactive", "Pending"]
        assert in_set[0]["meta"]["generated_from"] == "profiling"

    def test_no_value_set_without_distinct_values(self):
        """Column without distinct_values does not produce in_set expectation."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "profiling": {"approximate_num_distinct": 500},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_be_in_set" for e in exps)

    def test_string_lengths_from_profiling(self):
        """Column with string_lengths produces length expectation."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "profiling": {"string_lengths": {"min_length": 2, "max_length": 50}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        length_exps = [
            e for e in exps if e["type"] == "expect_column_value_lengths_to_be_between"
        ]
        assert len(length_exps) == 1
        assert length_exps[0]["kwargs"]["min_value"] == 2
        assert length_exps[0]["kwargs"]["max_value"] == 50
        assert length_exps[0]["meta"]["generated_from"] == "profiling"

    def test_no_string_lengths_without_profiling_data(self):
        """Column without string_lengths does not produce length expectation."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 1.0},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(
            e["type"] == "expect_column_value_lengths_to_be_between" for e in exps
        )

    def test_soft_null_check_moderate_completeness(self):
        """Completeness 0.95-0.99 produces not_be_null with mostly param."""
        col = {
            "name": "field",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.97},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(null_exps) == 1
        assert null_exps[0]["kwargs"]["mostly"] == 0.97

    def test_no_null_check_below_095(self):
        """Completeness below 0.95 produces no not_be_null expectation."""
        col = {
            "name": "notes",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.94},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_not_be_null" for e in exps)

    def test_boundary_095_gets_soft_null(self):
        """Completeness of exactly 0.95 should trigger soft null check."""
        col = {
            "name": "field",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.95},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(null_exps) == 1
        assert null_exps[0]["kwargs"]["mostly"] == 0.95

    def test_no_duplicate_not_null_when_baseline_covers(self):
        """Column with nullable dict AND high completeness → only baseline not-null, not profiling."""
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "nullable": {"MD": False},
            "profiling": {"completeness": 1.0},
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_column_expectations(col)
        null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(null_exps) == 1
        assert null_exps[0]["meta"]["generated_from"] == "baseline"

    def test_no_duplicate_length_when_baseline_covers(self):
        """Column with max_length AND string_lengths → only baseline length, not profiling."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "max_length": 50,
            "profiling": {"string_lengths": {"min_length": 2, "max_length": 45}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_column_expectations(col)
        length_exps = [
            e for e in exps if e["type"] == "expect_column_value_lengths_to_be_between"
        ]
        assert len(length_exps) == 1
        assert length_exps[0]["meta"]["generated_from"] == "baseline"

    def test_profiling_length_when_no_max_length(self):
        """Column without max_length but with string_lengths → profiling length generated."""
        col = {
            "name": "notes",
            "data_type": "VARCHAR",
            "profiling": {"string_lengths": {"min_length": 5, "max_length": 500}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        length_exps = [
            e for e in exps if e["type"] == "expect_column_value_lengths_to_be_between"
        ]
        assert len(length_exps) == 1

    def test_profiling_not_null_when_all_nullable(self):
        """Column with nullable:{MD:true} (all nullable) AND high completeness → profiling not-null."""
        col = {
            "name": "field",
            "data_type": "VARCHAR",
            "nullable": {"MD": True},
            "profiling": {"completeness": 1.0},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(null_exps) == 1
        assert null_exps[0]["meta"]["generated_from"] == "profiling"

    def test_approximate_uniqueness_near_threshold(self):
        """Column with 99% distinct values should still be detected as unique."""
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"approximate_num_distinct": 990, "num_records": 1000},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert any(e["type"] == "expect_column_values_to_be_unique" for e in exps)

    def test_approximate_uniqueness_below_threshold(self):
        """Column with 98% distinct values should NOT be detected as unique."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "profiling": {"approximate_num_distinct": 980, "num_records": 1000},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_be_unique" for e in exps)

    def test_no_profiling_returns_empty(self):
        col = {"name": "id", "data_type": "INTEGER"}
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert exps == []

    def test_empty_profiling_returns_empty(self):
        col = {"name": "id", "data_type": "INTEGER", "profiling": {}}
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert exps == []

    def test_profiling_expectations_have_generated_from(self):
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"statistics": {"min": 0, "max": 100}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        for exp in exps:
            assert exp["meta"]["generated_from"] == "profiling"

    def test_profiling_expectations_have_warning_severity(self):
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"statistics": {"min": 0, "max": 100}, "completeness": 1.0},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        for exp in exps:
            assert exp["meta"]["severity"] == "warning"

    def test_profiling_wired_into_baseline(self):
        """Profiling expectations should appear in generate_baseline_column_expectations."""
        col = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {"statistics": {"min": 1, "max": 999}},
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_column_expectations(col)
        assert any(e["type"] == "expect_column_values_to_be_between" for e in exps)

    def test_regex_pattern_from_profiling(self):
        """Column with patterns produces regex expectation."""
        col = {
            "name": "state_code",
            "data_type": "VARCHAR",
            "profiling": {"patterns": ["^[A-Z]{2}$"]},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        regex_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_match_regex"
        ]
        assert len(regex_exps) == 1
        assert regex_exps[0]["kwargs"]["regex"] == "^[A-Z]{2}$"
        assert regex_exps[0]["kwargs"]["mostly"] == 0.95
        assert regex_exps[0]["meta"]["generated_from"] == "profiling"

    def test_regex_pattern_from_format_patterns(self):
        """Column with format_patterns (fallback key) produces regex expectation."""
        col = {
            "name": "zip",
            "data_type": "VARCHAR",
            "profiling": {"format_patterns": ["^\\d{5}$"]},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        regex_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_match_regex"
        ]
        assert len(regex_exps) == 1
        assert regex_exps[0]["kwargs"]["regex"] == "^\\d{5}$"

    def test_no_regex_without_patterns(self):
        """Column without patterns does not produce regex expectation."""
        col = {
            "name": "name",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 1.0},
        }
        gen = BaselineExpectationGenerator()
        exps = gen._generate_profiling_expectations(col)
        assert not any(e["type"] == "expect_column_values_to_match_regex" for e in exps)

    def test_profiling_wired_into_full_generate(self):
        """Profiling expectations should appear in generate_baseline_expectations."""
        umf_data = {
            "table_name": "t",
            "columns": [
                {
                    "name": "id",
                    "data_type": "INTEGER",
                    "profiling": {"approximate_num_distinct": 500, "num_records": 500},
                }
            ],
        }
        gen = BaselineExpectationGenerator()
        exps = gen.generate_baseline_expectations(umf_data)
        assert any(e["type"] == "expect_column_values_to_be_unique" for e in exps)
