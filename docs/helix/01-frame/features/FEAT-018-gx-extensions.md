---
ddx:
  id: FEAT-018
---

# Feature Specification: FEAT-018 — Custom GX Extensions

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-018
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Table Validation
**Covered PRD Requirements**: FR-7.5
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Custom Great Expectations expectation classes that bridge tablespec domain concepts into GX execution.

## Ideal Future State

A data engineer can rely on Custom GX Extensions as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

## Problem Statement

- **Current situation**: The feature is implemented or governed by existing source evidence, but the pre-template specification did not expose the current HELIX feature-specification sections.
- **Pain points**: Reviewers had to infer requirements, edge cases, success criteria, and dependency boundaries from component lists and source paths, which made alignment checks brittle.
- **Desired outcome**: The feature contract is explicit, traceable to cited evidence, and updated without introducing behavior beyond the implementation and story artifacts already referenced here.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Implemented Components | What must tablespec preserve for implemented components? | Maintain the source-backed implemented components behavior documented in this feature. |

## Requirements

### Functional Requirements by Area

#### Implemented Components

F018-IMPLEM-01. The feature SHALL provide the implemented components behavior described in the existing scope evidence and cited source modules below.
F018-IMPLEM-02. Changes to the implemented components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Implemented Components

##### ExpectColumnValuesToMatchDomainType (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Loads the domain type registry (`src/tablespec/domain_types.yaml`), validates that column values match the validation spec for the assigned domain type (regex patterns, value sets, format constraints).

Works on Spark and Sail execution backends. Bridges domain types from FEAT-013 into the GX validation pipeline.

```python
# Usage in expectation suite
{
    "type": "expect_column_values_to_match_domain_type",
    "kwargs": {"column": "gender_cd", "domain_type": "gender_code"}
}
```

##### ExpectColumnValuesToCastToType (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Validates actual Spark casting (not just pattern matching). Catches edge cases like "2023-02-30" (format-valid but date-invalid). Supports flexible date/timestamp parsing with fallback formats. Skips validation if column is already the target type (pre-typed Gold tables).

##### ExpectColumnDateToBeInCurrentYear (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Validates date values fall within current calendar year using dynamic Spark SQL DATE_TRUNC for year bounds. Supports mostly threshold.

##### ExpectColumnPairDateOrder (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Cross-column date ordering for start_date < end_date patterns common in temporal data (eligibility spans, enrollment periods, contract dates, event ranges). Supports `or_equal` flag and null pair handling.

##### Standalone Validators -- DONE

- `validate_domain_type()` — PySpark DataFrame validator for domain types (usable without GX framework)
- `validate_column_pair_date_order()` — PySpark DataFrame validator for date ordering

## User Stories

- [US-031 — Validate Custom GX Expectations](../user-stories/US-031-validate-custom-gx-expectations.md)

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
- **PRD requirements**: FR-7.5

### Existing Dependency Evidence

- FEAT-013 (domain type registry)
- FEAT-024 (Spark/Sail session for execution)

### Source Evidence

- `src/tablespec/validation/custom_gx_expectations.py`

### Preserved Acceptance Evidence

| # | Criterion | Test Evidence |
|---|-----------|---------------|
| AC-1 | Domain type value set validation (state codes, gender, LOB) | `test_domain_type_expectation.py::test_*_valid/invalid` |
| AC-2 | Domain type regex validation (email, NPI, ZIP, phone) | `test_domain_type_expectation.py::test_*_regex*` |
| AC-3 | Domain type length validation | `test_domain_type_expectation.py::test_*_length*` |
| AC-4 | Mostly threshold support | `test_domain_type_expectation.py::test_*_mostly*` |
| AC-5 | Null handling (all nulls pass, mixed nulls excluded) | `test_domain_type_expectation.py::test_*_null*` |
| AC-6 | Unknown domain type fails with clear message | `test_domain_type_expectation.py::test_*_unknown*` |
| AC-7 | Date pair ordering with valid/invalid data | `test_date_order_expectation.py` |
| AC-8 | Date pair or_equal flag (>= vs >) | `test_date_order_expectation.py` |
| AC-9 | Result structure includes element_count, unexpected_count, partial_unexpected_list | `test_domain_type_expectation.py::test_*_result*` |

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
