"""Unit tests for constraint_handlers module."""

import pytest

from tablespec.sample_data.constraint_handlers import ConstraintHandlers

pytestmark = pytest.mark.fast


class TestShouldApplyEqualityConstraint:
    """Test should_apply_equality_constraint logic."""

    @pytest.mark.parametrize(
        ("ignore_row_if", "other_value", "expected"),
        [
            # ignore_row_if='never' - always apply
            ("never", "value123", True),
            ("never", None, True),
            # ignore_row_if='either_value_is_missing' - apply if other has value
            ("either_value_is_missing", "value123", True),
            ("either_value_is_missing", None, False),
            # ignore_row_if='both_values_are_missing' - apply if other has value
            ("both_values_are_missing", "value123", True),
            ("both_values_are_missing", None, False),
        ],
    )
    def test_equality_constraint_conditions(self, ignore_row_if, other_value, expected):
        """Test equality constraint application with different conditions."""
        record = {"other_col": other_value}
        result = ConstraintHandlers.should_apply_equality_constraint(
            record=record,
            _col_name="current_col",
            other_col="other_col",
            ignore_row_if=ignore_row_if,
        )
        assert result == expected

    def test_never_always_applies(self):
        """Test that 'never' ignore condition always applies constraint."""
        record = {"other_col": "some_value"}
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "col_a", "other_col", "never"
        )

        record = {"other_col": None}
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "col_a", "other_col", "never"
        )

        record = {}  # other_col not even present
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "col_a", "other_col", "never"
        )

    def test_either_value_missing_logic(self):
        """Test 'either_value_is_missing' condition."""
        # Other column has value -> apply
        record = {"other_col": "value"}
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "either_value_is_missing"
        )

        # Other column is None -> don't apply
        record = {"other_col": None}
        assert not ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "either_value_is_missing"
        )

        # Other column missing -> don't apply
        record = {}
        assert not ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "either_value_is_missing"
        )

    def test_both_values_missing_logic(self):
        """Test 'both_values_are_missing' condition."""
        # Other column has value -> apply
        record = {"other_col": "value"}
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "both_values_are_missing"
        )

        # Other column is None -> don't apply
        record = {"other_col": None}
        assert not ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "both_values_are_missing"
        )

    def test_unknown_ignore_condition_defaults_to_apply(self):
        """Test that unknown ignore_row_if values default to applying constraint."""
        record = {"other_col": "value"}
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "current_col", "other_col", "unknown_condition"
        )

    def test_empty_record(self):
        """Test behavior with empty record."""
        record = {}
        # 'never' should still apply
        assert ConstraintHandlers.should_apply_equality_constraint(
            record, "col_a", "col_b", "never"
        )
        # 'either_value_is_missing' should not apply
        assert not ConstraintHandlers.should_apply_equality_constraint(
            record, "col_a", "col_b", "either_value_is_missing"
        )


class TestShouldApplyUniqueWithinRecordConstraint:
    """Test should_apply_unique_within_record_constraint logic."""

    @pytest.mark.parametrize(
        ("ignore_row_if", "record", "constraint_columns", "expected"),
        [
            # ignore_row_if='never' - always apply
            ("never", {"col_a": "val1", "col_b": "val2"}, ["col_a", "col_b"], True),
            ("never", {"col_a": None, "col_b": None}, ["col_a", "col_b"], True),
            # ignore_row_if='any_value_is_missing' - apply only if all present and non-null
            (
                "any_value_is_missing",
                {"col_a": "val1", "col_b": "val2"},
                ["col_a", "col_b"],
                True,
            ),
            (
                "any_value_is_missing",
                {"col_a": "val1", "col_b": None},
                ["col_a", "col_b"],
                False,
            ),
            ("any_value_is_missing", {"col_a": "val1"}, ["col_a", "col_b"], False),
            # ignore_row_if='all_values_are_missing' - apply unless all missing
            (
                "all_values_are_missing",
                {"col_a": "val1", "col_b": "val2"},
                ["col_a", "col_b"],
                True,
            ),
            (
                "all_values_are_missing",
                {"col_a": "val1", "col_b": None},
                ["col_a", "col_b"],
                True,
            ),
            (
                "all_values_are_missing",
                {"col_a": None, "col_b": None},
                ["col_a", "col_b"],
                False,
            ),
        ],
    )
    def test_unique_within_record_conditions(
        self, ignore_row_if, record, constraint_columns, expected
    ):
        """Test unique-within-record constraint with different conditions."""
        result = ConstraintHandlers.should_apply_unique_within_record_constraint(
            record=record,
            constraint_columns=constraint_columns,
            ignore_row_if=ignore_row_if,
        )
        assert result == expected

    def test_never_always_applies(self):
        """Test that 'never' always applies constraint."""
        # All values present
        record = {"col_a": "val1", "col_b": "val2", "col_c": "val3"}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b", "col_c"], "never"
        )

        # Some values missing
        record = {"col_a": "val1", "col_b": None}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b", "col_c"], "never"
        )

        # All values missing
        record = {}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "never"
        )

    def test_any_value_missing_requires_all_present(self):
        """Test 'any_value_is_missing' requires all columns present and non-null."""
        # All present and non-null -> apply
        record = {"col_a": "val1", "col_b": "val2", "col_c": "val3"}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b", "col_c"], "any_value_is_missing"
        )

        # One is None -> don't apply
        record = {"col_a": "val1", "col_b": None, "col_c": "val3"}
        assert not ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b", "col_c"], "any_value_is_missing"
        )

        # One is missing -> don't apply
        record = {"col_a": "val1", "col_c": "val3"}
        assert not ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b", "col_c"], "any_value_is_missing"
        )

    def test_all_values_missing_applies_unless_all_null(self):
        """Test 'all_values_are_missing' applies unless all values are null."""
        # All present and non-null -> apply
        record = {"col_a": "val1", "col_b": "val2"}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "all_values_are_missing"
        )

        # Some null -> apply
        record = {"col_a": "val1", "col_b": None}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "all_values_are_missing"
        )

        # All null -> don't apply
        record = {"col_a": None, "col_b": None}
        assert not ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "all_values_are_missing"
        )

    def test_partially_generated_record(self):
        """Test with record where not all constraint columns are generated yet."""
        # Only col_a generated so far
        record = {"col_a": "val1"}

        # 'any_value_is_missing' should not apply (col_b not yet generated)
        assert not ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "any_value_is_missing"
        )

        # 'all_values_are_missing' should apply (col_a has value)
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "all_values_are_missing"
        )

    def test_unknown_ignore_condition_defaults_to_apply(self):
        """Test that unknown ignore_row_if values default to applying constraint."""
        record = {"col_a": "val1", "col_b": "val2"}
        assert ConstraintHandlers.should_apply_unique_within_record_constraint(
            record, ["col_a", "col_b"], "unknown_condition"
        )


class TestEnsureDistinctFromColumns:
    """Test ensure_distinct_from_columns value modification."""

    def test_no_modification_when_no_conflicts(self):
        """Test that value is unchanged when no conflicts exist."""
        handlers = ConstraintHandlers()
        record = {"col_a": "value_a", "col_b": "value_b"}
        value = "value_c"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        assert result == "value_c"

    def test_modifies_string_value_to_avoid_conflict(self):
        """Test that string values are modified with suffix when conflicts exist."""
        handlers = ConstraintHandlers()
        record = {"col_a": "duplicate", "col_b": "other"}
        value = "duplicate"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should add suffix to make distinct
        assert result.startswith("duplicate")
        assert result != "duplicate"
        assert "_v1" in result

    def test_modifies_numeric_value_to_avoid_conflict(self):
        """Test that numeric values are incremented when conflicts exist."""
        handlers = ConstraintHandlers()
        record = {"col_a": 100, "col_b": 200}
        value = 100

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should increment to make distinct
        assert result == 101

    def test_handles_none_value(self):
        """Test that None values are returned unchanged."""
        handlers = ConstraintHandlers()
        record = {"col_a": "value_a"}
        value = None

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b"],
            current_col="col_b",
            enable_debug=False,
        )

        assert result is None

    def test_no_other_columns_in_record(self):
        """Test when no other columns from constraint group are in record yet."""
        handlers = ConstraintHandlers()
        record = {}
        value = "any_value"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_a",
            enable_debug=False,
        )

        # Should return unchanged since no other values to compare
        assert result == "any_value"

    def test_skips_none_values_in_other_columns(self):
        """Test that None values in other columns are ignored."""
        handlers = ConstraintHandlers()
        record = {"col_a": None, "col_b": "value_b"}
        value = "value_b"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should modify to avoid conflict with col_b
        assert result != "value_b"

    def test_multiple_conflicts_increments_suffix(self):
        """Test that multiple conflicts result in higher suffix numbers."""
        handlers = ConstraintHandlers()
        # Simulate a scenario where first attempt also conflicts
        # This is hard to test directly without mocking, but we can verify the logic
        record = {"col_a": "duplicate", "col_b": "duplicate_v1"}
        value = "duplicate"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should try _v1, see it conflicts, then use _v2
        assert result == "duplicate_v2"

    def test_max_attempts_exceeded_returns_last_attempt(self):
        """Test behavior when max attempts (100) is exceeded."""
        handlers = ConstraintHandlers()
        # Create record where all variations conflict (impossible in practice)
        # For testing, we create a record with many conflicts
        record = {f"col_{i}": "duplicate" for i in range(50)}
        value = "duplicate"

        # Add the conflicting value to constraint columns
        constraint_columns = [f"col_{i}" for i in range(50)] + ["current_col"]

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=constraint_columns,
            current_col="current_col",
            enable_debug=False,
        )

        # Should still return a value (even if duplicate)
        assert result is not None

    def test_float_value_increment(self):
        """Test that float values are incremented correctly."""
        handlers = ConstraintHandlers()
        record = {"col_a": 10.5, "col_b": 20.0}
        value = 10.5

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should increment to 11.5
        assert result == 11.5

    def test_non_string_non_numeric_value(self):
        """Test handling of values that are neither string nor numeric."""
        handlers = ConstraintHandlers()
        record = {"col_a": ["list"], "col_b": "other"}
        value = ["list"]

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "col_c"],
            current_col="col_c",
            enable_debug=False,
        )

        # Should convert to string and add suffix
        assert isinstance(result, str)
        assert "_v1" in result

    def test_current_column_excluded_from_comparison(self):
        """Test that current column is not compared against itself."""
        handlers = ConstraintHandlers()
        # Record already has current_col (shouldn't happen in practice, but test defensively)
        record = {"col_a": "value_a", "col_b": "value_b", "current_col": "existing"}
        value = "existing"

        result = handlers.ensure_distinct_from_columns(
            value=value,
            record=record,
            constraint_columns=["col_a", "col_b", "current_col"],
            current_col="current_col",
            enable_debug=False,
        )

        # Should not conflict with itself
        # Since col_a and col_b have different values, no modification needed
        assert result == "existing"

    def test_debug_logging_enabled(self, caplog):
        """Test that debug logging works when enabled."""
        import logging

        handlers = ConstraintHandlers()
        record = {"col_a": "duplicate"}
        value = "duplicate"

        with caplog.at_level(logging.INFO):
            result = handlers.ensure_distinct_from_columns(
                value=value,
                record=record,
                constraint_columns=["col_a", "col_b"],
                current_col="col_b",
                enable_debug=True,
            )

        # Should have logged the change
        assert "Made col_b distinct" in caplog.text
        assert "duplicate -> duplicate_v1" in caplog.text
        assert result == "duplicate_v1"
