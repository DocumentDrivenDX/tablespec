---
ddx:
  id: FEAT-021
---

# Feature Specification: FEAT-021 — UMF Loader & Validator Improvements

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-021
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: UMF Model and I/O; Split-Format UMF
**Covered PRD Requirements**: FR-1.7, FR-10.2, FR-10.3
**Cross-Subsystem Rationale**: Cross-subsystem hardening: loader diagnostics and validator checks protect the same UMF load path.

## Overview

Improve error reporting and validation coverage in the UMF loading and validation pipeline.

## Ideal Future State

A data engineer can rely on UMF Loader & Validator Improvements as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F021-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F021-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Targeted Error Messages (`src/tablespec/umf_loader.py`)

Replace generic "Cannot detect format" errors in `umf_loader.py` with specific diagnostic messages:

- "No `table.yaml` found in {path}" when the table metadata file is missing.
- "No `columns/` subdirectory found in {path}" when column definitions are absent.
- "Found `table.yaml` but it is empty or malformed: {detail}" for parse errors.
- "Column file `{name}.yaml` failed validation: {detail}" for individual column issues.

Each message should include the path searched and what was expected.

##### Expectation Type Validation (`src/tablespec/umf_validator.py`)

Validator checks that expectation types referenced in the suite are recognized GX expectation types. Unknown types produce warnings (not errors) to allow forward compatibility with newer GX versions.

Uses a known-types registry derived from GX's built-in expectation list, updatable without code changes.

##### Split Format Roundtrip Property Test (`tests/unit/test_umf_loader.py`)

Hypothesis property test: any valid UMF produced by `umf_object()` strategy survives `save -> load` through split format with all fields preserved. Catches serialization edge cases (empty lists, None vs missing, special characters in descriptions).

## User Stories

- [US-034 — Load and Validate UMF with Clear Errors](../user-stories/US-034-load-and-validate-umf-with-clear-errors.md)

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
- **PRD requirements**: FR-1.7, FR-10.2, FR-10.3

### Existing Dependency Evidence

- FEAT-016 (Hypothesis strategies, property testing patterns)

### Source Evidence

- `src/tablespec/umf_loader.py`
- `src/tablespec/umf_validator.py`

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
