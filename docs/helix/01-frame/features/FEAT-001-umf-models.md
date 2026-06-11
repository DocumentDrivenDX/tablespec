---
ddx:
  id: FEAT-001
---

# Feature Specification: FEAT-001 — UMF Models and I/O

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-001
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: UMF Model and I/O
**Covered PRD Requirements**: FR-1.1, FR-1.2, FR-1.3, FR-1.4, FR-1.5, FR-1.6, FR-1.7, FR-1.8, FR-1.9, FR-1.10
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Type-safe Pydantic models for the Universal Metadata Format (UMF), plus YAML serialization and deserialization.

## Ideal Future State

A data engineer can rely on UMF Models and I/O as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

## Problem Statement

- **Current situation**: The feature is implemented or governed by existing source evidence, but the pre-template specification did not expose the current HELIX feature-specification sections.
- **Pain points**: Reviewers had to infer requirements, edge cases, success criteria, and dependency boundaries from component lists and source paths, which made alignment checks brittle.
- **Desired outcome**: The feature contract is explicit, traceable to cited evidence, and updated without introducing behavior beyond the implementation and story artifacts already referenced here.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Models | What must tablespec preserve for models? | Maintain the source-backed models behavior documented in this feature. |
| Key Behaviors | What must tablespec preserve for key behaviors? | Maintain the source-backed key behaviors behavior documented in this feature. |
| I/O | What must tablespec preserve for i/o? | Maintain the source-backed i/o behavior documented in this feature. |
| Changelog Models | What must tablespec preserve for changelog models? | Maintain the source-backed changelog models behavior documented in this feature. |

## Requirements

### Functional Requirements by Area

#### Models

F001-MODELS-01. The feature SHALL provide the models behavior described in the existing scope evidence and cited source modules below.
F001-MODELS-02. Changes to the models behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

#### Key Behaviors

F001-KEYBEH-01. The feature SHALL provide the key behaviors behavior described in the existing scope evidence and cited source modules below.
F001-KEYBEH-02. Changes to the key behaviors behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

#### I/O

F001-IO-01. The feature SHALL provide the i/o behavior described in the existing scope evidence and cited source modules below.
F001-IO-02. Changes to the i/o behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

#### Changelog Models

F001-CHANGE-01. The feature SHALL provide the changelog models behavior described in the existing scope evidence and cited source modules below.
F001-CHANGE-02. Changes to the changelog models behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Models

- **UMF** - Root model: version, table_name, columns, validation_rules, relationships, metadata
- **UMFColumn** - Column definition: name, data_type, length, precision, scale, nullable, sample_values
- **Nullable** - Per-LOB nullability: MD (Medicaid), MP (Medicare Part D), ME (Medicare)
- **ValidationRule** - Rule: rule_type, description, severity (error/warning/info), parameters
- **ValidationRules** - Table-level and column-level rule collections
- **ForeignKey** - FK with confidence scoring and legacy format support
- **ReferencedBy** - Reverse FK reference
- **Index** - Database index definition
- **Relationships** - FK, referenced_by, and index collections
- **UMFMetadata** - Timestamps, creator, pipeline phase (1-7)

#### Key Behaviors

- Column names validated: `^[A-Za-z][A-Za-z0-9_]*$`, max 128 chars
- Unique column names enforced
- VARCHAR requires length; DECIMAL recommends precision
- Extra fields forbidden (`extra="forbid"`)
- Version format: `\d+\.\d+`

#### I/O

- `load_umf_from_yaml(path)` - Load and validate UMF from YAML
- `save_umf_to_yaml(umf, path)` - Save UMF to YAML, excluding None values
- `UMFLoader` - Auto-detect and load from split or JSON format (see FEAT-010)

#### Changelog Models

- **ChangeEntry** - Structured changelog entry with timestamp, author, change type
- **ChangeDetail** - Per-field change detail
- **ChangeType** - Enum of change categories

## User Stories

- [US-001 — Load and Validate a UMF Schema from YAML](../user-stories/US-001-load-and-validate-umf-schema.md)
- [US-002 — Construct a UMF Schema Programmatically](../user-stories/US-002-construct-umf-programmatically.md)

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
- **PRD requirements**: FR-1.1, FR-1.2, FR-1.3, FR-1.4, FR-1.5, FR-1.6, FR-1.7, FR-1.8, FR-1.9, FR-1.10

### Source Evidence

- `src/tablespec/models/umf.py`
- `src/tablespec/models/changelog.py`

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
