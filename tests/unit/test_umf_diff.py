"""Unit tests for UMFDiff: comparing two UMF objects."""

import pytest

from tablespec.models.umf import UMF, UMFColumn, ValidationRules
from tablespec.umf_diff import (
    UMFChangeType,
    UMFColumnChange,
    UMFComponentType,
    UMFDiff,
    UMFMetadataChange,
    UMFValidationChange,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _make_umf(columns=None, description=None, table_type=None, validation_rules=None):
    """Helper to build a minimal UMF object."""
    cols = columns or [UMFColumn(name="col1", data_type="VARCHAR", length=50)]
    return UMF(
        version="1.0",
        table_name="test_table",
        columns=cols,
        description=description,
        table_type=table_type,
        validation_rules=validation_rules,
    )


def _make_col(name, data_type="VARCHAR", length=None, description=None, **kwargs):
    return UMFColumn(
        name=name, data_type=data_type, length=length, description=description, **kwargs
    )


class TestUMFChangeTypeEnum:
    def test_values(self):
        assert UMFChangeType.ADDED == "added"
        assert UMFChangeType.REMOVED == "removed"
        assert UMFChangeType.MODIFIED == "modified"


class TestUMFComponentTypeEnum:
    def test_values(self):
        assert UMFComponentType.COLUMN == "column"
        assert UMFComponentType.VALIDATION_RULE == "validation_rule"
        assert UMFComponentType.RELATIONSHIP == "relationship"
        assert UMFComponentType.METADATA == "metadata"


class TestUMFColumnChange:
    def test_get_key(self):
        change = UMFColumnChange(
            change_type=UMFChangeType.ADDED, column_name="birth_date"
        )
        assert change.get_key() == "column.birth_date"

    def test_description_added(self):
        change = UMFColumnChange(change_type=UMFChangeType.ADDED, column_name="col1")
        assert change.description() == "Add column col1"

    def test_description_removed(self):
        change = UMFColumnChange(change_type=UMFChangeType.REMOVED, column_name="col1")
        assert change.description() == "Remove column col1"

    def test_description_modified_no_fields(self):
        change = UMFColumnChange(change_type=UMFChangeType.MODIFIED, column_name="col1")
        assert change.description() == "Modify column col1"

    def test_description_modified_with_fields(self):
        change = UMFColumnChange(
            change_type=UMFChangeType.MODIFIED,
            column_name="col1",
            changed_fields={
                "description": ("old desc", "new desc"),
                "data_type": ("VARCHAR", "INTEGER"),
                "length": (50, 100),
                "nullable": (True, False),
                "other_field": ("a", "b"),
            },
        )
        desc = change.description()
        assert "description:" in desc
        assert "type: VARCHAR" in desc
        assert "length: 50" in desc
        assert "nullable changed" in desc
        assert "other_field changed" in desc


class TestUMFValidationChange:
    def test_get_key_column_rule(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("col1", "values_to_not_be_null", 0),
        )
        assert change.get_key() == "validation.col1.values_to_not_be_null.0"

    def test_get_key_table_rule(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("-", "table_row_count", 0),
        )
        assert change.get_key() == "validation.table.table_row_count.0"

    def test_description_added(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.ADDED,
            rule_key=("col1", "not_null", 0),
        )
        assert change.description() == "Add validation col1.not_null.0"

    def test_description_removed(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.REMOVED,
            rule_key=("col1", "not_null", 0),
        )
        assert change.description() == "Remove validation col1.not_null.0"

    def test_description_modified_no_fields(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.MODIFIED,
            rule_key=("col1", "not_null", 0),
        )
        assert change.description() == "Modify validation col1.not_null.0"

    def test_description_modified_with_fields(self):
        change = UMFValidationChange(
            change_type=UMFChangeType.MODIFIED,
            rule_key=("col1", "not_null", 0),
            changed_fields={"severity": ("warning", "error"), "count": (1, 2)},
        )
        desc = change.description()
        assert 'severity: "warning"' in desc
        assert "count: 1" in desc


class TestUMFMetadataChange:
    def test_get_key(self):
        change = UMFMetadataChange(
            field_name="description", old_value="old", new_value="new"
        )
        assert change.get_key() == "metadata.description"

    def test_description_canonical_name(self):
        change = UMFMetadataChange(
            field_name="canonical_name", old_value="Old Name", new_value="New Name"
        )
        assert "canonical_name" in change.description()
        assert "Old Name" in change.description()

    def test_description_aliases(self):
        change = UMFMetadataChange(field_name="aliases", old_value=[], new_value=["a"])
        assert change.description() == "Update aliases"

    def test_description_table_description(self):
        change = UMFMetadataChange(
            field_name="description", old_value="old", new_value="new"
        )
        assert change.description() == "Update table description"

    def test_description_other_field(self):
        change = UMFMetadataChange(
            field_name="table_type", old_value="provided", new_value="lookup"
        )
        assert change.description() == "Update table_type"


class TestUMFDiffColumnChanges:
    def test_new_table_all_columns_added(self):
        new_umf = _make_umf(columns=[_make_col("a"), _make_col("b")])
        diff = UMFDiff(old_umf=None, new_umf=new_umf)
        changes = diff.get_column_changes()
        assert len(changes) == 2
        assert all(c.change_type == UMFChangeType.ADDED for c in changes)
        assert {c.column_name for c in changes} == {"a", "b"}

    def test_no_changes_identical_umfs(self):
        cols = [_make_col("col1", length=50)]
        old = _make_umf(columns=cols)
        new = _make_umf(columns=cols)
        diff = UMFDiff(old, new)
        assert diff.get_column_changes() == []

    def test_column_added(self):
        old = _make_umf(columns=[_make_col("col1")])
        new = _make_umf(columns=[_make_col("col1"), _make_col("col2")])
        diff = UMFDiff(old, new)
        changes = diff.get_column_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.ADDED
        assert changes[0].column_name == "col2"

    def test_column_removed(self):
        old = _make_umf(columns=[_make_col("col1"), _make_col("col2")])
        new = _make_umf(columns=[_make_col("col1")])
        diff = UMFDiff(old, new)
        changes = diff.get_column_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.REMOVED
        assert changes[0].column_name == "col2"

    def test_column_modified(self):
        old = _make_umf(columns=[_make_col("col1", data_type="VARCHAR", length=50)])
        new = _make_umf(columns=[_make_col("col1", data_type="VARCHAR", length=100)])
        diff = UMFDiff(old, new)
        changes = diff.get_column_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.MODIFIED
        assert changes[0].changed_fields["length"] == (50, 100)

    def test_sort_order_removed_added_modified(self):
        old = _make_umf(
            columns=[_make_col("remove_me"), _make_col("modify_me", length=10)]
        )
        new = _make_umf(
            columns=[_make_col("modify_me", length=20), _make_col("add_me")]
        )
        diff = UMFDiff(old, new)
        changes = diff.get_column_changes()
        assert len(changes) == 3
        assert changes[0].change_type == UMFChangeType.REMOVED
        assert changes[1].change_type == UMFChangeType.ADDED
        assert changes[2].change_type == UMFChangeType.MODIFIED

    def test_column_description_change(self):
        old = _make_umf(columns=[_make_col("col1", description="old")])
        new = _make_umf(columns=[_make_col("col1", description="new")])
        diff = UMFDiff(old, new)
        changes = diff.get_column_changes()
        assert len(changes) == 1
        assert "description" in changes[0].changed_fields


class TestUMFDiffValidationChanges:
    def _make_expectation(
        self, col, rule_type, rule_index=0, severity="warning", **extra
    ):
        exp = {
            "type": f"expect_{rule_type}",
            "kwargs": {"column": col} if col != "-" else {},
            "meta": {"rule_index": rule_index, "severity": severity},
        }
        exp.update(extra)
        return exp

    def test_no_validation_rules(self):
        old = _make_umf()
        new = _make_umf()
        diff = UMFDiff(old, new)
        assert diff.get_validation_changes() == []

    def test_new_table_no_old_expectations(self):
        exp = self._make_expectation("col1", "not_null")
        new = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        diff = UMFDiff(old_umf=None, new_umf=new)
        changes = diff.get_validation_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.ADDED

    def test_validation_added(self):
        exp = self._make_expectation("col1", "not_null")
        old = _make_umf(validation_rules=ValidationRules(expectations=[]))
        new = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        diff = UMFDiff(old, new)
        changes = diff.get_validation_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.ADDED

    def test_validation_removed(self):
        exp = self._make_expectation("col1", "not_null")
        old = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        new = _make_umf(validation_rules=ValidationRules(expectations=[]))
        diff = UMFDiff(old, new)
        changes = diff.get_validation_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.REMOVED

    def test_validation_modified(self):
        old_exp = self._make_expectation("col1", "not_null", severity="warning")
        new_exp = self._make_expectation("col1", "not_null", severity="error")
        old = _make_umf(validation_rules=ValidationRules(expectations=[old_exp]))
        new = _make_umf(validation_rules=ValidationRules(expectations=[new_exp]))
        diff = UMFDiff(old, new)
        changes = diff.get_validation_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.MODIFIED

    def test_old_has_rules_new_has_none(self):
        """When new UMF has no validation_rules, removals are detected."""
        exp = self._make_expectation("col1", "not_null")
        old = _make_umf(validation_rules=ValidationRules(expectations=[exp]))
        new = _make_umf()
        diff = UMFDiff(old, new)
        changes = diff.get_validation_changes()
        assert len(changes) == 1
        assert changes[0].change_type == UMFChangeType.REMOVED

    def test_validation_sort_order(self):
        exp1 = self._make_expectation("col1", "not_null", rule_index=0)
        exp2 = self._make_expectation("col1", "unique", rule_index=0)
        exp3_old = self._make_expectation(
            "col1", "in_set", rule_index=0, severity="warning"
        )
        exp3_new = self._make_expectation(
            "col1", "in_set", rule_index=0, severity="error"
        )

        old = _make_umf(validation_rules=ValidationRules(expectations=[exp1, exp3_old]))
        new = _make_umf(validation_rules=ValidationRules(expectations=[exp2, exp3_new]))
        diff = UMFDiff(old, new)
        changes = diff.get_validation_changes()
        types = [c.change_type for c in changes]
        # removed first, then added, then modified
        assert types == [
            UMFChangeType.REMOVED,
            UMFChangeType.ADDED,
            UMFChangeType.MODIFIED,
        ]


class TestUMFDiffMetadataChanges:
    def test_no_changes(self):
        old = _make_umf(description="test", table_type="provided")
        new = _make_umf(description="test", table_type="provided")
        diff = UMFDiff(old, new)
        assert diff.get_metadata_changes() == []

    def test_new_table_returns_empty(self):
        new = _make_umf(description="test")
        diff = UMFDiff(old_umf=None, new_umf=new)
        assert diff.get_metadata_changes() == []

    def test_description_changed(self):
        old = _make_umf(description="old desc")
        new = _make_umf(description="new desc")
        diff = UMFDiff(old, new)
        changes = diff.get_metadata_changes()
        assert len(changes) == 1
        assert changes[0].field_name == "description"
        assert changes[0].old_value == "old desc"
        assert changes[0].new_value == "new desc"

    def test_table_type_changed(self):
        old = _make_umf(table_type="provided")
        new = _make_umf(table_type="lookup")
        diff = UMFDiff(old, new)
        changes = diff.get_metadata_changes()
        field_names = [c.field_name for c in changes]
        assert "table_type" in field_names

    def test_multiple_metadata_changes(self):
        old = _make_umf(description="old", table_type="provided")
        new = _make_umf(description="new", table_type="lookup")
        diff = UMFDiff(old, new)
        changes = diff.get_metadata_changes()
        assert len(changes) == 2


class TestUMFDiffInternalMethods:
    def test_compare_dicts_no_changes(self):
        diff = UMFDiff(old_umf=None, new_umf=_make_umf())
        assert diff._compare_dicts({"a": 1}, {"a": 1}) is None

    def test_compare_dicts_with_changes(self):
        diff = UMFDiff(old_umf=None, new_umf=_make_umf())
        result = diff._compare_dicts({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
        assert result == {"b": (2, 3), "c": (None, 4)}

    def test_compare_dicts_with_exclude(self):
        diff = UMFDiff(old_umf=None, new_umf=_make_umf())
        result = diff._compare_dicts(
            {"a": 1, "b": 2}, {"a": 99, "b": 3}, exclude_keys={"a"}
        )
        assert result == {"b": (2, 3)}

    def test_compare_validation_rules_excludes_meta_internals(self):
        diff = UMFDiff(old_umf=None, new_umf=_make_umf())
        old_rule = {
            "type": "expect_not_null",
            "meta": {"rule_index": 0, "severity": "warning"},
        }
        new_rule = {
            "type": "expect_not_null",
            "meta": {"rule_index": 1, "severity": "error"},
        }
        result = diff._compare_validation_rules(old_rule, new_rule)
        # rule_index is excluded, but severity is tracked
        assert "meta.severity" in result
        assert "meta.rule_index" not in result
