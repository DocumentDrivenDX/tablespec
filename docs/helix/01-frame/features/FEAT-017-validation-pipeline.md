---
ddx:
  id: FEAT-017
---

# Feature Specification: FEAT-017 — Validation Pipeline Improvements

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-017
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Great Expectations Integration; Table Validation; Quality Baselines
**Covered PRD Requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3
**Cross-Subsystem Rationale**: Cross-subsystem validation workflow: suite execution, blocking behavior, reporting, and baselines are one user-visible validation pipeline.

## Overview

Fix structural issues in the validation pipeline: redundant expectations, missing execution paths, non-functional blocking behavior, and lack of reporting.

## Ideal Future State

A data engineer can rely on Validation Pipeline Improvements as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F017-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F017-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Suite-Level GX Execution (`src/tablespec/gx_wrapper.py`)

Replace per-call validator creation in `gx_wrapper.py` with batch execution. One datasource, one validator, one pass for all expectations in a suite. Eliminates repeated GX context setup overhead.

##### Staged Execution (`src/tablespec/gx_wrapper.py`)

`GXSuiteExecutor.execute_staged()` classifies expectations by stage using `classify_validation_type()`, then executes:

- **Raw expectations** against string data (all columns VARCHAR).
- **Ingested expectations** against typed data (columns cast to UMF-declared types).

This connects the existing `classify_validation_type()` function (currently unused) to the execution pipeline.

##### Baseline Generator Fixes (`src/tablespec/gx_baseline.py`)

`BaselineExpectationGenerator` currently generates redundant expectation types:

- `expect_column_to_exist` -- redundant when column-level expectations already imply existence.
- `expect_column_values_to_be_of_type` -- redundant at raw stage where all columns are strings.

Stop generating these. Enforce via Hypothesis property test: no generated suite contains redundant types.

Resolved: `REQUIRED_BASELINE_EXPECTATION_TYPES` (`gx_baseline.py:21`) is now an empty frozenset, so it no longer conflicts with `REDUNDANT_VALIDATION_TYPES` (`models/umf.py:65`) listing `expect_column_to_exist` as redundant.

##### Profiling to Expectations (`src/tablespec/profiling/gx_expectation_builder.py`)

Profile-derived expectation generation is implemented by `ProfileToGxMapper`
(`src/tablespec/profiling/gx_expectation_builder.py`) and verified by
`tests/unit/test_native_profiler_key_candidates.py` plus the Sail profiler lane.
It converts profiling statistics to expectations:

- High cardinality -> `expect_column_values_to_be_unique`
- Min/max values -> `expect_column_values_to_be_between`
- High completeness -> `expect_column_values_to_not_be_null`
- Regex patterns -> `expect_column_values_to_match_regex` (for columns with detected format patterns)

Test via GX harness (FEAT-016) against actual data to verify generated expectations are correct.

Ingested-stage checks to implement, in priority order:

1. `expect_column_values_to_be_between` -- numeric and date range validation on typed data.
2. `expect_column_pair_values_a_to_be_greater_than_b` -- cross-column ordering (e.g., end_date > start_date).
3. `expect_column_pair_values_to_be_equal` -- cross-column equality constraints.

##### Blocking Behavior (`src/tablespec/quality/executor.py`)

Implement `should_block_pipeline()` in `quality/executor.py`. Currently always returns `False`.

Must consider:
- Individual expectation severity
- `blocking` flag on expectation meta
- Suite-level thresholds
- Aggregate failure rates across the suite

##### Validation Reporting (`src/tablespec/quality/executor.py`)

`ValidationReport` class producing:

- Human-readable summaries (pass/fail counts, failure details)
- Structured failure details with expectation type, column, observed vs expected
- Rich-formatted tables for CLI output
- Machine-readable dicts for programmatic consumption

## User Stories

- [US-030 — Run Validation Pipeline with Blocking Reports](../user-stories/US-030-run-validation-pipeline-with-blocking-reports.md)

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
- **PRD requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3

### Existing Dependency Evidence

- ADR-005 (unified expectation model)
- FEAT-016 (test harness for validation testing)

### Source Evidence

- `src/tablespec/gx_wrapper.py`
- `src/tablespec/gx_baseline.py`
- `src/tablespec/quality/executor.py`
- `src/tablespec/models/umf.py`

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
