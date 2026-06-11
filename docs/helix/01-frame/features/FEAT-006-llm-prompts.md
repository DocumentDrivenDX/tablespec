---
ddx:
  id: FEAT-006
---

# Feature Specification: FEAT-006 — LLM Prompt Generation

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-006
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: LLM Prompt Generation
**Covered PRD Requirements**: FR-6.1, FR-6.2, FR-6.3, FR-6.4, FR-6.5, FR-6.6, FR-6.7
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Generate structured prompts for LLM-based schema enrichment across documentation, validation, relationships, and survivorship.

## Ideal Future State

A data engineer can rely on LLM Prompt Generation as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F006-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F006-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### Documentation (`prompts/documentation.py`)
- `generate_documentation_prompt` - Business purpose, data flow, relationships, compliance

##### Validation (`prompts/validation.py`, `prompts/column_validation.py`)
- `generate_validation_prompt` - Table-level multi-column expectations
- `generate_column_validation_prompt` - Single-column expectations with prompt hash tracking
- `has_validation_rules` / `should_generate_column_prompt` - Filtering helpers

##### Relationships (`prompts/relationship.py`)
- `generate_relationship_prompt` - FK discovery with cardinality estimation
- Healthcare-domain awareness (member/provider/claim IDs, drug codes)
- Handles both UMF and lookup table directories

##### Survivorship (`prompts/survivorship.py`)
- `generate_survivorship_prompt` - Data survivorship and merge logic mapping

##### Expectation Guide (`prompts/expectation_guide.py`)
- Loads categorized expectation types from JSON schemas
- Provides parameter requirements, validation, quick reference
- Decision tree for pending implementation expectations

##### Filename Pattern (`prompts/filename_pattern.py`)
- `generate_filename_pattern_prompt` - Filename convention and pattern prompts

##### Validation Per Column (`prompts/validation_per_column.py`)
- Column-specific validation prompt generation with granular targeting

## User Stories

- [US-008 — Generate LLM Prompts for Schema Enrichment](../user-stories/US-008-generate-llm-prompts-for-schema-enrichment.md)

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
- **PRD requirements**: FR-6.1, FR-6.2, FR-6.3, FR-6.4, FR-6.5, FR-6.6, FR-6.7

### Source Evidence

- `src/tablespec/prompts/`

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
