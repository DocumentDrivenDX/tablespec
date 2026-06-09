"""Detect and represent differences between two UMF versions.

Provides in-memory comparison of UMF objects to identify:
- Column changes (added, removed, modified)
- Validation rule changes
- Metadata changes (canonical_name, aliases, etc.)
- Relationship changes

Used by Excel import to generate atomic, per-change commits.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from tablespec.expectation_utils import expectation_dicts_from_umf
from tablespec.models import UMF, UMFColumn


class UMFChangeType(str, Enum):
    """Type of change detected in UMF comparison."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class UMFComponentType(str, Enum):
    """Type of component that changed in UMF."""

    COLUMN = "column"
    VALIDATION_RULE = "validation_rule"
    RELATIONSHIP = "relationship"
    METADATA = "metadata"


@dataclass
class UMFColumnChange:
    """Represents a change to a column."""

    change_type: UMFChangeType
    column_name: str
    old_column: UMFColumn | None = None
    new_column: UMFColumn | None = None
    changed_fields: dict[str, tuple[Any, Any]] | None = None

    def get_key(self) -> str:
        """Get the Excel row key for this column change."""
        return f"column.{self.column_name}"

    def description(self) -> str:
        """Generate human-readable description of the change."""
        if self.change_type == UMFChangeType.ADDED:
            return f"Add column {self.column_name}"
        if self.change_type == UMFChangeType.REMOVED:
            return f"Remove column {self.column_name}"
        # MODIFIED
        if not self.changed_fields:
            return f"Modify column {self.column_name}"

        changes = []
        for field, (old_val, new_val) in self.changed_fields.items():
            if field == "description":
                changes.append(f"description: {old_val!r} → {new_val!r}")
            elif field == "data_type":
                changes.append(f"type: {old_val} → {new_val}")
            elif field == "length":
                changes.append(f"length: {old_val} → {new_val}")
            elif field == "nullable":
                changes.append("nullable changed")
            else:
                changes.append(f"{field} changed")

        return f"Modify {self.column_name}: {', '.join(changes)}"


@dataclass
class UMFValidationChange:
    """Represents a change to a validation rule.

    Key is (column, rule_type, rule_index) - stable identity for round-trip edits.
    Severity is NOT part of the key (it's a property, not identity).
    """

    change_type: UMFChangeType
    rule_key: tuple[str, str, int]  # (column, rule_type, rule_index)
    old_rule: dict[str, Any] | None = None
    new_rule: dict[str, Any] | None = None
    changed_fields: dict[str, tuple[Any, Any]] | None = None

    def get_key(self) -> str:
        """Get the Excel row key for this validation change."""
        column, rule_type, index = self.rule_key
        column_str = column if column != "-" else "table"
        return f"validation.{column_str}.{rule_type}.{index}"

    def description(self) -> str:
        """Generate human-readable description of the change."""
        column, rule_type, index = self.rule_key
        column_str = column if column != "-" else "table"

        if self.change_type == UMFChangeType.ADDED:
            return f"Add validation {column_str}.{rule_type}.{index}"
        if self.change_type == UMFChangeType.REMOVED:
            return f"Remove validation {column_str}.{rule_type}.{index}"
        # MODIFIED
        if not self.changed_fields:
            return f"Modify validation {column_str}.{rule_type}.{index}"

        # Show actual field values that changed
        changes = []
        for field, (old_val, new_val) in self.changed_fields.items():
            # Format values for display
            old_str = f'"{old_val}"' if isinstance(old_val, str) else str(old_val)
            new_str = f'"{new_val}"' if isinstance(new_val, str) else str(new_val)
            changes.append(f"{field}: {old_str} → {new_str}")

        return f"Validation {column_str}.{rule_type}.{index}: {', '.join(changes)}"


@dataclass
class UMFMetadataChange:
    """Represents a change to table-level metadata."""

    field_name: str
    old_value: Any
    new_value: Any

    def get_key(self) -> str:
        """Get the Excel row key for this metadata change."""
        return f"metadata.{self.field_name}"

    def description(self) -> str:
        """Generate human-readable description of the change."""
        if self.field_name == "canonical_name":
            return f"Update canonical_name: {self.old_value!r} → {self.new_value!r}"
        if self.field_name == "aliases":
            return "Update aliases"
        if self.field_name == "description":
            return "Update table description"
        return f"Update {self.field_name}"


class UMFDiff:
    """Detect differences between two UMF versions."""

    def __init__(self, old_umf: UMF | None, new_umf: UMF) -> None:
        """Initialize diff detector.

        Args:
            old_umf: Previous UMF version (None if new table)
            new_umf: New UMF version from import

        """
        self.old_umf = old_umf
        self.new_umf = new_umf

    def get_column_changes(self) -> list[UMFColumnChange]:
        """Detect all column additions, removals, and modifications.

        Returns:
            List of ColumnChange objects sorted by change type (removed, added, modified)

        """
        changes: list[UMFColumnChange] = []

        if not self.old_umf:
            # First import - all columns are "added"
            for col in self.new_umf.columns:
                changes.append(
                    UMFColumnChange(
                        change_type=UMFChangeType.ADDED,
                        column_name=col.name,
                        new_column=col,
                    )
                )
            return changes

        # Build maps for comparison
        old_cols_by_name = {col.name: col for col in self.old_umf.columns}
        new_cols_by_name = {col.name: col for col in self.new_umf.columns}

        # Removed columns
        for col_name, old_col in old_cols_by_name.items():
            if col_name not in new_cols_by_name:
                changes.append(
                    UMFColumnChange(
                        change_type=UMFChangeType.REMOVED,
                        column_name=col_name,
                        old_column=old_col,
                    )
                )

        # Added columns
        for col_name, new_col in new_cols_by_name.items():
            if col_name not in old_cols_by_name:
                changes.append(
                    UMFColumnChange(
                        change_type=UMFChangeType.ADDED,
                        column_name=col_name,
                        new_column=new_col,
                    )
                )

        # Modified columns
        for col_name, old_col in old_cols_by_name.items():
            if col_name in new_cols_by_name:
                new_col = new_cols_by_name[col_name]

                changed_fields = self._compare_columns(old_col, new_col)
                if changed_fields:
                    changes.append(
                        UMFColumnChange(
                            change_type=UMFChangeType.MODIFIED,
                            column_name=col_name,
                            old_column=old_col,
                            new_column=new_col,
                            changed_fields=changed_fields,
                        )
                    )

        # Sort: removed first, then added, then modified
        return sorted(
            changes,
            key=lambda c: (
                0
                if c.change_type == UMFChangeType.REMOVED
                else 1
                if c.change_type == UMFChangeType.ADDED
                else 2
            ),
        )

    def get_validation_changes(self) -> list[UMFValidationChange]:
        """Detect all validation rule additions, removals, and modifications.

        Uses (column, rule_type, rule_index) as the composite key.
        Severity is NOT part of the key - it's a property that can change without
        creating a new rule.

        Returns:
            List of UMFValidationChange objects sorted by change type
            (removed, added, modified)

        """
        changes: list[UMFValidationChange] = []

        new_expectations = self._get_expectations(self.new_umf)
        old_expectations = self._get_expectations(self.old_umf) if self.old_umf else []

        if not new_expectations:
            # If new UMF has no rules, detect removals only
            for exp in old_expectations:
                changes.append(
                    UMFValidationChange(
                        change_type=UMFChangeType.REMOVED,
                        rule_key=self._get_rule_key(exp),
                        old_rule=exp,
                    )
                )
            return changes

        # Build maps by (column, rule_type, rule_index)
        old_rules = {}
        new_rules = {}

        for exp in old_expectations:
            key = self._get_rule_key(exp)
            old_rules[key] = exp

        for exp in new_expectations:
            key = self._get_rule_key(exp)
            new_rules[key] = exp

        # Removed: in old but not in new
        for key, old_exp in old_rules.items():
            if key not in new_rules:
                changes.append(
                    UMFValidationChange(
                        change_type=UMFChangeType.REMOVED,
                        rule_key=key,
                        old_rule=old_exp,
                    )
                )

        # Added: in new but not in old
        for key, new_exp in new_rules.items():
            if key not in old_rules:
                changes.append(
                    UMFValidationChange(
                        change_type=UMFChangeType.ADDED,
                        rule_key=key,
                        new_rule=new_exp,
                    )
                )

        # Modified: in both but different
        for key, new_exp in new_rules.items():
            if key in old_rules:
                old_exp = old_rules[key]
                if old_exp != new_exp:
                    changed_fields = self._compare_validation_rules(old_exp, new_exp)
                    changes.append(
                        UMFValidationChange(
                            change_type=UMFChangeType.MODIFIED,
                            rule_key=key,
                            old_rule=old_exp,
                            new_rule=new_exp,
                            changed_fields=changed_fields,
                        )
                    )

        # Sort: removed first, then added, then modified
        return sorted(
            changes,
            key=lambda c: (
                0
                if c.change_type == UMFChangeType.REMOVED
                else 1
                if c.change_type == UMFChangeType.ADDED
                else 2
            ),
        )

    def _get_expectations(self, umf: UMF) -> list[dict]:
        """Extract expectations list from UMF validation_rules.

        Handles both the expectations-based format (list of dicts with type/kwargs/meta)
        and gracefully returns empty list if validation_rules uses a different structure.

        Args:
            umf: UMF model

        Returns:
            List of expectation dicts

        """
        return expectation_dicts_from_umf(umf)

    def _get_rule_key(self, exp: dict) -> tuple[str, str, int]:
        """Extract (column, rule_type, rule_index) key from expectation.

        Args:
            exp: Expectation dict with type, kwargs, and meta

        Returns:
            Tuple of (column, rule_type, rule_index)

        """
        column = exp.get("kwargs", {}).get("column", "-")
        rule_type = exp.get("type", "").removeprefix("expect_")
        rule_index = exp.get("meta", {}).get("rule_index", 0)
        return (column, rule_type, rule_index)

    def get_metadata_changes(self) -> list[UMFMetadataChange]:
        """Detect changes to table-level metadata.

        Returns:
            List of UMFMetadataChange objects

        """
        changes: list[UMFMetadataChange] = []

        if not self.old_umf:
            return changes

        # Check specific metadata fields
        metadata_fields = ["description", "table_type"]
        # Include canonical_name and aliases only if present on the model
        for optional_field in ["canonical_name", "aliases"]:
            if hasattr(self.old_umf, optional_field) or hasattr(
                self.new_umf, optional_field
            ):
                metadata_fields.append(optional_field)

        for field in metadata_fields:
            old_val = getattr(self.old_umf, field, None)
            new_val = getattr(self.new_umf, field, None)

            if old_val != new_val:
                changes.append(
                    UMFMetadataChange(
                        field_name=field,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

        return changes

    def _extract_column_name(self, expectation: dict) -> str:
        """Extract column name from a validation expectation.

        Args:
            expectation: Validation expectation dict

        Returns:
            Column name, or "-" if it's a cross-column rule

        """
        # Try to extract from description first (most reliable)
        desc = expectation.get("meta", {}).get("description", "")
        if "Column " in desc and " must " in desc:
            # Format: "Column <name> must ..."
            parts = desc.split("Column ")
            if len(parts) > 1:
                return parts[1].split(" ")[0]

        # Check kwargs for column name
        kwargs = expectation.get("kwargs", {})
        if "column" in kwargs:
            return kwargs["column"]

        # Cross-column rule
        return "-"

    def _compare_columns(
        self, old_col: UMFColumn, new_col: UMFColumn
    ) -> dict[str, tuple[Any, Any]] | None:
        """Compare two columns and return changed fields.

        Args:
            old_col: Old column version
            new_col: New column version

        Returns:
            Dict mapping field name to (old_value, new_value) for changed fields, or None if no changes

        """
        fields_to_check = [
            "description",
            "data_type",
            "length",
            "precision",
            "scale",
            "nullable",
            "sample_values",
        ]
        # Include optional fields only if they exist on the model
        for optional_field in ["key_type", "domain_type"]:
            if hasattr(old_col, optional_field) or hasattr(new_col, optional_field):
                fields_to_check.append(optional_field)

        changed = {}
        for field in fields_to_check:
            old_val = getattr(old_col, field, None)
            new_val = getattr(new_col, field, None)

            if old_val != new_val:
                changed[field] = (old_val, new_val)

        return changed if changed else None

    def _compare_dicts(
        self, old_dict: dict, new_dict: dict, exclude_keys: set[str] | None = None
    ) -> dict[str, tuple[Any, Any]] | None:
        """Compare two dicts and return changed keys.

        Args:
            old_dict: Old dict
            new_dict: New dict
            exclude_keys: Keys to skip in comparison

        Returns:
            Dict mapping key to (old_value, new_value) for changed keys, or None if no changes

        """
        exclude_keys = exclude_keys or set()

        changed = {}

        # Keys that were removed or modified
        for key in old_dict:
            if key in exclude_keys:
                continue
            old_val = old_dict.get(key)
            new_val = new_dict.get(key)
            if old_val != new_val:
                changed[key] = (old_val, new_val)

        # Keys that were added
        for key in new_dict:
            if key in exclude_keys or key in old_dict:
                continue
            changed[key] = (None, new_dict.get(key))

        return changed if changed else None

    def _compare_validation_rules(
        self, old_rule: dict, new_rule: dict
    ) -> dict[str, tuple[Any, Any]] | None:
        """Compare validation rules, excluding internal-only meta fields.

        Args:
            old_rule: Old validation rule dict
            new_rule: New validation rule dict

        Returns:
            Dict mapping key to (old_value, new_value) for changed keys, or None if no changes

        """
        changed = {}

        # Compare top-level keys except 'meta'
        for key in old_rule:
            if key == "meta":
                continue
            old_val = old_rule.get(key)
            new_val = new_rule.get(key)
            if old_val != new_val:
                changed[key] = (old_val, new_val)

        # Check for added top-level keys
        for key in new_rule:
            if key == "meta" or key in old_rule:
                continue
            changed[key] = (None, new_rule.get(key))

        # Compare meta fields, but exclude internal-only fields
        # Keep: severity, description (user-editable)
        # Exclude: rule_index (used for indexing), generated_from (internal)
        old_meta = old_rule.get("meta", {})
        new_meta = new_rule.get("meta", {})

        exclude_meta_fields = {"rule_index", "generated_from"}

        for meta_key in old_meta:
            if meta_key in exclude_meta_fields:
                continue
            old_val = old_meta.get(meta_key)
            new_val = new_meta.get(meta_key)
            if old_val != new_val:
                changed[f"meta.{meta_key}"] = (old_val, new_val)

        for meta_key in new_meta:
            if meta_key in exclude_meta_fields or meta_key in old_meta:
                continue
            changed[f"meta.{meta_key}"] = (None, new_meta.get(meta_key))

        return changed if changed else None
