---
ddx:
  id: FEAT-022
---

# FEAT-022: Schema Compatibility Checker

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-022
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Schema Change Management
**Covered PRD Requirements**: FR-11.6 (builds on FR-11.1 diffing owned by FEAT-010)
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Analyze two UMF versions and determine backward/forward compatibility, reporting breaking changes with explanations.

## Components

### Type Lattice (`src/tablespec/umf_diff.py`)

Explicit `SAFE_WIDENINGS` dict defining lossless type transitions:

```python
SAFE_WIDENINGS = {
    ("INTEGER", "DECIMAL"),
    ("CHAR", "VARCHAR"),
    ("FLOAT", "DECIMAL"),
    ("DATE", "DATETIME"),
    ("VARCHAR", "TEXT"),
}
```

`is_safe_widening(old_type, new_type) -> bool` function for programmatic checks.

### Nullable-Aware Comparison (`src/tablespec/umf_diff.py`)

Compares `Nullable` objects context-by-context (MD/MP/ME), not flattened to a single boolean. Tightening nullable in one LOB context is a breaking change for that context only, not necessarily for others.

### Rename-with-Alias Detection (`src/tablespec/umf_diff.py`)

If a column name changes between versions but the old name appears in the new column's `aliases` list, report as a rename (severity: info) rather than a remove+add pair (severity: breaking). This avoids false-positive breaking change reports for intentional renames that preserve backward compatibility through aliasing.

### CompatibilityReport (`src/tablespec/umf_diff.py`)

```python
@dataclass
class CompatibilityIssue:
    component: str          # "column.name", "column.type", "nullable.MD"
    change_type: str        # "added", "removed", "widened", "narrowed", "modified"
    severity: str           # "breaking", "compatible", "info"
    description: str
    old_value: Any
    new_value: Any

@dataclass
class CompatibilityReport:
    is_backward_compatible: bool
    is_forward_compatible: bool
    issues: list[CompatibilityIssue]
```

### Compatibility Testing (`tests/unit/test_umf_diff.py`)

Hypothesis properties:
- **Reflexivity**: Any UMF is compatible with itself.
- **Addition safety**: Adding a nullable column is always backward-compatible.
- **Removal detection**: Removing a column is always detected as breaking.

Golden files for ~15 specific cases covering type widening, type narrowing, nullable changes per context, column addition/removal, length/precision changes, and rename-with-alias scenarios.
## User Stories

- [US-035 — Check Schema Compatibility](../user-stories/US-035-check-schema-compatibility.md)

## Source

- `src/tablespec/umf_diff.py` (existing, to be extended)
- `src/tablespec/models/umf.py` (Nullable model)

## Dependencies

- FEAT-016 (UMF Builder, Hypothesis strategies, golden file runner)
