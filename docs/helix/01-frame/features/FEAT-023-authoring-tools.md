---
ddx:
  id: FEAT-023
---

# Feature Specification: FEAT-023 — Authoring Tools

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-023
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: CLI Interface; LLM Prompt Generation; Domain Type Inference
**Covered PRD Requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4
**Cross-Subsystem Rationale**: Cross-subsystem authoring workflow: CLI mutations, prompt response application, validation preview, and domain assignment form one authoring surface.

## Overview

CLI commands, LLM integration, validation preview, and interactive TUI for authoring and managing UMF schemas.

## Ideal Future State

A data engineer can rely on Authoring Tools as a governed tablespec capability without reverse-engineering source files or older registry-card notes. The feature's source-backed behavior, user stories, dependencies, and update rules are captured in one place so downstream specs, tests, and agents use the same contract.

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

F023-COMPON-01. The feature SHALL provide the components behavior described in the existing scope evidence and cited source modules below.
F023-COMPON-02. Changes to the components behavior SHALL update this feature specification, affected user stories, and registry metadata in the same governed change.

### Non-Functional Requirements

- **Performance**: No new feature-specific runtime target is introduced by this backfill; existing PRD, test, and implementation evidence remain authoritative until a feature-specific target is specified.
- **Security**: The feature SHALL not expand data exposure, logging, or external-service behavior beyond the cited implementation and dependency evidence.
- **Scalability**: No new feature-specific scalability target is introduced by this backfill; scalability claims require explicit benchmark or test evidence.
- **Reliability**: The feature contract SHALL remain source-backed: behavior changes require updated source citations or tests before this document is marked current.

### Existing Scope Evidence

This section preserves the pre-template feature content as source-backed scope evidence. It is descriptive evidence for the requirements above, not a separate implementation plan.

#### Components

##### CLI Mutation Commands (`src/tablespec/cli.py`)

Thin CLI wrappers around pure functions for scriptable UMF editing:

- `tablespec column add/modify/remove/rename` -- Column CRUD operations.
- `tablespec validation add/remove/sync` -- Manage expectations in the suite.
- `tablespec domain infer/set` -- Domain type inference and assignment.
- `tablespec apply-response` -- Apply LLM-generated validation rules.

Each command wraps a pure function. Test the function, not the CLI layer.

##### LLM Response Applier (`src/tablespec/cli.py`)

Takes LLM-generated JSON (from prompt generators in `prompts/`), validates and integrates it into the UMF:

1. Validate GX expectation format.
2. Classify each expectation by stage via `classify_validation_type()`.
3. Deduplicate against existing expectations in the suite.
4. Validate that expectation types exist in GX.
5. If the UMF has `sample_values` on columns, run generated expectations against them via the GX test harness (FEAT-016) to check semantic correctness before accepting.
6. Return structured `ApplyResult`:

```python
@dataclass
class ApplyResult:
    added: list[Expectation]
    deduplicated: list[Expectation]   # Already existed
    invalid: list[dict]               # Failed validation
    warnings: list[str]
```

##### Validation Preview (`src/tablespec/cli.py`)

- `tablespec preview` -- Show expectations classified by stage (raw/ingested), formatted as a table.
- `tablespec preview --against data.csv` -- Dry-run validation via GX DuckDB harness (FEAT-016 + ADR-006).
- `tablespec preview --diff` -- Run compatibility check against previous version (FEAT-022).

##### Interactive TUI (`src/tablespec/tui.py`)

Textual-based terminal UI for browsing and editing UMF schemas:

- Tree view of tables -> columns with expandable details.
- Search across column names, descriptions, domain types.
- Relationship visualization between tables.
- Inline editing of column properties and expectations.

Requires adding `textual` as an optional dependency (`tablespec[tui]`). Testing via Textual's pilot framework.

NOTE: The TUI is for interactive exploration and editing. The CLI commands above are for scripting and CI. These are complementary, not overlapping.

## User Stories

- [US-036 — Author UMF with CLI and LLM Assistance](../user-stories/US-036-author-umf-with-cli-and-llm-assistance.md)

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
- **PRD requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4

### Existing Dependency Evidence

- ADR-005 (unified expectation model for applier and preview)
- ADR-006 (DuckDB backend for preview --against)
- FEAT-016 (GX test harness)
- FEAT-017 (validation pipeline for staged execution)
- FEAT-022 (compatibility checker for preview --diff)

### Source Evidence

- `src/tablespec/cli.py` (existing, to be extended)
- `src/tablespec/prompts/` (existing prompt generators)

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
