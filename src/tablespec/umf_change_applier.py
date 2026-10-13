"""Apply individual UMF changes to create modified UMF versions.

Provides functions to apply column, validation rule, and metadata changes
to a UMF object, enabling atomic per-change commits during Excel import.
"""

import copy

from tablespec.models import UMF
from tablespec.umf_diff import (
    UMFChangeType,
    UMFColumnChange,
    UMFMetadataChange,
    UMFValidationChange,
)


def apply_column_change(umf: UMF, change: UMFColumnChange) -> UMF:
    """Apply a column change to a UMF, returning modified copy.

    Args:
        umf: Original UMF
        change: Column change to apply

    Returns:
        New UMF with change applied

    """
    result = copy.deepcopy(umf)

    if change.change_type == UMFChangeType.ADDED:
        # Add new column
        if change.new_column is None:
            msg = "New column required for ADD change"
            raise ValueError(msg)
        result.columns.append(change.new_column)

    elif change.change_type == UMFChangeType.REMOVED:
        # Remove column
        result.columns = [c for c in result.columns if c.name != change.column_name]

    elif change.change_type == UMFChangeType.MODIFIED:
        # Modify column
        if change.new_column is None or change.changed_fields is None:
            msg = "New column and changed_fields required for MODIFIED change"
            raise ValueError(msg)

        # Find column and replace it
        for i, col in enumerate(result.columns):
            if col.name == change.column_name:
                result.columns[i] = change.new_column
                break

    return result


def apply_validation_change(umf: UMF, change: UMFValidationChange) -> UMF:
    """Apply a validation rule change to a UMF, returning modified copy.

    Uses (column, rule_type, rule_index) as the key for matching rules.
    Preserves order of expectations in the list.

    Note: This function operates on UMF models that use the expectations-based
    validation_rules format (list of dicts with type/kwargs/meta). If the
    validation_rules model does not have an 'expectations' attribute, this
    function will attempt to create one.

    Args:
        umf: Original UMF
        change: Validation change to apply

    Returns:
        New UMF with change applied

    """
    result = copy.deepcopy(umf)

    # Ensure validation_rules exists
    if result.validation_rules is None:
        try:
            from tablespec.models import ValidationRules

            result.validation_rules = ValidationRules(expectations=[])
        except (ImportError, TypeError):
            # ValidationRules model may not accept 'expectations' parameter
            # in the current schema; skip validation change application
            return result

    # Get current expectations list (handle both attribute and dict styles)
    if hasattr(result.validation_rules, "expectations"):
        current_expectations = list(
            getattr(result.validation_rules, "expectations", None) or []
        )
    elif isinstance(result.validation_rules, dict):
        current_expectations = list(result.validation_rules.get("expectations", []))
    else:
        # Cannot apply validation changes to this validation_rules structure
        return result

    # Extract the rule key from the change
    column, rule_type, rule_index = change.rule_key

    if change.change_type == UMFChangeType.ADDED:
        # Add new expectation (append to end)
        if change.new_rule is None:
            msg = "New rule required for ADD change"
            raise ValueError(msg)
        current_expectations.append(change.new_rule)

    elif change.change_type == UMFChangeType.REMOVED:
        # Remove expectation by key (preserve order of remaining)
        current_expectations = [
            exp
            for exp in current_expectations
            if not _rule_matches_key(exp, column, rule_type, rule_index)
        ]

    elif change.change_type == UMFChangeType.MODIFIED:
        # Modify expectation in-place (same position)
        if change.new_rule is None:
            msg = "New rule required for MODIFIED change"
            raise ValueError(msg)

        for i, exp in enumerate(current_expectations):
            if _rule_matches_key(exp, column, rule_type, rule_index):
                current_expectations[i] = change.new_rule
                break

    # Set expectations back
    if hasattr(result.validation_rules, "expectations"):
        result.validation_rules.expectations = current_expectations
    elif isinstance(result.validation_rules, dict):
        result.validation_rules["expectations"] = current_expectations

    return result


def _rule_matches_key(exp: dict, column: str, rule_type: str, rule_index: int) -> bool:
    """Check if an expectation matches the given (column, rule_type, rule_index) key.

    Args:
        exp: Expectation dict
        column: Column name (or "-" for table-level)
        rule_type: Rule type (without "expect_" prefix)
        rule_index: Rule index

    Returns:
        True if the expectation matches the key

    """
    exp_column = exp.get("kwargs", {}).get("column", "-")
    exp_rule_type = exp.get("type", "").removeprefix("expect_")
    exp_rule_index = exp.get("meta", {}).get("rule_index", 0)

    return (
        exp_column == column
        and exp_rule_type == rule_type
        and exp_rule_index == rule_index
    )


def apply_metadata_change(umf: UMF, change: UMFMetadataChange) -> UMF:
    """Apply a metadata change to a UMF, returning modified copy.

    Args:
        umf: Original UMF
        change: Metadata change to apply

    Returns:
        New UMF with change applied

    """
    result = copy.deepcopy(umf)
    setattr(result, change.field_name, change.new_value)
    return result


def apply_changes_sequentially(
    umf: UMF,
    column_changes: list[UMFColumnChange] | None = None,
    validation_changes: list[UMFValidationChange] | None = None,
    metadata_changes: list[UMFMetadataChange] | None = None,
) -> UMF:
    """Apply multiple changes to a UMF sequentially.

    Args:
        umf: Original UMF
        column_changes: Column changes to apply in order
        validation_changes: Validation changes to apply in order
        metadata_changes: Metadata changes to apply in order

    Returns:
        UMF with all changes applied

    """
    result = umf

    # Apply column changes first
    for change in column_changes or []:
        result = apply_column_change(result, change)

    # Then validation changes
    for change in validation_changes or []:
        result = apply_validation_change(result, change)

    # Finally metadata changes
    for change in metadata_changes or []:
        result = apply_metadata_change(result, change)

    return result


def get_affected_files(
    umf_dir,
    change: UMFColumnChange | UMFValidationChange | UMFMetadataChange,
) -> list:
    """Get list of files affected by a change (for commit purposes).

    Args:
        umf_dir: Path to UMF directory
        change: Change to analyze

    Returns:
        List of file paths affected by this change

    """
    from pathlib import Path

    umf_dir = Path(umf_dir)
    affected = []

    if isinstance(change, UMFColumnChange):
        # Column change affects the columns directory (split format only)
        columns_dir = umf_dir / "columns"
        if columns_dir.exists():
            # Each column might be its own file
            # For now, return all column files since we don't know the exact structure
            affected.extend(columns_dir.glob("*.yaml"))

    elif isinstance(change, UMFValidationChange):
        # Validation change affects validation_rules.yaml
        validation_rules_file = umf_dir / "validation_rules.yaml"
        if validation_rules_file.exists():
            affected.append(validation_rules_file)

    elif isinstance(change, UMFMetadataChange):
        # Metadata change affects table-level files
        for ext in [".yaml", ".yml"]:
            table_file = umf_dir / f"table{ext}"
            if table_file.exists():
                affected.append(table_file)
                break

    return affected
