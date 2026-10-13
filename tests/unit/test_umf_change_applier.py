"""Unit tests for umf_change_applier: applying atomic changes to UMF objects."""

import pytest

from tablespec.models.umf import UMF, UMFColumn, ValidationRules
from tablespec.umf_change_applier import (
    apply_changes_sequentially,
    apply_column_change,
    apply_metadata_change,
    apply_validation_change,
)
from tablespec.umf_diff import (
    UMFChangeType,
    UMFColumnChange,
    UMFMetadataChange,
    UMFValidationChange,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _make_umf(columns=None, description=None, table_type=None, validation_rules=None):
    cols = columns or [UMFColumn(name="col1", data_type="VARCHAR", length=50)]
    return UMF(
        version="1.0",
        table_name="test_table",
        columns=cols,
        description=description,
        table_type=table_type,
        validation_rules=validation_rules,
    )


def _make_col(name, data_type="VARCHAR", length=None, description=None):
    return UMFColumn(
        name=name, data_type=data_type, length=length, description=description
    )


class TestApplyColumnChange:
    def test_add_column(self):
        umf = _make_umf(columns=[_make_col("col1")])
        new_col = _make_col("col2", data_type="INTEGER")
        change = UMFColumnChange(
            change_type=UMFChangeType.ADDED,
            column_name="col2",
            new_column=new_col,
        )
        result = apply_column_change(umf, change)
        assert len(result.columns) == 2
        assert result.columns[1].name == "col2"
        # Original is not mutated
        assert len(umf.columns) == 1

    def test_add_column_missing_new_column_raises(self):
        umf = _make_umf()
        change = UMFColumnChange(
            change_type=UMFChangeType.ADDED,
            column_name="col2",
            new_column=None,
        )
        with pytest.raises(ValueError, match="New column required"):
            apply_column_change(umf, change)

    def test_remove_column(self):
        umf = _make_umf(columns=[_make_col("col1"), _make_col("col2")])
        change = UMFColumnChange(
            change_type=UMFChangeType.REMOVED,
            column_name="col2",
        )
        result = apply_column_change(umf, change)
        assert len(result.columns) == 1
        assert result.columns[0].name == "col1"

    def test_modify_column(self):
        umf = _make_umf(columns=[_make_col("col1", length=50)])
        new_col = _make_col("col1", length=100)
        change = UMFColumnChange(
            change_type=UMFChangeType.MODIFIED,
            column_name="col1",
            old_column=umf.columns[0],
            new_column=new_col,
            changed_fields={"length": (50, 100)},
        )
        result = apply_column_change(umf, change)
        assert result.columns[0].length == 100

    def test_modify_column_missing_fields_raises(self):
        umf = _make_umf()
        change = UMFColumnChange(
            change_type=UMFChangeType.MODIFIED,
            column_name="col1",
            new_column=None,
            changed_fields=None,
        )
        with pytest.raises(ValueError, match="New column and changed_fields required"):
            apply_column_change(umf, change)

    def test_does_not_mutate_original(self):
        umf = _make_umf(columns=[_make_col("col1"), _make_col("col2")])
        change = UMFColumnChange(
            change_type=UMFChangeType.REMOVED,
            column_name="col2",
        )
        apply_column_change(umf, change)
        assert len(umf.columns) == 2


class TestApplyValidationChange:
    def _make_expectation(self, col, rule_type, rule_index=0, severity="warning"):
        return {
            "type": f"expect_{rule_type}",
            "kwargs": {"column": col} if col != "-" else {},
            "meta": {"rule_index": rule_index, "severity": severity},
        }

    def test_add_validation(self):
        umf = _make_umf(validation_rules=ValidationRules(expectations=[]))
        new_rule = self._make_expectation("col1", "not_null")
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("col1", "not_null", 0),
            new_rule=new_rule,
        )
        result = apply_validation_change(umf, change)
        assert len(result.validation_rules.expectations) == 1

    def test_add_validation_missing_rule_raises(self):
        umf = _make_umf(validation_rules=ValidationRules(expectations=[]))
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("col1", "not_null", 0),
            new_rule=None,
        )
        with pytest.raises(ValueError, match="New rule required"):
            apply_validation_change(umf, change)

    def test_remove_validation(self):
        exp = self._make_expectation("col1", "not_null")
        umf = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        change = UMFValidationChange(
            change_type=UMFChangeType.REMOVED,
            rule_key=("col1", "not_null", 0),
        )
        result = apply_validation_change(umf, change)
        assert len(result.validation_rules.expectations) == 0

    def test_modify_validation(self):
        old_exp = self._make_expectation("col1", "not_null", severity="warning")
        new_exp = self._make_expectation("col1", "not_null", severity="error")
        umf = _make_umf(validation_rules=ValidationRules(expectations=[old_exp]))
        change = UMFValidationChange(
            change_type=UMFChangeType.MODIFIED,
            rule_key=("col1", "not_null", 0),
            new_rule=new_exp,
        )
        result = apply_validation_change(umf, change)
        assert result.validation_rules.expectations[0]["meta"]["severity"] == "error"

    def test_modify_validation_missing_rule_raises(self):
        exp = self._make_expectation("col1", "not_null")
        umf = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        change = UMFValidationChange(
            change_type=UMFChangeType.MODIFIED,
            rule_key=("col1", "not_null", 0),
            new_rule=None,
        )
        with pytest.raises(ValueError, match="New rule required"):
            apply_validation_change(umf, change)

    def test_create_validation_rules_when_none(self):
        umf = _make_umf()
        assert umf.validation_rules is None
        new_rule = self._make_expectation("col1", "not_null")
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("col1", "not_null", 0),
            new_rule=new_rule,
        )
        result = apply_validation_change(umf, change)
        assert result.validation_rules is not None
        assert len(result.validation_rules.expectations) == 1

    def test_does_not_mutate_original(self):
        exp = self._make_expectation("col1", "not_null")
        umf = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        change = UMFValidationChange(
            change_type=UMFChangeType.REMOVED,
            rule_key=("col1", "not_null", 0),
        )
        apply_validation_change(umf, change)
        assert len(umf.validation_rules.expectations) == 1


class TestApplyMetadataChange:
    def test_change_description(self):
        umf = _make_umf(description="old")
        change = UMFMetadataChange(
            field_name="description", old_value="old", new_value="new"
        )
        result = apply_metadata_change(umf, change)
        assert result.description == "new"
        assert umf.description == "old"

    def test_change_table_type(self):
        umf = _make_umf(table_type="provided")
        change = UMFMetadataChange(
            field_name="table_type", old_value="provided", new_value="lookup"
        )
        result = apply_metadata_change(umf, change)
        assert result.table_type == "lookup"


class TestApplyChangesSequentially:
    def test_apply_multiple_column_changes(self):
        umf = _make_umf(columns=[_make_col("col1")])
        changes = [
            UMFColumnChange(
                change_type=UMFChangeType.ADDED,
                column_name="col2",
                new_column=_make_col("col2"),
            ),
            UMFColumnChange(
                change_type=UMFChangeType.ADDED,
                column_name="col3",
                new_column=_make_col("col3"),
            ),
        ]
        result = apply_changes_sequentially(umf, column_changes=changes)
        assert len(result.columns) == 3

    def test_apply_all_change_types(self):
        exp = {
            "type": "expect_not_null",
            "kwargs": {"column": "col1"},
            "meta": {"rule_index": 0, "severity": "warning"},
        }
        umf = _make_umf(
            columns=[_make_col("col1")],
            description="old",
            validation_rules=ValidationRules(expectations=[]),
        )
        result = apply_changes_sequentially(
            umf,
            column_changes=[
                UMFColumnChange(
                    change_type=UMFChangeType.ADDED,
                    column_name="col2",
                    new_column=_make_col("col2"),
                ),
            ],
            validation_changes=[
                UMFValidationChange(
                    change_type=UMFChangeType.ADDED,
                    rule_key=("col1", "not_null", 0),
                    new_rule=exp,
                ),
            ],
            metadata_changes=[
                UMFMetadataChange(
                    field_name="description", old_value="old", new_value="new"
                ),
            ],
        )
        assert len(result.columns) == 2
        assert len(result.validation_rules.expectations) == 1
        assert result.description == "new"

    def test_apply_empty_changes(self):
        umf = _make_umf()
        result = apply_changes_sequentially(umf)
        assert result.table_name == umf.table_name

    def test_apply_none_changes(self):
        umf = _make_umf()
        result = apply_changes_sequentially(
            umf,
            column_changes=None,
            validation_changes=None,
            metadata_changes=None,
        )
        assert result.table_name == umf.table_name
