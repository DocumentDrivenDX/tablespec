---
ddx:
  id: FEAT-002
---

# Feature Specification: FEAT-002 — Schema Generation

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-002
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Schema Generation
**Covered PRD Requirements**: FR-2.1, FR-2.2, FR-2.3
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Generate schema definitions in multiple output formats from UMF metadata.

## Ideal Future State

A data engineer can rely on Schema Generation as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

## Problem Statement

- **Current situation**: The feature is implemented or governed by existing source evidence, but the pre-template specification did not expose the current HELIX feature-specification sections.
- **Pain points**: Reviewers had to infer requirements, edge cases, success criteria, and dependency boundaries from component lists and source paths, which made alignment checks brittle.
- **Desired outcome**: The feature contract is explicit, traceable to cited evidence, and updated without introducing behavior beyond the implementation and story artifacts already referenced here.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Supported Formats | What must tablespec preserve for supported formats? | Maintain the source-backed supported formats behavior documented in this feature. |

## Requirements

### Functional Requirements by Area

#### Supported Formats

F002-SUPPOR-01. The feature SHALL provide the supported formats behavior described in the existing scope evidence and cited source modules below.
F002-SUPPOR-02. Changes to the supported formats behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Supported Formats

1. **SQL DDL** (`generate_sql_ddl`) - CREATE TABLE with NOT NULL, column/table comments, suggested indexes
2. **PySpark** (`generate_pyspark_schema`) - StructType Python code with correct type imports
3. **JSON Schema** (`generate_json_schema`) - Draft-07 schema with type mapping, maxLength, examples

## User Stories

- [US-003 — Generate SQL DDL from a UMF Schema](../user-stories/US-003-generate-sql-ddl-from-umf.md)

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
- **PRD requirements**: FR-2.1, FR-2.2, FR-2.3

### Source Evidence

- `src/tablespec/schemas/generators.py`
- Type conversions via `src/tablespec/type_mappings.py`

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
