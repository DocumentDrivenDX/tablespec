---
ddx:
  id: FEAT-016
---

# Feature Specification: FEAT-016 — Testing Infrastructure for Agentic Development

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-016
**Owner**: Engineering Productivity
**Covered PRD Subsystem(s)**: Runtime Platform
**Covered PRD Requirements**: None — meta-feature anchored to the Product Vision and Principles per the traceability convention (principles.md §Tension Resolution, decided 2026-06-10); provides the evidence tier for FR-20.3's serverless/Connect target without owning runtime behavior.
**Cross-Subsystem Rationale**: Verification support feature: test infrastructure proves supported runtime targets without owning runtime behavior.

## Overview

Foundational testing infrastructure enabling fast iteration, property-based testing, and test-first development workflows. All components are additive -- existing tests remain unchanged.

## Ideal Future State

A data engineer can rely on Testing Infrastructure for Agentic Development as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F016-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F016-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### GX Test Harness (`tests/conftest.py`)

Execute GX expectations against Spark or Sail backends. Wraps GX context/datasource/validator setup behind a simple API.

Returns structured `GXTestResult` objects with:
- Pass/fail status per expectation
- Observed values
- Unexpected counts
- Sample unexpected values

```python
harness = GXTestHarness(backend="sail")  # or "spark"
result = harness.run(expectations, data_path="test.csv", stage="raw")
assert result.all_passed
assert result["expect_column_to_exist"]["column_name"].success
```

##### UMF Builder DSL (`tests/builders.py`)

Composable builder for test fixtures replacing ad-hoc `_make_umf()` helpers and raw dict construction across test files.

```python
umf = (UMFBuilder("test_table")
    .column("id", "INTEGER", nullable=False)
    .column("name", "VARCHAR", length=100)
    .column("amount", "DECIMAL", precision=10, scale=2)
    .build())  # Returns UMF object

ddl = generate_sql_ddl(umf.as_dict())  # .as_dict() for dict consumers
```

- `.build()` returns UMF model objects (for UMFDiff, compatibility checker).
- `.as_dict()` returns dicts (for `generate_sql_ddl`, `generate_pyspark_schema`).

##### Golden File Runner (`tests/golden/`)

Auto-discovers test cases from directory structure:

```
tests/golden/{feature}/{case}.input.yaml
tests/golden/{feature}/{case}.expected.sql
tests/golden/{feature}/{case}.expected.json
```

Parametrized via pytest. Failure produces unified diff. Used only for short, human-verifiable outputs (~30 lines max). Complex outputs use property tests instead.

##### Hypothesis Strategies (`tests/strategies.py`)

`tests/strategies.py` with composable strategies for property-based testing:

- `umf_column()` -- generates valid UMFColumn instances
- `umf_dict()` -- generates valid UMF dicts
- `umf_object()` -- generates valid UMF model objects

Every generated value passes Pydantic validation. Extends existing Hypothesis usage in `tests/unit/test_yaml_formatter_fuzzing.py`.

##### Fast Test Marker (`pyproject.toml`)

`@pytest.mark.fast` for tests completing in <100ms with no I/O, no Spark, no network. Registered in `pyproject.toml` markers. Agent runs `pytest -m fast` during iteration for sub-second feedback.

##### Test Discovery Convention (`tests/`)

Source file `src/tablespec/foo.py` maps to test file `tests/unit/test_foo.py`.

For new features: write test file first with `@pytest.mark.xfail` tests as the executable spec. Implementation removes `xfail` by making tests pass.

## User Stories

- [US-029 — Maintain Agentic Test Infrastructure](../user-stories/US-029-maintain-agentic-test-infrastructure.md)

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
- **PRD requirements**: None — meta-feature anchored to the Product Vision and Principles per the traceability convention (principles.md §Tension Resolution, decided 2026-06-10); provides the evidence tier for FR-20.3's serverless/Connect target without owning runtime behavior.

### Existing Dependency Evidence

- `tablespec[lite]` (Sail backend) or `tablespec[spark]` (Spark backend) for GX harness

### Source Evidence

- `tests/conftest.py` (harness fixtures, builder, markers)
- `tests/strategies.py` (Hypothesis strategies)
- `tests/golden/` (golden file test cases)
- `pyproject.toml` (marker registration)

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
