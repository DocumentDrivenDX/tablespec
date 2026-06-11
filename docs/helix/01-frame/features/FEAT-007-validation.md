---
ddx:
  id: FEAT-007
---

# Feature Specification: FEAT-007 — Table Validation

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-007
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Table Validation; Table Merge
**Cross-Subsystem Rationale**: Cross-subsystem validation workflow: table merge uses UMF survivorship and validation metadata, and US-018 is the merge slice under this validation-facing feature. Runtime-platform behavior is governed by FR-20.x and ADR-010.
**Covered PRD Requirements**: FR-7.1–FR-7.8, FR-15.1, FR-15.2, FR-15.3 (with the Runtime-Platform contract FR-20.4)

## Overview

Validate Spark DataFrames against UMF specifications and validate UMF files against JSON schema. Suite execution is **Connect-safe**: a compiled Great Expectations suite runs with identical verdicts on classic Spark, Sail (local Spark Connect), and Databricks serverless — see FEAT-025, ADR-010, ADR-011.

## Ideal Future State

A data engineer can rely on Table Validation as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F007-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F007-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Suite Executor (`validation/gx_executor.py`, `validation/native_executor.py`) [requires PySpark]
- `GXSuiteExecutor` — execute a compiled GX suite in a single batch pass.
- **Per-DataFrame engine routing** (FR-7.7): Spark Connect DataFrames (Sail / Databricks serverless) route to the native DataFrame-API executor; classic Spark DataFrames keep the unchanged GX `add_spark` path. Routing keys off the DataFrame's own module (`gx_executor.py:211-239`), never a process-global flag.
- **Why**: GX 1.x `add_spark` / `SparkDFExecutionEngine` asserts a live JVM `SparkContext` that does not exist on Connect, so data-scanning expectations otherwise silently return `success=False`/`result={}` (`native_executor.py:1-31`).
- `native_executor.evaluate_expectation()` — Connect-safe evaluators for every baseline expectation type, engine-correct via `_functions_for` / bound `df[col]`, returning the same `ExpectationResult` shape as the classic path.
- **Staged execution** (FR-7.8): `execute_staged()` classifies raw (string) vs ingested (typed) expectations and routes each to the correct DataFrame.
- **Fail-closed reconciliation**: GX-dropped results are re-evaluated standalone via the native validators so a dropped expectation never silently passes (`gx_executor.py:411-489`).

##### Table Validator (`validation/table_validator.py`) [requires PySpark]
- `TableValidator` - Validate DataFrame against UMF
- Schema validation (missing/extra columns)
- Data type validation
- LOB-specific nullable validation
- Business rule validation (uniqueness, format, value constraints)
- Structured error output via `VALIDATION_ERROR_SCHEMA`

##### UMF Validator (`umf_validator.py`)
- `UMFValidator` - Validate UMF files against JSON schema + business rules
- File, data, and directory validation
- Default specification application (VARCHAR length 255, DECIMAL precision 18/scale 2)
- Duplicate column name fixing

##### Completeness Validator (`completeness_validator.py`)
- Validate completeness of UMF specifications against expected fields

##### Relationship Validator (`relationship_validator.py`)
- Validate foreign key relationships and referential integrity definitions

##### Naming Validator (`naming_validator.py`)
- Validate column and table names against naming conventions

## User Stories

- [US-009 — Validate a DataFrame Against a UMF Schema](../user-stories/US-009-validate-dataframe-against-umf.md)
- [US-018 — Merge Table Files with Survivorship](../user-stories/US-018-merge-tables.md)

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
- **PRD requirements**: FR-7.1–FR-7.8, FR-15.1, FR-15.2, FR-15.3 (with the Runtime-Platform contract FR-20.4)

### Related Artifacts

- FEAT-025 (Connect-safe GX suite validation — the execution layer beneath these validators)
- ADR-010 (Spark Connect / serverless runtime model), ADR-011 (Connect-safe GX native-executor routing), ADR-005 (unified expectation model)

### Source Evidence

- `src/tablespec/validation/gx_executor.py`
- `src/tablespec/validation/native_executor.py`
- `src/tablespec/validation/table_validator.py`
- `src/tablespec/umf_validator.py`
- `src/tablespec/completeness_validator.py`
- `src/tablespec/relationship_validator.py`
- `src/tablespec/naming_validator.py`

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
