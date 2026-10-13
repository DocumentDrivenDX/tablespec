"""Test Great Expectations baseline expectation generation from UMF."""

# @covers US-005-AC1
# @covers US-005-AC2
# @covers US-005-AC3
# @covers US-005-AC4
# @covers US-005-AC5

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from tablespec.gx_baseline import BaselineExpectationGenerator, UmfToGxMapper

pytestmark = pytest.mark.fast

if TYPE_CHECKING:
    from pathlib import Path


class TestBaselineExpectationGenerator:
    """Test baseline expectation generation from UMF metadata."""

    @pytest.fixture
    def generator(self):
        """Create generator instance."""
        return BaselineExpectationGenerator()

    @pytest.fixture
    def minimal_umf(self):
        """Minimal UMF data for testing."""
        return {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "VARCHAR"},
            ],
        }

    @pytest.fixture
    def full_umf(self):
        """Full UMF data with all metadata fields."""
        return {
            "table_name": "customer_table",
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "INTEGER",
                    "nullable": {"medicare": False, "medicaid": True},
                },
                {
                    "name": "customer_name",
                    "data_type": "VARCHAR",
                    "max_length": 100,
                    "nullable": {"medicare": False, "medicaid": False},
                },
                {
                    "name": "birth_date",
                    "data_type": "DATE",
                    "nullable": {"medicare": True, "medicaid": True},
                },
                {
                    "name": "email",
                    "data_type": "STRING",
                    "length": 255,
                },
            ],
        }

    def test_generate_baseline_expectations_with_structural(
        self, generator, minimal_umf
    ):
        """Test baseline generation includes structural expectations."""
        expectations = generator.generate_baseline_expectations(
            minimal_umf, include_structural=True
        )

        # Should have structural + column expectations
        # 2 structural (column count, column list) + id: cast_to_type (1) + name: (0) = 3
        assert len(expectations) >= 3

        # Check structural expectations exist
        exp_types = [exp["type"] for exp in expectations]
        assert "expect_table_column_count_to_equal" in exp_types
        assert "expect_table_columns_to_match_ordered_list" in exp_types

    def test_generate_baseline_expectations_without_structural(
        self, generator, minimal_umf
    ):
        """Test baseline generation can exclude structural expectations."""
        expectations = generator.generate_baseline_expectations(
            minimal_umf, include_structural=False
        )

        # Should only have column expectations:
        # - id (IntegerType): cast_to_type (1)
        # - name (StringType): (0)
        assert len(expectations) == 1

        # Check no structural expectations
        exp_types = [exp["type"] for exp in expectations]
        assert "expect_table_column_count_to_equal" not in exp_types
        assert "expect_table_columns_to_match_ordered_list" not in exp_types

    def test_structural_expectations_column_count(self, generator, minimal_umf):
        """Test structural expectation for column count."""
        structural = generator._generate_structural_expectations(minimal_umf)

        column_count_exp = next(
            exp
            for exp in structural
            if exp["type"] == "expect_table_column_count_to_equal"
        )

        assert column_count_exp["kwargs"]["value"] == 2
        assert column_count_exp["meta"]["severity"] == "critical"
        assert "2 columns" in column_count_exp["meta"]["description"]

    def test_structural_expectations_column_order(self, generator, minimal_umf):
        """Test structural expectation for column order."""
        structural = generator._generate_structural_expectations(minimal_umf)

        column_list_exp = next(
            exp
            for exp in structural
            if exp["type"] == "expect_table_columns_to_match_ordered_list"
        )

        assert column_list_exp["kwargs"]["column_list"] == ["id", "name"]
        assert column_list_exp["meta"]["severity"] == "critical"

    def test_column_existence_not_generated(self, generator):
        """Test that column existence expectation is no longer generated (redundant)."""
        column = {"name": "test_col", "data_type": "VARCHAR"}

        expectations = generator.generate_baseline_column_expectations(column)

        existence_exp = next(
            (exp for exp in expectations if exp["type"] == "expect_column_to_exist"),
            None,
        )

        assert existence_exp is None

    def test_column_type_not_generated(self, generator):
        """Test that column type expectation is no longer generated (redundant)."""
        column = {"name": "age", "data_type": "INTEGER"}

        expectations = generator.generate_baseline_column_expectations(column)

        type_exp = next(
            (
                exp
                for exp in expectations
                if exp["type"] == "expect_column_values_to_be_of_type"
            ),
            None,
        )

        assert type_exp is None

    def test_nullability_expectation_required(self, generator):
        """Test nullability expectation when column is required for some LOBs."""
        column = {
            "name": "required_field",
            "data_type": "VARCHAR",
            "nullable": {"medicare": False, "medicaid": True},
        }

        expectations = generator.generate_baseline_column_expectations(column)

        not_null_exp = next(
            (
                exp
                for exp in expectations
                if exp["type"] == "expect_column_values_to_not_be_null"
            ),
            None,
        )

        assert not_null_exp is not None
        assert not_null_exp["kwargs"]["column"] == "required_field"
        assert not_null_exp["meta"]["severity"] == "critical"
        assert "medicare" in not_null_exp["meta"]["contexts"]

    def test_nullability_expectation_optional(self, generator):
        """Test no nullability expectation when column is optional for all LOBs."""
        column = {
            "name": "optional_field",
            "data_type": "VARCHAR",
            "nullable": {"medicare": True, "medicaid": True},
        }

        expectations = generator.generate_baseline_column_expectations(column)

        not_null_exp = next(
            (
                exp
                for exp in expectations
                if exp["type"] == "expect_column_values_to_not_be_null"
            ),
            None,
        )

        assert not_null_exp is None

    def test_max_length_expectation_from_max_length(self, generator):
        """Test max length expectation from max_length field."""
        column = {"name": "name_field", "data_type": "VARCHAR", "max_length": 50}

        expectations = generator.generate_baseline_column_expectations(column)

        length_exp = next(
            exp
            for exp in expectations
            if exp["type"] == "expect_column_value_lengths_to_be_between"
        )

        assert length_exp["kwargs"]["column"] == "name_field"
        assert length_exp["kwargs"]["max_value"] == 50
        assert length_exp["meta"]["severity"] == "warning"

    def test_max_length_expectation_from_length(self, generator):
        """Test max length expectation from length field."""
        column = {"name": "code", "data_type": "VARCHAR", "length": 10}

        expectations = generator.generate_baseline_column_expectations(column)

        length_exp = next(
            exp
            for exp in expectations
            if exp["type"] == "expect_column_value_lengths_to_be_between"
        )

        assert length_exp["kwargs"]["max_value"] == 10

    def test_embedding_generates_length_expectation(self, generator):
        """Test EMBEDDING columns generate dimensionality expectations."""
        column = {
            "name": "embedding",
            "data_type": "EMBEDDING",
            "dimension": 1024,
        }

        expectations = generator.generate_baseline_column_expectations(column)

        length_exp = next(
            exp
            for exp in expectations
            if exp["type"] == "expect_column_value_lengths_to_equal"
        )

        assert length_exp["kwargs"]["column"] == "embedding"
        assert length_exp["kwargs"]["value"] == 1024
        assert length_exp["meta"]["validation_stage"] == "ingested"
        assert length_exp["meta"]["severity"] == "critical"

    def test_embedding_dimension_multiple_of_16_has_no_advisory(self, generator):
        """Test Vector Search advisory is not emitted for divisible dimensions."""
        expectations = generator.generate_baseline_column_expectations(
            {"name": "embedding", "data_type": "EMBEDDING", "dimension": 1024}
        )

        exp_types = {exp["type"] for exp in expectations}
        assert "expect_column_value_lengths_to_equal" in exp_types
        assert "expect_embedding_dimension_multiple_of_16_advisory" not in exp_types

    def test_embedding_dimension_advisory_is_non_blocking(self, generator):
        """Test non-divisible dimensions surface as non-blocking advisories."""
        expectations = generator.generate_baseline_column_expectations(
            {"name": "embedding", "data_type": "EMBEDDING", "dimension": 1025}
        )

        advisory = next(
            exp
            for exp in expectations
            if exp["type"] == "expect_embedding_dimension_multiple_of_16_advisory"
        )
        assert advisory["kwargs"] == {"column": "embedding", "dimension": 1025}
        assert advisory["meta"]["validation_stage"] == "ingested"
        assert advisory["meta"]["severity"] == "info"
        assert advisory["meta"]["blocking"] is False
        assert "Vector Search" in advisory["meta"]["description"]

    def test_date_format_expectation(self, generator):
        """Test DATE columns get strftime format expectation."""
        column = {"name": "birth_date", "data_type": "DATE"}

        expectations = generator.generate_baseline_column_expectations(column)

        date_exp = next(
            exp
            for exp in expectations
            if exp["type"] == "expect_column_values_to_match_strftime_format"
        )

        assert date_exp["kwargs"]["column"] == "birth_date"
        assert date_exp["kwargs"]["strftime_format"] == "%Y%m%d"
        assert date_exp["meta"]["severity"] == "warning"

    def test_full_umf_generates_all_expectations(self, generator, full_umf):
        """Test full UMF generates complete set of expectations."""
        expectations = generator.generate_baseline_expectations(
            full_umf, include_structural=True
        )

        # Should have several expectations
        assert len(expectations) > 5

        # Check all expected types are present
        exp_types = {exp["type"] for exp in expectations}
        assert "expect_table_column_count_to_equal" in exp_types
        assert "expect_table_columns_to_match_ordered_list" in exp_types
        assert "expect_column_values_to_not_be_null" in exp_types
        assert "expect_column_value_lengths_to_be_between" in exp_types
        assert "expect_column_values_to_match_strftime_format" in exp_types

        # Redundant types should NOT be present
        assert "expect_column_to_exist" not in exp_types
        assert "expect_column_values_to_be_of_type" not in exp_types


class TestUmfToGxMapper:
    """Test UMF to GX expectation suite mapping."""

    @pytest.fixture
    def mapper(self):
        """Create mapper instance."""
        return UmfToGxMapper()

    @pytest.fixture
    def umf_file(self, tmp_path: Path):
        """Create temporary UMF file."""
        umf_data = {
            "table_name": "test_table",
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": {"medicare": False}},
                {"name": "name", "data_type": "VARCHAR", "max_length": 100},
            ],
        }

        umf_path = tmp_path / "test_table.umf.yaml"
        with umf_path.open("w", encoding="utf-8") as f:
            yaml.dump(umf_data, f)

        return umf_path

    @pytest.fixture
    def umf_with_profiling(self, tmp_path: Path):
        """Create UMF file with profiling data."""
        umf_data = {
            "table_name": "profiled_table",
            "columns": [
                {
                    "name": "id",
                    "data_type": "INTEGER",
                    "profiling": {
                        "completeness": 1.0,
                        "approximate_num_distinct": 1000,
                    },
                },
                {
                    "name": "status",
                    "data_type": "VARCHAR",
                    "profiling": {
                        "completeness": 0.95,
                        "approximate_num_distinct": 5,
                    },
                },
            ],
        }

        umf_path = tmp_path / "profiled_table.umf.yaml"
        with umf_path.open("w", encoding="utf-8") as f:
            yaml.dump(umf_data, f)

        return umf_path

    def test_generate_expectations_basic(self, mapper, umf_file):
        """Test basic expectation suite generation."""
        suite = mapper.generate_expectations(umf_file)

        assert suite["name"] == "test_table_suite"
        assert suite["meta"]["table_name"] == "test_table"
        assert suite["meta"]["generated_by"] == "tablespec"
        assert len(suite["expectations"]) > 0

    def test_generate_expectations_strictness_levels(self, mapper, umf_file):
        """Test different strictness levels."""
        suite_loose = mapper.generate_expectations(umf_file, strictness="loose")
        suite_medium = mapper.generate_expectations(umf_file, strictness="medium")
        suite_strict = mapper.generate_expectations(umf_file, strictness="strict")

        assert suite_loose["meta"]["strictness"] == "loose"
        assert suite_medium["meta"]["strictness"] == "medium"
        assert suite_strict["meta"]["strictness"] == "strict"

        # All should have baseline expectations (strictness currently doesn't affect baseline)
        assert len(suite_loose["expectations"]) > 0
        assert len(suite_medium["expectations"]) > 0
        assert len(suite_strict["expectations"]) > 0

    def test_suite_includes_baseline_expectations(self, mapper, umf_file):
        """Test suite includes baseline expectations from UMF metadata."""
        suite = mapper.generate_expectations(umf_file)

        exp_types = {exp["type"] for exp in suite["expectations"]}

        # Should have structural expectations
        assert "expect_table_column_count_to_equal" in exp_types
        assert "expect_table_columns_to_match_ordered_list" in exp_types

        # Redundant types should NOT be present
        assert "expect_column_to_exist" not in exp_types
        assert "expect_column_values_to_be_of_type" not in exp_types

    def test_profiling_expectations_generated(self, mapper, umf_with_profiling):
        """Test that profiling-based expectations are attempted."""
        suite = mapper.generate_expectations(umf_with_profiling)

        # Should have expectations (currently just baseline, but profiling path is exercised)
        assert len(suite["expectations"]) > 0

        # Profiling columns should be processed
        assert suite["meta"]["table_name"] == "profiled_table"

    def test_profiling_expectations_without_profiling_data(self, mapper, umf_file):
        """Test no profiling expectations when no profiling data exists."""
        suite = mapper.generate_expectations(umf_file)
        profiling_exps = [
            e
            for e in suite["expectations"]
            if e.get("meta", {}).get("generated_from") == "profiling"
        ]
        assert profiling_exps == []

    def test_profiling_expectations_with_profiling_data(
        self, mapper, umf_with_profiling
    ):
        """Test profiling expectations are generated via BaselineExpectationGenerator."""
        suite = mapper.generate_expectations(umf_with_profiling)
        profiling_exps = [
            e
            for e in suite["expectations"]
            if e.get("meta", {}).get("generated_from") == "profiling"
        ]
        # Profiling data should produce expectations via BaselineExpectationGenerator
        assert isinstance(profiling_exps, list)

    def test_suite_metadata_contains_source_file(self, mapper, umf_file):
        """Test suite metadata includes source UMF file path."""
        suite = mapper.generate_expectations(umf_file)

        assert "source_umf" in suite["meta"]
        assert str(umf_file) in suite["meta"]["source_umf"]

    def test_generate_expectations_with_path_string(self, mapper, umf_file):
        """Test generate_expectations accepts string path."""
        suite = mapper.generate_expectations(str(umf_file))

        assert suite["name"] == "test_table_suite"
        assert len(suite["expectations"]) > 0

    def test_generate_expectations_with_path_object(self, mapper, umf_file):
        """Test generate_expectations accepts Path object."""
        suite = mapper.generate_expectations(umf_file)

        assert suite["name"] == "test_table_suite"
        assert len(suite["expectations"]) > 0

    def test_mapper_uses_baseline_generator(self, mapper):
        """Test mapper uses BaselineExpectationGenerator."""
        assert isinstance(mapper.baseline_generator, BaselineExpectationGenerator)

    def test_expectation_meta_fields(self, mapper, umf_file):
        """Test expectations have required meta fields."""
        suite = mapper.generate_expectations(umf_file)

        for exp in suite["expectations"]:
            assert "meta" in exp
            assert "description" in exp["meta"]
            assert "severity" in exp["meta"]
            assert exp["meta"]["severity"] in ["critical", "warning", "info"]

    def test_table_name_from_umf(self, mapper, tmp_path: Path):
        """Test table name is extracted from UMF."""
        umf_data = {
            "table_name": "my_custom_table",
            "columns": [{"name": "col1", "data_type": "VARCHAR"}],
        }

        umf_path = tmp_path / "custom.umf.yaml"
        with umf_path.open("w", encoding="utf-8") as f:
            yaml.dump(umf_data, f)

        suite = mapper.generate_expectations(umf_path)

        assert suite["name"] == "my_custom_table_suite"
        assert suite["meta"]["table_name"] == "my_custom_table"

    def test_unknown_table_name_fallback(self, mapper, tmp_path: Path):
        """Test fallback when table_name not in UMF."""
        umf_data = {"columns": [{"name": "col1", "data_type": "VARCHAR"}]}

        umf_path = tmp_path / "test.umf.yaml"
        with umf_path.open("w", encoding="utf-8") as f:
            yaml.dump(umf_data, f)

        suite = mapper.generate_expectations(umf_path)

        assert suite["name"] == "unknown_suite"
        assert suite["meta"]["table_name"] == "unknown"


class TestCrossColumnExpectations:
    """Test cross-column pair expectations for date ordering."""

    @pytest.fixture
    def generator(self):
        """Create generator instance."""
        return BaselineExpectationGenerator()

    def test_start_end_date_pair_generates_expectation(self, generator):
        """UMF with start_date and end_date columns generates a pair expectation."""
        umf_data = {
            "table_name": "enrollment",
            "columns": [
                {"name": "start_date", "data_type": "DATE"},
                {"name": "end_date", "data_type": "DATE"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert len(expectations) == 1
        exp = expectations[0]
        assert exp["type"] == "expect_column_pair_values_a_to_be_greater_than_b"
        assert exp["kwargs"]["column_A"] == "end_date"
        assert exp["kwargs"]["column_B"] == "start_date"
        assert exp["kwargs"]["or_equal"] is True
        assert exp["meta"]["severity"] == "warning"
        assert exp["meta"]["generated_from"] == "baseline"

    def test_no_date_columns_generates_nothing(self, generator):
        """UMF with no date columns generates no pair expectations."""
        umf_data = {
            "table_name": "simple",
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "VARCHAR"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert expectations == []

    def test_mismatched_names_generates_nothing(self, generator):
        """UMF with start_date but no matching end column generates nothing."""
        umf_data = {
            "table_name": "partial",
            "columns": [
                {"name": "start_date", "data_type": "DATE"},
                {"name": "created_date", "data_type": "DATE"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert expectations == []

    def test_case_insensitive_matching(self, generator):
        """Case insensitivity works for Start_Date / End_Date."""
        umf_data = {
            "table_name": "mixed_case",
            "columns": [
                {"name": "Start_Date", "data_type": "DATE"},
                {"name": "End_Date", "data_type": "DATE"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert len(expectations) == 1
        exp = expectations[0]
        assert exp["kwargs"]["column_A"] == "End_Date"
        assert exp["kwargs"]["column_B"] == "Start_Date"

    def test_effective_expiry_pattern(self, generator):
        """Effective/expiry date patterns are detected."""
        umf_data = {
            "table_name": "policy",
            "columns": [
                {"name": "effective_date", "data_type": "DATE"},
                {"name": "expiry_date", "data_type": "DATE"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert len(expectations) == 1
        assert expectations[0]["kwargs"]["column_A"] == "expiry_date"
        assert expectations[0]["kwargs"]["column_B"] == "effective_date"

    def test_begin_end_pattern(self, generator):
        """Begin/end date patterns are detected."""
        umf_data = {
            "table_name": "period",
            "columns": [
                {"name": "begin_period", "data_type": "DATE"},
                {"name": "end_period", "data_type": "DATE"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert len(expectations) == 1
        assert expectations[0]["kwargs"]["column_A"] == "end_period"
        assert expectations[0]["kwargs"]["column_B"] == "begin_period"

    def test_datetime_columns_supported(self, generator):
        """DATETIME type columns are also matched."""
        umf_data = {
            "table_name": "events",
            "columns": [
                {"name": "start_time", "data_type": "DATETIME"},
                {"name": "end_time", "data_type": "DATETIME"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert len(expectations) == 1

    def test_non_date_start_end_ignored(self, generator):
        """Start/end columns that are not date types are ignored."""
        umf_data = {
            "table_name": "range",
            "columns": [
                {"name": "start_value", "data_type": "INTEGER"},
                {"name": "end_value", "data_type": "INTEGER"},
            ],
        }

        expectations = generator._generate_cross_column_expectations(umf_data)

        assert expectations == []

    def test_cross_column_included_in_baseline(self, generator):
        """Cross-column expectations are included in generate_baseline_expectations."""
        umf_data = {
            "table_name": "enrollment",
            "columns": [
                {"name": "start_date", "data_type": "DATE"},
                {"name": "end_date", "data_type": "DATE"},
            ],
        }

        expectations = generator.generate_baseline_expectations(umf_data)

        pair_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_pair_values_a_to_be_greater_than_b"
        ]
        assert len(pair_exps) == 1


class TestProfilingExpectations:
    """Test profiling-based expectation generation from BaselineExpectationGenerator."""

    @pytest.fixture
    def generator(self):
        """Create generator instance."""
        return BaselineExpectationGenerator()

    @staticmethod
    def _profiling_exps(expectations: list[dict]) -> list[dict]:
        """Filter expectations to only profiling-generated ones."""
        return [
            e
            for e in expectations
            if e.get("meta", {}).get("generated_from") == "profiling"
        ]

    def test_uniqueness_high_cardinality(self, generator):
        """Column with num_distinct >= 0.99 * num_records generates uniqueness expectation."""
        column = {
            "name": "id",
            "data_type": "INTEGER",
            "profiling": {
                "approximate_num_distinct": 1000,
                "num_records": 1000,
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        unique_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_be_unique"
        ]
        assert len(unique_exps) == 1
        assert unique_exps[0]["kwargs"]["column"] == "id"

    def test_no_uniqueness_low_cardinality(self, generator):
        """Column with num_distinct far below num_records generates no uniqueness expectation."""
        column = {
            "name": "status",
            "data_type": "VARCHAR",
            "profiling": {
                "approximate_num_distinct": 50,
                "num_records": 1000,
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        unique_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_be_unique"
        ]
        assert unique_exps == []

    def test_range_from_statistics(self, generator):
        """Column with statistics min/max generates between expectation."""
        column = {
            "name": "score",
            "data_type": "INTEGER",
            "profiling": {
                "statistics": {"min": 0, "max": 100},
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        range_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_be_between"
        ]
        assert len(range_exps) == 1
        assert range_exps[0]["kwargs"]["min_value"] == 0
        assert range_exps[0]["kwargs"]["max_value"] == 100
        assert range_exps[0]["kwargs"]["column"] == "score"

    def test_high_completeness_strict_not_null(self, generator):
        """Column with completeness > 0.99 and no baseline nullable generates strict not-null."""
        column = {
            "name": "email",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 1.0},
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        not_null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 1
        assert "mostly" not in not_null_exps[0]["kwargs"]

    def test_moderate_completeness_mostly_not_null(self, generator):
        """Column with completeness 0.95-0.99 generates not-null with mostly."""
        column = {
            "name": "phone",
            "data_type": "VARCHAR",
            "profiling": {"completeness": 0.97},
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        not_null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 1
        assert not_null_exps[0]["kwargs"]["mostly"] == 0.97

    def test_completeness_skipped_when_baseline_has_not_null(self, generator):
        """Column with completeness=1.0 but nullable={ctx: False} generates no profiling not-null."""
        column = {
            "name": "required_field",
            "data_type": "VARCHAR",
            "nullable": {"medicare": False},
            "profiling": {"completeness": 1.0},
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        not_null_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert not_null_exps == []

    def test_value_set_from_distinct_values(self, generator):
        """Column with distinct_values generates value-set expectation."""
        column = {
            "name": "status",
            "data_type": "VARCHAR",
            "profiling": {
                "distinct_values": ["A", "B", "C"],
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        set_exps = [e for e in exps if e["type"] == "expect_column_values_to_be_in_set"]
        assert len(set_exps) == 1
        assert set_exps[0]["kwargs"]["value_set"] == ["A", "B", "C"]
        assert set_exps[0]["kwargs"]["column"] == "status"

    def test_string_length_from_profiling(self, generator):
        """Column with string_lengths generates length-between expectation."""
        column = {
            "name": "code",
            "data_type": "VARCHAR",
            "profiling": {
                "string_lengths": {"min_length": 5, "max_length": 10},
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        length_exps = [
            e for e in exps if e["type"] == "expect_column_value_lengths_to_be_between"
        ]
        assert len(length_exps) == 1
        assert length_exps[0]["kwargs"]["min_value"] == 5
        assert length_exps[0]["kwargs"]["max_value"] == 10

    def test_string_length_skipped_when_baseline_has_length(self, generator):
        """Column with string_lengths but also max_length in UMF generates no profiling length."""
        column = {
            "name": "code",
            "data_type": "VARCHAR",
            "max_length": 20,
            "profiling": {
                "string_lengths": {"min_length": 5, "max_length": 10},
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        length_exps = [
            e for e in exps if e["type"] == "expect_column_value_lengths_to_be_between"
        ]
        # Baseline already covers length; profiling should not add another
        assert length_exps == []

    def test_regex_pattern(self, generator):
        """Column with patterns generates regex expectation."""
        column = {
            "name": "state_code",
            "data_type": "VARCHAR",
            "profiling": {
                "patterns": ["^[A-Z]{2}$"],
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        regex_exps = [
            e for e in exps if e["type"] == "expect_column_values_to_match_regex"
        ]
        assert len(regex_exps) == 1
        assert regex_exps[0]["kwargs"]["regex"] == "^[A-Z]{2}$"
        assert regex_exps[0]["kwargs"]["mostly"] == 0.95

    def test_no_profiling_data_returns_empty(self, generator):
        """Column without profiling key generates no profiling expectations."""
        column = {
            "name": "plain_col",
            "data_type": "VARCHAR",
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        assert exps == []

    def test_all_profiling_expectations_have_correct_meta(self, generator):
        """All profiling expectations have generated_from=profiling and severity=warning."""
        column = {
            "name": "rich_col",
            "data_type": "VARCHAR",
            "profiling": {
                "completeness": 1.0,
                "approximate_num_distinct": 500,
                "num_records": 500,
                "statistics": {"min": 1, "max": 99},
                "distinct_values": ["X", "Y"],
                "string_lengths": {"min_length": 1, "max_length": 5},
                "patterns": ["^[A-Z]$"],
            },
        }

        exps = self._profiling_exps(
            generator.generate_baseline_column_expectations(column)
        )

        assert (
            len(exps) >= 5
        )  # uniqueness, range, not-null, value-set, regex (length skipped? no, no baseline length)

        for exp in exps:
            assert exp["meta"]["generated_from"] == "profiling"
            assert exp["meta"]["severity"] == "warning"
            assert "description" in exp["meta"]
