# @covers US-036-AC1
"""Tests for UMF authoring mutation functions."""

import pytest

from tests.builders import UMFBuilder
from tablespec.authoring.mutations import (
    add_column,
    modify_column,
    remove_column,
    remove_expectation,
    rename_column,
)
from tablespec.models.umf import UMF, Expectation, ExpectationMeta, ExpectationSuite

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]


class TestAddColumn:
    def test_adds_column(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        result = add_column(umf, "name", "VARCHAR", length=50)
        assert len(result.columns) == 2
        assert result.columns[1].name == "name"

    def test_duplicate_raises(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        with pytest.raises(ValueError, match="already exists"):
            add_column(umf, "id", "VARCHAR")

    def test_original_unchanged(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        result = add_column(umf, "name", "VARCHAR")
        assert len(umf.columns) == 1  # original unchanged
        assert len(result.columns) == 2

    def test_result_passes_validation(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        result = add_column(umf, "name", "VARCHAR", length=50, description="A name")
        result.model_dump()  # Pydantic validation


class TestRemoveColumn:
    def test_removes_column(self):
        umf = (
            UMFBuilder("t")
            .column("id", "INTEGER")
            .column("name", "VARCHAR", length=50)
            .build()
        )
        result = remove_column(umf, "name")
        assert len(result.columns) == 1
        assert result.columns[0].name == "id"

    def test_not_found_raises(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        with pytest.raises(ValueError, match="not found"):
            remove_column(umf, "nonexistent")


class TestRenameColumn:
    def test_renames(self):
        umf = UMFBuilder("t").column("old_name", "INTEGER").build()
        result = rename_column(umf, "old_name", "new_name")
        assert result.columns[0].name == "new_name"

    def test_keep_alias(self):
        umf = UMFBuilder("t").column("old_name", "INTEGER").build()
        result = rename_column(umf, "old_name", "new_name", keep_alias=True)
        assert result.columns[0].name == "new_name"
        assert "old_name" in (result.columns[0].aliases or [])

    def test_not_found_raises(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        with pytest.raises(ValueError, match="not found"):
            rename_column(umf, "missing", "new_col")

    def test_duplicate_target_raises(self):
        umf = UMFBuilder("t").column("a", "INTEGER").column("b", "INTEGER").build()
        with pytest.raises(ValueError, match="already exists"):
            rename_column(umf, "a", "b")


class TestModifyColumn:
    def test_modifies_description(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        result = modify_column(umf, "id", description="Primary key")
        assert result.columns[0].description == "Primary key"

    def test_modifies_length(self):
        umf = UMFBuilder("t").column("name", "VARCHAR", length=50).build()
        result = modify_column(umf, "name", length=100)
        assert result.columns[0].length == 100

    def test_not_found_raises(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        with pytest.raises(ValueError, match="not found"):
            modify_column(umf, "missing", description="nope")

    def test_original_unchanged(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        result = modify_column(umf, "id", description="Primary key")
        assert umf.columns[0].description is None
        assert result.columns[0].description == "Primary key"


class TestRemoveExpectation:
    @staticmethod
    def _umf_with_suite() -> UMF:
        umf = (
            UMFBuilder("t").column("id", "INTEGER").column("amount", "DECIMAL").build()
        )
        suite = ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_not_be_null",
                    kwargs={"column": "id"},
                    meta=ExpectationMeta(stage="raw", severity="critical"),
                ),
                Expectation(
                    type="expect_column_values_to_be_between",
                    kwargs={"column": "amount", "min_value": 0},
                    meta=ExpectationMeta(stage="ingested", severity="warning"),
                ),
                Expectation(
                    type="expect_column_values_to_not_be_null",
                    kwargs={"column": "amount"},
                    meta=ExpectationMeta(stage="raw", severity="critical"),
                ),
            ],
        )
        return umf.model_copy(update={"expectations": suite})

    def test_removes_matching_type_and_column(self):
        umf = self._umf_with_suite()
        result, count = remove_expectation(
            umf, "expect_column_values_to_not_be_null", "id"
        )
        assert count == 1
        assert len(result.expectations.expectations) == 2

    def test_removes_all_matching_type(self):
        umf = self._umf_with_suite()
        result, count = remove_expectation(umf, "expect_column_values_to_not_be_null")
        assert count == 2
        assert len(result.expectations.expectations) == 1
        assert (
            result.expectations.expectations[0].type
            == "expect_column_values_to_be_between"
        )

    def test_no_match_returns_original(self):
        umf = self._umf_with_suite()
        result, count = remove_expectation(umf, "expect_column_to_exist")
        assert count == 0
        assert result is umf

    def test_updates_only_expectations_field(self):
        """Verify remove_expectation mutates only umf.expectations, not legacy fields."""
        umf = self._umf_with_suite()
        result, count = remove_expectation(umf, "expect_column_values_to_be_between")
        assert count == 1
        # expectations field is updated
        assert len(result.expectations.expectations) == 2
        # legacy fields are untouched (None on the builder-produced UMF)
        assert result.quality_checks is None
        assert result.validation_rules is None

    def test_removes_from_migrated_legacy_expectations(self):
        umf = UMF(
            version="1.0",
            table_name="t",
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

        result, count = remove_expectation(
            umf, "expect_column_values_to_not_be_null", "id"
        )

        assert count == 1
        assert result.expectations is not None
        assert result.expectations.expectations == []
        assert result.validation_rules is None
        assert result.quality_checks is None
