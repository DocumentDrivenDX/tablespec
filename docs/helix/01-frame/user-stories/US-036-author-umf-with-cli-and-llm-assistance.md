---
ddx:
  id: US-036
---

# US-036: Author UMF with CLI and LLM Assistance

**Feature**: FEAT-023 - Authoring Tools
**Feature Requirements**: AUTH-01, AUTH-02, AUTH-03
**PRD Requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer iterating on a UMF spec
**I want** CLI mutations, validation preview, domain assignment, and LLM response application to be scriptable and reviewable
**So that** authoring changes can be made safely without hand-editing every YAML field

## Context

Authoring tools combine CLI workflow, prompt-generated validation rules, and domain metadata into one authoring surface. This is intentionally cross-subsystem because the user workflow spans those capabilities.

## Walkthrough

1. User modifies columns, domains, or validation rules through CLI/pure authoring helpers.
2. System validates and previews the resulting UMF change.
3. User applies or rejects the change based on structured output.

## Acceptance Criteria

- [ ] **US-036-AC1** - Given a column/domain mutation, when authoring helpers run, then the UMF changes are valid, previewable, and preserve unrelated content.
- [ ] **US-036-AC2** - Given an LLM response with validation rules, when apply-response runs, then valid expectations are added, duplicates are ignored, and invalid entries are reported.

## Edge Cases

- **Invalid LLM output**: invalid entries are reported without corrupting the UMF.
- **Repeated operations**: idempotent changes do not duplicate validations.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Mutation preview | US-036-AC1 | UMF + mutation | preview/apply | valid isolated change |
| Apply response | US-036-AC2 | LLM JSON response | apply-response | valid added, duplicates skipped, invalid reported |

## Dependencies

- **Feature Spec**: FEAT-023
- **PRD Requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4

## Out of Scope

- Letting LLM output bypass UMF/GX validation.
