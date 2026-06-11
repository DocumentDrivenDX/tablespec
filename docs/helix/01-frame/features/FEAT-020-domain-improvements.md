---
ddx:
  id: FEAT-020
---

# Feature Specification: FEAT-020 — Domain Type System Improvements

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-020
**Owner**: Data Platform
**Covered PRD Subsystem(s)**: Domain Type Inference
**Covered PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Improvements to the domain type inference system for better matching accuracy, richer results, and consistency across the codebase.

## Ideal Future State

A data engineer can rely on Domain Type System Improvements as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F020-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F020-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Abbreviation Expansion (`src/tablespec/inference/domain_types.py`)

`COMMON_ABBREVIATIONS` dict mapping healthcare data abbreviations to full words:

```python
COMMON_ABBREVIATIONS = {
    "mbr": "member", "dt": "date", "cd": "code", "desc": "description",
    "nm": "name", "addr": "address", "nbr": "number", "amt": "amount",
    "qty": "quantity", "pct": "percent", "ind": "indicator", "typ": "type",
    "sts": "status", "eff": "effective", "exp": "expiration", ...
}
```

`expand_column_name()` generates candidate names for fuzzy matching, improving inference accuracy on abbreviated column names like `mbr_eff_dt` -> `member_effective_date`.

##### Confidence-Ranked Results with Explanation (`src/tablespec/inference/domain_types.py`)

`infer_domain_type()` currently returns `tuple[str | None, float]` (type + confidence). Replace this with a structured `InferenceResult` that adds explanation and runner_up fields:

```python
@dataclass
class InferenceResult:
    domain_type: str        # Best match
    confidence: float       # 0.0 - 1.0
    explanation: str        # Which signals matched (name pattern, value regex, etc.)
    runner_up: str | None   # Second-best match for ambiguous cases
```

##### Excel Converter Registry Sync (`src/tablespec/excel_converter.py`)

Excel dropdown for domain types currently reads from a hardcoded 14-type list. Update to read from `DomainTypeRegistry` instead, making all 41+ domain types available in the Excel authoring workflow.

##### Regex Validation on Registry Load (`src/tablespec/inference/domain_types.py`)

Invalid regex patterns in `domain_types.yaml` currently fail silently during inference. Change to raise `ValueError` on registry load, catching configuration errors early.

## User Stories

- [US-033 — Improve Domain Type Inference](../user-stories/US-033-improve-domain-type-inference.md)

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
- **PRD requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4

### Source Evidence

- `src/tablespec/inference/domain_types.py`
- `src/tablespec/excel_converter.py`

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
