---
ddx:
  id: FEAT-010
---

# Feature Specification: FEAT-010 — UMF Change Management

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-010
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Split-Format UMF; Schema Change Management
**Covered PRD Requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4, FR-11.1, FR-11.2, FR-11.3, FR-11.4, FR-11.5
**Cross-Subsystem Rationale**: Cross-subsystem workflow: git-friendly split storage, diffing, applying, dependency checks, and changelog generation are one schema-change workflow.

## Overview

Split-format UMF storage, schema diffing, atomic change application, and git-based changelog generation.

## Ideal Future State

A data engineer can rely on UMF Change Management as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F010-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F010-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### UMF Loader (`umf_loader.py`)
- `UMFLoader` - Load UMF from split (directory) or JSON format with auto-detection
- `UMFFormat` enum: SPLIT (default, git-friendly) and JSON (artifact standard)
- Legacy single-file YAML UMF documents are migration-only and are not auto-detected
- Bidirectional conversion between formats

##### UMF Diff (`umf_diff.py`)
- `UMFDiff` - Compare two UMF versions
- Detects: column added/removed/modified, validation rule changes, metadata changes, relationship changes
- Change types: `UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`

##### Change Applier (`umf_change_applier.py`)
- `apply_column_change()`, `apply_metadata_change()`, `apply_validation_change()`
- Returns modified deep copies for immutable change tracking

##### Changelog Generator (`changelog_generator.py`)
- `ChangelogGenerator` - Git history-based changelog for table directories
- `YAMLDiffParser` - Detailed YAML diff parsing from git commits
- Structured output via `ChangeEntry` and `ChangeDetail` models

## User Stories

- [US-012 — Load UMF from Split-Format Directory](../user-stories/US-012-split-format-loading.md)
- [US-014 — Generate Changelog from Git History](../user-stories/US-014-generate-changelog.md)
- [US-015 — Diff Two UMF Versions](../user-stories/US-015-diff-umf-versions.md)
- [US-020 — Resolve Pipeline Dependencies](../user-stories/US-020-resolve-dependencies.md)

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
- **PRD requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4, FR-11.1, FR-11.2, FR-11.3, FR-11.4, FR-11.5

### Existing Dependency Evidence

- ruamel.yaml (split-format YAML)
- gitpython (changelog generation)

### Source Evidence

- `src/tablespec/umf_loader.py`
- `src/tablespec/umf_diff.py`
- `src/tablespec/umf_change_applier.py`
- `src/tablespec/changelog_generator.py`
- `src/tablespec/changelog_diff_parser.py`
- `src/tablespec/changelog_formatter.py`
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
