---
ddx:
  id: US-036
---

# US-036: Author UMF with CLI and LLM Assistance

**Feature**: FEAT-023 - Authoring Tools
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

## Context

This story covers the author umf with cli and llm assistance slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a author umf with cli and llm assistance fixture or source object.
2. System runs the the authoring helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-036-AC1** — Given a column/domain mutation for `member.yaml`, when the authoring helpers run, then **US-036-AC1** - Given a column/domain mutation, when authoring helpers run, then the UMF changes are valid, previewable, and preserve unrelated content.
- [ ] **US-036-AC2** — Given a column/domain mutation for `member.yaml`, when the authoring helpers run, then **US-036-AC2** - Given an LLM response with validation rules, when apply-response runs, then valid expectations are added, duplicates are ignored, and invalid entries are reported.

## Edge Cases

- **invalid LLM output must not corrupt the UMF**: invalid LLM output must not corrupt the UMF
- **duplicate expectations should be ignored**: duplicate expectations should be ignored
- **preview/apply should preserve unrelated content**: preview/apply should preserve unrelated content

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Preview a member.yaml mutation | US-036-AC1 | member.yaml column and domain mutation | the authoring helpers run | **US-036-AC1** - Given a column/domain mutation, when authoring helpers run, then the UMF changes are valid, previewable, and preserve unrelated content. |
| Apply an LLM-proposed validation rule | US-036-AC2 | LLM response with expect_column_values_to_be_between(age) | the authoring helpers run | **US-036-AC2** - Given an LLM response with validation rules, when apply-response runs, then valid expectations are added, duplicates are ignored, and invalid entries are reported. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-023 - Authoring Tools
- **Feature Requirements**: AUTH-01, AUTH-02, AUTH-03
- **PRD Requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- bypassing validation with LLM output
- directly editing the canonical files without preview

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
