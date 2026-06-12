"""Schema compatibility checking between UMF versions.

Compares two :class:`~tablespec.models.umf.UMF` objects and produces a
:class:`CompatibilityReport` listing every breaking, warning, or
informational change.
"""

from dataclasses import dataclass, field
from typing import Any

from tablespec.models.umf import UMF, Nullable, UMFColumn
from tablespec.type_lattice import (
    is_length_compatible,
    is_precision_compatible,
    is_safe_widening,
)


@dataclass
class CompatibilityIssue:
    """A single compatibility finding between two schema versions."""

    component: str  # e.g. "column.ssn", "table.primary_key"
    change: str  # "removed", "type_narrowed", "nullable_tightened", etc.
    severity: str  # "breaking", "warning", "info"
    description: str
    old_value: Any = None
    new_value: Any = None


@dataclass
class CompatibilityReport:
    """Aggregate result of a compatibility check."""

    is_backward_compatible: bool
    is_forward_compatible: bool
    issues: list[CompatibilityIssue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nullable_contexts(n: Nullable | None) -> dict[str, bool]:
    """Return a {context_key: bool} dict for a Nullable, treating None as empty."""
    if n is None:
        return {}
    # Nullable uses model_config extra="allow", so extra fields are in __pydantic_extra__
    result: dict[str, bool] = {}
    for key in n.model_fields_set | set(n.__pydantic_extra__ or {}):
        val = getattr(n, key, None)
        if val is None:
            val = (n.__pydantic_extra__ or {}).get(key)
        if isinstance(val, bool):
            result[key] = val
    return result


def _is_column_fully_nullable(col: UMFColumn) -> bool:
    """Return True when the column has no nullable constraint or all contexts are True."""
    if col.nullable is None:
        return True
    contexts = _nullable_contexts(col.nullable)
    if not contexts:
        return True
    return all(contexts.values())


def _check_column_added(col: UMFColumn, issues: list[CompatibilityIssue]) -> None:
    """Evaluate a newly-added column."""
    if _is_column_fully_nullable(col):
        issues.append(
            CompatibilityIssue(
                component=f"column.{col.name}",
                change="added",
                severity="info",
                description=f"Nullable column '{col.name}' added",
                new_value=col.name,
            )
        )
    else:
        issues.append(
            CompatibilityIssue(
                component=f"column.{col.name}",
                change="added_required",
                severity="breaking",
                description=(
                    f"Required (non-nullable) column '{col.name}' added — "
                    "existing data will not satisfy the new constraint"
                ),
                new_value=col.name,
            )
        )


def _check_column_removed(col: UMFColumn, issues: list[CompatibilityIssue]) -> None:
    issues.append(
        CompatibilityIssue(
            component=f"column.{col.name}",
            change="removed",
            severity="breaking",
            description=f"Column '{col.name}' removed",
            old_value=col.name,
        )
    )


def _check_type_change(
    name: str,
    old_col: UMFColumn,
    new_col: UMFColumn,
    issues: list[CompatibilityIssue],
) -> None:
    """Check data_type, length, precision, and scale changes."""
    old_type = old_col.data_type.upper()
    new_type = new_col.data_type.upper()

    if old_type != new_type:
        safe, reason = is_safe_widening(old_type, new_type)
        if safe:
            issues.append(
                CompatibilityIssue(
                    component=f"column.{name}",
                    change="type_widened",
                    severity="info",
                    description=f"Type widened from {old_type} to {new_type}: {reason}",
                    old_value=old_type,
                    new_value=new_type,
                )
            )
        else:
            issues.append(
                CompatibilityIssue(
                    component=f"column.{name}",
                    change="type_narrowed",
                    severity="breaking",
                    description=f"Type changed from {old_type} to {new_type} (potential data loss)",
                    old_value=old_type,
                    new_value=new_type,
                )
            )
        return  # type changed, skip length/precision check on old type

    if old_type == "EMBEDDING":
        if old_col.dimension != new_col.dimension:
            issues.append(
                CompatibilityIssue(
                    component=f"column.{name}",
                    change="dimension_narrowed",
                    severity="breaking",
                    description=(
                        f"Embedding dimension changed from {old_col.dimension} to {new_col.dimension} "
                        "(breaking change)"
                    ),
                    old_value=old_col.dimension,
                    new_value=new_col.dimension,
                )
            )
        return

    # Same type — check length (VARCHAR/CHAR)
    if old_type in ("VARCHAR", "CHAR"):
        if old_col.length != new_col.length:
            if is_length_compatible(old_col.length, new_col.length):
                issues.append(
                    CompatibilityIssue(
                        component=f"column.{name}",
                        change="length_widened",
                        severity="info",
                        description=f"Length widened from {old_col.length} to {new_col.length}",
                        old_value=old_col.length,
                        new_value=new_col.length,
                    )
                )
            else:
                issues.append(
                    CompatibilityIssue(
                        component=f"column.{name}",
                        change="length_narrowed",
                        severity="breaking",
                        description=f"Length narrowed from {old_col.length} to {new_col.length} (potential data loss)",
                        old_value=old_col.length,
                        new_value=new_col.length,
                    )
                )

    # Same type — check precision/scale (DECIMAL)
    if old_type == "DECIMAL":
        if (old_col.precision, old_col.scale) != (new_col.precision, new_col.scale):
            if is_precision_compatible(
                old_col.precision, old_col.scale, new_col.precision, new_col.scale
            ):
                issues.append(
                    CompatibilityIssue(
                        component=f"column.{name}",
                        change="precision_widened",
                        severity="info",
                        description=(
                            f"Precision/scale widened from ({old_col.precision},{old_col.scale}) "
                            f"to ({new_col.precision},{new_col.scale})"
                        ),
                        old_value=(old_col.precision, old_col.scale),
                        new_value=(new_col.precision, new_col.scale),
                    )
                )
            else:
                issues.append(
                    CompatibilityIssue(
                        component=f"column.{name}",
                        change="precision_narrowed",
                        severity="breaking",
                        description=(
                            f"Precision/scale narrowed from ({old_col.precision},{old_col.scale}) "
                            f"to ({new_col.precision},{new_col.scale}) (potential data loss)"
                        ),
                        old_value=(old_col.precision, old_col.scale),
                        new_value=(new_col.precision, new_col.scale),
                    )
                )


def _check_nullable_change(
    name: str,
    old_col: UMFColumn,
    new_col: UMFColumn,
    issues: list[CompatibilityIssue],
) -> None:
    """Context-aware nullable comparison."""
    old_ctx = _nullable_contexts(old_col.nullable)
    new_ctx = _nullable_contexts(new_col.nullable)

    if old_ctx == new_ctx:
        return

    all_keys = set(old_ctx) | set(new_ctx)
    for key in sorted(all_keys):
        old_val = old_ctx.get(key)
        new_val = new_ctx.get(key)

        if old_val == new_val:
            continue

        if old_val is None and new_val is not None:
            # New context added — not breaking for existing consumers
            severity = "info"
            desc = f"Nullable context '{key}' added for column '{name}' (value={new_val})"
            change = "nullable_context_added"
        elif old_val is not None and new_val is None:
            # Context removed
            severity = "warning"
            desc = f"Nullable context '{key}' removed for column '{name}'"
            change = "nullable_context_removed"
        elif old_val is True and new_val is False:
            # nullable → required  (tightened) — breaking for that context
            severity = "breaking"
            desc = (
                f"Nullable tightened for column '{name}' in context '{key}': "
                "nullable -> required"
            )
            change = "nullable_tightened"
        else:
            # required → nullable  (relaxed) — safe
            severity = "info"
            desc = (
                f"Nullable relaxed for column '{name}' in context '{key}': "
                "required -> nullable"
            )
            change = "nullable_relaxed"

        issues.append(
            CompatibilityIssue(
                component=f"column.{name}",
                change=change,
                severity=severity,
                description=desc,
                old_value=old_val,
                new_value=new_val,
            )
        )


def _check_description_change(
    name: str,
    old_col: UMFColumn,
    new_col: UMFColumn,
    issues: list[CompatibilityIssue],
) -> None:
    if old_col.description != new_col.description:
        issues.append(
            CompatibilityIssue(
                component=f"column.{name}",
                change="description_changed",
                severity="info",
                description=f"Description changed for column '{name}'",
                old_value=old_col.description,
                new_value=new_col.description,
            )
        )


def _check_primary_key(old: UMF, new: UMF, issues: list[CompatibilityIssue]) -> None:
    old_pk = old.primary_key or []
    new_pk = new.primary_key or []
    if old_pk != new_pk:
        if not old_pk and new_pk:
            severity = "warning"
            change = "primary_key_added"
            desc = f"Primary key added: {new_pk}"
        elif old_pk and not new_pk:
            severity = "breaking"
            change = "primary_key_removed"
            desc = f"Primary key removed: {old_pk}"
        else:
            severity = "breaking"
            change = "primary_key_changed"
            desc = f"Primary key changed from {old_pk} to {new_pk}"
        issues.append(
            CompatibilityIssue(
                component="table.primary_key",
                change=change,
                severity=severity,
                description=desc,
                old_value=old_pk,
                new_value=new_pk,
            )
        )


def _resolve_renames(
    old_cols: dict[str, UMFColumn],
    new_cols: dict[str, UMFColumn],
) -> dict[str, str]:
    """Return {old_name: new_name} for columns renamed via aliases.

    A column is considered "renamed" when:
    - old_name is NOT in new_cols
    - a new column lists old_name in its ``aliases``
    """
    renames: dict[str, str] = {}
    # Build a reverse index: alias -> new column name
    alias_to_new: dict[str, str] = {}
    for new_name, new_col in new_cols.items():
        for alias in new_col.aliases or []:
            alias_to_new[alias] = new_name

    for old_name in old_cols:
        if old_name not in new_cols and old_name in alias_to_new:
            renames[old_name] = alias_to_new[old_name]

    return renames


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_compatibility(old: UMF, new: UMF) -> CompatibilityReport:
    """Compare two UMF versions and report compatibility.

    Returns a :class:`CompatibilityReport` with all detected issues.
    """
    issues: list[CompatibilityIssue] = []

    old_cols = {c.name: c for c in old.columns}
    new_cols = {c.name: c for c in new.columns}

    # Detect renames via aliases
    renames = _resolve_renames(old_cols, new_cols)

    # --- Column removals (excluding renames) ---
    for old_name, old_col in old_cols.items():
        if old_name not in new_cols and old_name not in renames:
            _check_column_removed(old_col, issues)

    # --- Renamed columns (info, not breaking) ---
    for old_name, new_name in renames.items():
        issues.append(
            CompatibilityIssue(
                component=f"column.{old_name}",
                change="renamed",
                severity="info",
                description=(
                    f"Column '{old_name}' renamed to '{new_name}' "
                    f"(old name listed in aliases)"
                ),
                old_value=old_name,
                new_value=new_name,
            )
        )

    # --- Column additions ---
    renamed_new_names = set(renames.values())
    for new_name, new_col in new_cols.items():
        if new_name not in old_cols and new_name not in renamed_new_names:
            _check_column_added(new_col, issues)

    # --- Modified columns (present in both, or matched via rename) ---
    pairs: list[tuple[str, UMFColumn, UMFColumn]] = []
    for name in old_cols:
        if name in new_cols:
            pairs.append((name, old_cols[name], new_cols[name]))
    for old_name, new_name in renames.items():
        pairs.append((new_name, old_cols[old_name], new_cols[new_name]))

    for name, old_col, new_col in pairs:
        _check_type_change(name, old_col, new_col, issues)
        _check_nullable_change(name, old_col, new_col, issues)
        _check_description_change(name, old_col, new_col, issues)

    # --- Table-level checks ---
    _check_primary_key(old, new, issues)

    # --- Compute summary flags ---
    # Forward compatible = new schema can consume data written with old schema
    # This is broken if columns were added that are required
    has_forward_breaking = any(
        i.severity == "breaking" and i.change in ("added_required",)
        for i in issues
    )
    # Backward compatible = old consumers can still read data written with new schema
    # Broken by removals, type narrowing, nullable tightening, pk changes
    has_backward_breaking = any(
        i.severity == "breaking"
        and i.change
        not in ("added_required",)
        for i in issues
    )

    return CompatibilityReport(
        is_backward_compatible=not has_backward_breaking,
        is_forward_compatible=not has_forward_breaking,
        issues=issues,
    )
