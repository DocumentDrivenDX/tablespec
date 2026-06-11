---
ddx:
  id: FEAT-019
---

# Feature Specification: FEAT-019 — SQL Generator CTE Mode

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-019
**Owner**: Platform / Compilation
**Covered PRD Subsystem(s)**: Multi-Target Emission
**Covered PRD Requirements**: FR-19.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Add a `mode` parameter to `SQLPlanGenerator` that produces a single `WITH...SELECT` statement using Common Table Expressions instead of sequential `CREATE OR REPLACE TEMPORARY VIEW` statements.

The current view-based approach in `schemas/sql_generator.py`:

- Requires sequential script execution (statements depend on prior views).
- Cannot be embedded in dbt models or other single-statement contexts.
- Forces duplicate joins for diamond dependencies in the dependency graph.
- Prevents query engine optimization across view boundaries.

CTE mode produces a single statement that query engines can optimize holistically.

## Ideal Future State

A data engineer can rely on SQL Generator CTE Mode as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F019-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F019-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### SQLPlanGenerator CTE Mode (`src/tablespec/schemas/sql_generator.py`)

The existing `generate_sql_plan()` function signature is:

```python
generate_sql_plan(table_umf, related_umfs, *, template_vars=None, table_resolver=None)
```

This feature adds a new `mode` parameter (proposed, not yet implemented):

```python
# Current behavior (default) -- produces CREATE OR REPLACE TEMPORARY VIEW statements
sql = generate_sql_plan(table_umf, related_umfs, mode="views")
# CREATE OR REPLACE TEMPORARY VIEW ...
# CREATE OR REPLACE TEMPORARY VIEW ...
# SELECT ...

# Proposed new mode
sql = generate_sql_plan(table_umf, related_umfs, mode="cte")
# WITH
#   step_1 AS (...),
#   step_2 AS (...)
# SELECT ...
```

Both modes produce semantically equivalent results for any valid UMF input.

##### Diamond Deduplication (`src/tablespec/schemas/sql_generator.py`)

In CTE mode, diamond dependencies (where multiple downstream steps reference the same upstream step) are handled by emitting each CTE once in the `WITH` clause, then referencing it by name from multiple downstream CTEs. This avoids the duplicate join problem present in view mode without requiring materialization.

##### Materialization Guidance

Not all intermediates are suitable as pure CTEs. Steps that perform 1:N deduplication via `ROW_NUMBER()`, pivots, or aggregations should be materialized (temporary tables or views) because re-executing them from a CTE reference would be expensive and potentially non-deterministic. Simple 1:1 joins and filters can remain as pure CTEs since they are cheap to re-evaluate if the query engine chooses not to factor them out.

##### Semantic Equivalence Testing

Semantic equivalence testing: both modes produce identical query results when executed against DuckDB with identical source data. DuckDB is used as a dev/test dependency for this verification.

Golden file tests for representative CTE outputs (~15 cases covering linear chains, diamond dependencies, fan-out/fan-in patterns).

## User Stories

- [US-032 — Generate a Single-Statement SQL Plan](../user-stories/US-032-generate-single-statement-sql-plan.md)

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
- **PRD requirements**: FR-19.4

### Existing Dependency Evidence

- ADR-006 (DuckDB for semantic equivalence testing)

### Source Evidence

- `src/tablespec/schemas/sql_generator.py` (SQLPlanGenerator)

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
