"""Tests for context_column-based conditional nullable expectation generation."""

from __future__ import annotations

import pytest

from tablespec.gx_baseline import BaselineExpectationGenerator

pytestmark = pytest.mark.fast


@pytest.fixture
def generator():
    return BaselineExpectationGenerator()


class TestConditionalNullable:
    """When context_column is set, per-context not-null expectations use row_condition."""

    def test_per_context_expectations_with_context_column(
        self, generator: BaselineExpectationGenerator
    ):
        umf_data = {
            "context_column": "LOB",
            "columns": [
                {
                    "name": "member_id",
                    "data_type": "VARCHAR",
                    "nullable": {"MD": False, "MP": True, "ME": False},
                },
            ],
        }
        expectations = generator.generate_baseline_expectations(
            umf_data, include_structural=False
        )

        # Should generate one not-null per non-nullable context (MD and ME)
        not_null_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 2

        # Each should have a row_condition
        conditions = {e["kwargs"]["row_condition"] for e in not_null_exps}
        assert "LOB='MD'" in conditions
        assert "LOB='ME'" in conditions

        # Each should have condition_parser=spark
        for exp in not_null_exps:
            assert exp["kwargs"]["condition_parser"] == "spark"

    def test_global_not_null_without_context_column(
        self, generator: BaselineExpectationGenerator
    ):
        umf_data = {
            "columns": [
                {
                    "name": "member_id",
                    "data_type": "VARCHAR",
                    "nullable": {"MD": False, "MP": True},
                },
            ],
        }
        expectations = generator.generate_baseline_expectations(
            umf_data, include_structural=False
        )

        not_null_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 1
        # No row_condition — global not-null
        assert "row_condition" not in not_null_exps[0]["kwargs"]

    def test_all_nullable_generates_nothing(
        self, generator: BaselineExpectationGenerator
    ):
        umf_data = {
            "context_column": "LOB",
            "columns": [
                {
                    "name": "optional_field",
                    "data_type": "VARCHAR",
                    "nullable": {"MD": True, "MP": True},
                },
            ],
        }
        expectations = generator.generate_baseline_expectations(
            umf_data, include_structural=False
        )
        not_null_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 0

    def test_custom_context_column_name(self, generator: BaselineExpectationGenerator):
        """context_column works with arbitrary column names, not just 'LOB'."""
        umf_data = {
            "context_column": "segment",
            "columns": [
                {
                    "name": "account_id",
                    "data_type": "VARCHAR",
                    "nullable": {"retail": False, "institutional": True},
                },
            ],
        }
        expectations = generator.generate_baseline_expectations(
            umf_data, include_structural=False
        )
        not_null_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 1
        assert not_null_exps[0]["kwargs"]["row_condition"] == "segment='retail'"

    def test_boolean_nullable_true_no_expectations(
        self, generator: BaselineExpectationGenerator
    ):
        """Boolean nullable=True (from DeequToUmfMapper) should not generate not-null."""
        umf_data = {
            "context_column": "LOB",
            "columns": [
                {
                    "name": "optional_field",
                    "data_type": "VARCHAR",
                    "nullable": True,
                },
            ],
        }
        expectations = generator.generate_baseline_expectations(
            umf_data, include_structural=False
        )
        not_null_exps = [
            e
            for e in expectations
            if e["type"] == "expect_column_values_to_not_be_null"
        ]
        assert len(not_null_exps) == 0


class TestContextColumnValidation:
    def test_valid_context_column_accepted(self):
        """UMF with context_column matching a column name should be valid."""
        from tablespec.models.umf import UMF

        umf = UMF(
            version="1.0",
            table_name="test",
            context_column="lob",
            columns=[
                {"name": "id", "data_type": "VARCHAR"},
                {"name": "lob", "data_type": "VARCHAR"},
            ],
        )
        assert umf.context_column == "lob"

    def test_invalid_context_column_rejected(self):
        """UMF with context_column not matching any column should raise ValueError."""
        from tablespec.models.umf import UMF

        with pytest.raises(ValueError, match="context_column.*nonexistent.*not found"):
            UMF(
                version="1.0",
                table_name="test",
                context_column="nonexistent",
                columns=[
                    {"name": "id", "data_type": "VARCHAR"},
                ],
            )

    def test_none_context_column_accepted(self):
        """UMF with no context_column should be valid."""
        from tablespec.models.umf import UMF

        umf = UMF(
            version="1.0",
            table_name="test",
            columns=[
                {"name": "id", "data_type": "VARCHAR"},
            ],
        )
        assert umf.context_column is None
