---
ddx:
  id: US-015
---

# US-015: Diff Two UMF Versions

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.1, FR-11.2
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer reviewing schema changes,
**I want** compare two UMF versions and see a structured list of differences,
**So that** I can understand what changed before approving a pull request.

## Context

This story covers the diff two umf versions slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a diff two umf versions fixture or source object.
2. System runs the the UMF diff and change-application flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-015-AC1** — Given a `member_v1` UMF and a `member_v2` UMF with a changed `plan_code`, when the UMF diff and change-application flow runs, then **US-015-AC1** - `UMFDiff` detects added, removed, and modified columns
- [ ] **US-015-AC2** — Given a `member_v1` UMF and a `member_v2` UMF with a changed `plan_code`, when the UMF diff and change-application flow runs, then **US-015-AC2** - Validation rule and metadata changes are identified separately
- [ ] **US-015-AC3** — Given a `member_v1` UMF and a `member_v2` UMF with a changed `plan_code`, when the UMF diff and change-application flow runs, then **US-015-AC3** - `UMFChangeApplier` can apply individual changes to produce intermediate UMF versions
- [ ] **US-015-AC4** — Given a `member_v1` UMF and a `member_v2` UMF with a changed `plan_code`, when the UMF diff and change-application flow runs, then **US-015-AC4** - Changes are typed (`UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`)

## Edge Cases

- **added, removed, and modified columns all need explicit handling**: added, removed, and modified columns all need explicit handling
- **typed changes should not collapse into one bucket**: typed changes should not collapse into one bucket
- **intermediate versions must stay constructible**: intermediate versions must stay constructible

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Diff plan_code changes | US-015-AC1 | member_v1 plan_code="PPO" and member_v2 plan_code="HMO" | the UMF diff and change-application flow runs | **US-015-AC1** - `UMFDiff` detects added, removed, and modified columns |
| Separate validation-rule changes | US-015-AC2 | validation rule severity change on status | the UMF diff and change-application flow runs | **US-015-AC2** - Validation rule and metadata changes are identified separately |
| Apply column-level changes | US-015-AC3 | UMFColumnChange(plan_code: PPO -> HMO) | the UMF diff and change-application flow runs | **US-015-AC3** - `UMFChangeApplier` can apply individual changes to produce intermediate UMF versions |
| Type the diff payloads | US-015-AC4 | UMFColumnChange, UMFMetadataChange, UMFValidationChange | the UMF diff and change-application flow runs | **US-015-AC4** - Changes are typed (`UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`) |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-010 — UMF Change Management
- **Feature Requirements**: DIFF-01, DIFF-02, DIFF-03
- **PRD Requirements**: FR-11.1, FR-11.2
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- storing version state outside the UMF diff model
- semantic merge policy beyond explicit changes

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
