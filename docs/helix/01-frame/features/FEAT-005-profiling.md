---
ddx:
  id: FEAT-005
---

# Feature Specification: FEAT-005 — Profiling Integration (Schema Mapping + Legacy Path)

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-005
**Owner**: Data Platform
**Cross-Subsystem Rationale**: None — single subsystem. Native Connect-safe profiling is governed by FEAT-024.
**Covered PRD Subsystem(s)**: Profiling Integration
**Covered PRD Requirements**: FR-5.3, FR-5.4, FR-5.5

## Overview

Map a Spark DataFrame's *schema* into UMF, and retain the legacy Deequ-style
profile→UMF authoring path as a compatibility-only mechanism. The **default**
profiling mechanism — the native, JVM-free, Connect-safe Spark-SQL profiler that
replaced PyDeequ — is governed by **[FEAT-024](FEAT-024-native-spark-profiler.md)**
(PRD FR-5.1/FR-5.2). This feature now owns only the schema-mapping and
legacy-compatibility surfaces of the Profiling Integration subsystem.

## Ideal Future State

A data engineer can rely on Profiling Integration (Schema Mapping + Legacy Path) as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F005-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F005-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Types (`profiling/types.py`)
- `ColumnProfile` - Per-column profiling data (completeness, distinct count, statistics, quantiles, sampled values, pattern)
- `DataFrameProfile` - Aggregate profiling result (produced by the native profiler; see FEAT-024)

##### Spark Schema Mapper (`profiling/spark_mapper.py`) [requires PySpark]
- `SparkToUmfMapper` - Convert a Spark DataFrame *schema* to UMF
- Maps Spark types to UMF types (`SPARK_TO_UMF_TYPE`); `SQL_TO_UMF_TYPE` maps warehouse type names (used by dbt-facing code)
- Preserves nullable and DecimalType precision/scale
- Produces UMF — the upstream source of truth that feeds GX/dbt/LDP generation (FR-5.4)

##### Deequ Mapper — REMOVED (legacy)
- The PyDeequ-based `DeequToUmfMapper` (`profiling/deequ_mapper.py`) was **removed**
  in commit `ad5a4d9` ("Implement native profiler to replace pydeequ"). It assumed
  a classic `SparkContext` and is unavailable on Databricks serverless / Spark
  Connect (FR-5.5). Code that needs profile-derived expectations now uses the native
  profiler + `ProfileToGxMapper` (FEAT-024). Per FR-5.5, no Deequ path may be
  assumed available on Connect/serverless.

## User Stories

- [US-007 — Convert Profiling Results to UMF](../user-stories/US-007-convert-profiling-results-to-umf.md)

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
- **PRD requirements**: FR-5.3, FR-5.4, FR-5.5

### Related Artifacts

- **[FEAT-024](FEAT-024-native-spark-profiler.md)** — the native (no-JVM,
  Connect-safe) Spark-SQL profiler that is the **default** profiling mechanism
  (PRD FR-5.1/FR-5.2). The Deequ replacement is recorded in
  [ADR-009](../../02-design/adr/ADR-009-native-spark-profiler-over-pydeequ.md).
- Domain type inference (FEAT-013) can enrich profiling results with semantic types
- Quality baselines (FEAT-012) extend profiling with drift detection

### Source Evidence

- `src/tablespec/profiling/types.py`
- `src/tablespec/profiling/spark_mapper.py`
- (default profiler: `src/tablespec/profiling/native_profiler.py` — see FEAT-024)

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
