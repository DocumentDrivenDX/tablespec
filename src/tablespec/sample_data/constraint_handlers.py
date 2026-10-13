"""Constraint validation and enforcement for sample data generation."""

import logging
from typing import Any


class ConstraintHandlers:
    """Handles constraint checking and enforcement during data generation."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def should_apply_equality_constraint(
        record: dict[str, Any],
        _col_name: str,
        other_col: str,
        ignore_row_if: str,
    ) -> bool:
        """Check if equality constraint should be applied based on ignore_row_if logic.

        Args:
            record: Current partially-built record
            _col_name: Current column name (being generated, not yet in record) - unused but kept for API consistency
            other_col: Other column in equality constraint (may already be in record)
            ignore_row_if: Ignore condition ('never', 'either_value_is_missing', 'both_values_are_missing')

        Returns:
            True if constraint should be applied, False otherwise

        """
        if ignore_row_if == "never":
            return True

        # Note: _col_name hasn't been generated yet, so we only check other_col
        other_value = record.get(other_col)

        if ignore_row_if == "either_value_is_missing":
            # Apply constraint if the other column has a value
            # (we're generating the current column now, so it will have a value)
            return other_value is not None
        if ignore_row_if == "both_values_are_missing":
            # Apply constraint if the other column has a value
            # (we're generating the current column now, so it will have a value)
            return other_value is not None

        # Unknown ignore_row_if value, default to applying constraint
        return True

    @staticmethod
    def should_apply_unique_within_record_constraint(
        record: dict[str, Any],
        constraint_columns: list[str],
        ignore_row_if: str,
    ) -> bool:
        """Check if unique-within-record constraint should be applied.

        Args:
            record: Current partially-built record
            constraint_columns: List of columns in the constraint
            ignore_row_if: Ignore condition ('never', 'any_value_is_missing', 'all_values_are_missing')

        Returns:
            True if constraint should be applied, False otherwise

        """
        if ignore_row_if == "never":
            return True

        # Check which columns have been generated and have values
        values = [record.get(col) for col in constraint_columns if col in record]

        if ignore_row_if == "any_value_is_missing":
            # Apply constraint only if all columns are present and non-null
            return all(v is not None for v in values) and len(values) == len(
                constraint_columns
            )
        if ignore_row_if == "all_values_are_missing":
            # Apply constraint unless all values are missing
            return any(v is not None for v in values)

        # Unknown ignore_row_if value, default to applying constraint
        return True

    def ensure_distinct_from_columns(
        self,
        value: Any,
        record: dict[str, Any],
        constraint_columns: list[str],
        current_col: str,
        enable_debug: bool,
    ) -> Any:
        """Ensure generated value differs from other columns in unique-within-record constraint.

        Args:
            value: Generated value to check/modify
            record: Current partially-built record
            constraint_columns: List of columns that must have distinct values
            current_col: Current column name
            enable_debug: Whether debug logging is enabled

        Returns:
            Modified value that is distinct from other columns in the group

        """
        if value is None:
            return value

        # Collect values from other columns in this constraint group
        other_values = [
            record.get(col)
            for col in constraint_columns
            if col != current_col and col in record and record.get(col) is not None
        ]

        if not other_values:
            # No other values to compare against
            return value

        # Check if current value conflicts with any other column
        max_attempts = 100
        attempt = 0
        original_value = value

        while value in other_values and attempt < max_attempts:
            attempt += 1

            # Add suffix to make distinct
            if isinstance(value, str):
                # Strip previous suffixes before adding new one
                base_value = str(original_value).rsplit("_", 1)[0]
                value = f"{base_value}_v{attempt}"
            elif isinstance(value, (int, float)):
                value = original_value + attempt
            else:
                # For other types, convert to string and add suffix
                value = f"{original_value}_v{attempt}"

        if attempt >= max_attempts:
            self.logger.warning(
                f"Failed to make {current_col} distinct from {constraint_columns} after {max_attempts} attempts"
            )

        if enable_debug and attempt > 0:
            self.logger.info(
                f"DEBUG: Made {current_col} distinct: {original_value} -> {value} (attempt={attempt})"
            )

        return value
