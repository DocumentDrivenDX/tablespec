"""Pure functions for UMF mutations. Each takes a UMF and returns a new UMF."""

from __future__ import annotations

from typing import Any

from tablespec.expectation_migration import migrate_to_expectation_suite
from tablespec.models.umf import UMF, UMFColumn


def add_column(umf: UMF, name: str, data_type: str, **kwargs: Any) -> UMF:
    """Add a column. Raises ValueError if name already exists."""
    existing_names = {col.name for col in umf.columns}
    if name in existing_names:
        msg = f"Column '{name}' already exists"
        raise ValueError(msg)

    col = UMFColumn(name=name, data_type=data_type, **kwargs)
    new_columns = [c.model_copy() for c in umf.columns] + [col]
    return umf.model_copy(update={"columns": new_columns})


def remove_column(umf: UMF, name: str) -> UMF:
    """Remove a column. Raises ValueError if name not found."""
    existing_names = {col.name for col in umf.columns}
    if name not in existing_names:
        msg = f"Column '{name}' not found"
        raise ValueError(msg)

    new_columns = [c.model_copy() for c in umf.columns if c.name != name]
    return umf.model_copy(update={"columns": new_columns})


def modify_column(umf: UMF, name: str, **changes: Any) -> UMF:
    """Modify column attributes. Raises ValueError if name not found."""
    existing_names = {col.name for col in umf.columns}
    if name not in existing_names:
        msg = f"Column '{name}' not found"
        raise ValueError(msg)

    new_columns = []
    for col in umf.columns:
        if col.name == name:
            new_columns.append(col.model_copy(update=changes))
        else:
            new_columns.append(col.model_copy())
    return umf.model_copy(update={"columns": new_columns})


def remove_expectation(
    umf: UMF, expectation_type: str, column: str | None = None
) -> tuple[UMF, int]:
    """Remove expectations matching type and optional column. Returns (new_umf, count_removed)."""

    def _matches(exp: dict[str, Any] | Any) -> bool:
        if isinstance(exp, dict):
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            exp_col = exp.get("kwargs", {}).get("column")
        else:
            exp_type = getattr(exp, "type", "")
            exp_col = getattr(exp, "kwargs", {}).get("column")
        if exp_type != expectation_type:
            return False
        if column is not None and exp_col != column:
            return False
        return True

    removed = 0
    updates: dict[str, Any] = {}
    suite = umf.expectations or migrate_to_expectation_suite(
        umf.model_dump(exclude_none=True)
    )

    original_expectations = list(suite.expectations)
    filtered_expectations = [exp for exp in original_expectations if not _matches(exp)]
    removed = len(original_expectations) - len(filtered_expectations)

    if removed:
        updates["expectations"] = suite.model_copy(
            update={"expectations": filtered_expectations}
        )
        updates["validation_rules"] = None
        updates["quality_checks"] = None

    return umf.model_copy(update=updates) if updates else umf, removed


def rename_column(
    umf: UMF, old_name: str, new_name: str, *, keep_alias: bool = False
) -> UMF:
    """Rename a column. If keep_alias, adds old_name to aliases."""
    existing_names = {col.name for col in umf.columns}
    if old_name not in existing_names:
        msg = f"Column '{old_name}' not found"
        raise ValueError(msg)
    if new_name in existing_names:
        msg = f"Column '{new_name}' already exists"
        raise ValueError(msg)

    new_columns = []
    for col in umf.columns:
        if col.name == old_name:
            updates: dict[str, Any] = {"name": new_name}
            if keep_alias:
                current_aliases = list(col.aliases or [])
                current_aliases.append(old_name)
                updates["aliases"] = current_aliases
            new_columns.append(col.model_copy(update=updates))
        else:
            new_columns.append(col.model_copy())
    return umf.model_copy(update={"columns": new_columns})
