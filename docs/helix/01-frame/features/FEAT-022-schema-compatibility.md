---
ddx:
  id: FEAT-022
---

# Feature Specification: FEAT-022 — Schema Compatibility Checker

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-022
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Schema Change Management
**Covered PRD Requirements**: FR-11.6 (builds on FR-11.1 diffing owned by FEAT-010)
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Analyze two UMF versions and determine backward/forward compatibility, reporting breaking changes with explanations.

## Ideal Future State

A data engineer can rely on Schema Compatibility Checker as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

## Problem Statement

- **Current situation**: The feature is implemented or governed by existing source evidence, but the pre-template specification did not expose the current HELIX feature-specification sections.
- **Pain points**: Reviewers had to infer requirements, edge cases, success criteria, and dependency boundaries from component lists and source paths, which made alignment checks brittle.
- **Desired outcome**: The feature contract is explicit, traceable to cited evidence, and updated without introducing behavior beyond the implementation and story artifacts already referenced here.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Components | What must tablespec preserve for components? | Maintain the source-backed components behavior documented in this feature. |

## Requirements

### Functional Requirements by Area

#### Components

F022-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F022-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Type Lattice (`src/tablespec/umf_diff.py`)

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

##### Nullable-Aware Comparison (`src/tablespec/umf_diff.py`)

Compares `Nullable` objects context-by-context (MD/MP/ME), not flattened to a single boolean. Tightening nullable in one LOB context is a breaking change for that context only, not necessarily for others.

##### Rename-with-Alias Detection (`src/tablespec/umf_diff.py`)

If a column name changes between versions but the old name appears in the new column's `aliases` list, report as a rename (severity: info) rather than a remove+add pair (severity: breaking). This avoids false-positive breaking change reports for intentional renames that preserve backward compatibility through aliasing.

##### CompatibilityReport (`src/tablespec/umf_diff.py`)

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

##### Compatibility Testing (`tests/unit/test_umf_diff.py`)

Hypothesis properties:
- **Reflexivity**: Any UMF is compatible with itself.
- **Addition safety**: Adding a nullable column is always backward-compatible.
- **Removal detection**: Removing a column is always detected as breaking.

Golden files for ~15 specific cases covering type widening, type narrowing, nullable changes per context, column addition/removal, length/precision changes, and rename-with-alias scenarios.

## User Stories

- [US-035 — Check Schema Compatibility](../user-stories/US-035-check-schema-compatibility.md)

## Edge Cases and Error Handling

- **Implementation drift**: If source behavior changes without updating this feature spec, the governing docs are stale and the change should fail documentation review.
- **Scope expansion**: New behavior not covered by the evidence above requires a feature/story update before implementation is treated as governed.
- **Missing story coverage**: If no user story exists for a requirement-level behavior, create or update the story rather than adding acceptance criteria directly to this feature (ADR-009).

## Success Metrics

- 100% of source paths cited in this feature continue to exist or are replaced with current citations in the same change that moves or removes them.
- 100% of runtime behavior changes in this feature area update the feature spec, registry row, and affected user stories before release.
- Documentation conformance checks pass for the required HELIX feature-specification sections.

## Constraints and Assumptions

- This backfill is source-preserving: it reorganizes and clarifies the governing contract without adding runtime behavior.
- Exact API, CLI, schema, and execution semantics remain owned by the implementation and any dedicated contract artifacts; this feature records the product-level capability boundary.
- Feature delivery stage remains tracked in `docs/helix/01-frame/feature-registry.md`; this document uses the feature-specification status field.

## Dependencies

- **Other features**: See the feature-registry dependency table for cross-feature dependencies; this backfill does not introduce new runtime dependencies.
- **External services**: Existing source-backed dependencies only; no new external service is introduced by this spec backfill.
- **PRD requirements**: FR-11.6 (builds on FR-11.1 diffing owned by FEAT-010)

### Existing Dependency Evidence

- FEAT-016 (UMF Builder, Hypothesis strategies, golden file runner)

### Source Evidence

- `src/tablespec/umf_diff.py` (existing, to be extended)
- `src/tablespec/models/umf.py` (Nullable model)

## Out of Scope

- Adding runtime behavior, public API surface, CLI flags, schemas, or telemetry solely through this documentation backfill.
- Reassigning PRD requirement ownership without updating the PRD and feature registry.
- Duplicating story-level acceptance criteria in this feature spec.

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements are listed when known.
- [x] Functional areas are subordinate parts of this feature's existing capability.
- [x] Overview and requirements are source-backed by preserved evidence.
- [x] Acceptance criteria remain in user stories, not this feature spec.
- [x] Dependencies and source evidence reference existing artifacts.
- [x] Backfill does not introduce new implementation behavior.
