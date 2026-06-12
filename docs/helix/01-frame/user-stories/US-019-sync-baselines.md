---
ddx:
  id: US-019
---

# US-019: Sync Baseline Validations Across Tables

**Feature**: FEAT-012 — Quality Baselines
**PRD Requirements**: FR-13.5
**Priority**: P1
**Status**: Approved

## Story

**As a** platform engineer maintaining table standards,
**I want** sync metadata columns and baseline validations across all table definitions,
**So that** every table has required metadata columns and up-to-date programmatic validations.

## Context

This story covers the sync baseline validations across tables slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a sync baseline validations across tables fixture or source object.
2. System runs the the baseline sync flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-019-AC1** — Given baseline files for `member` and `claim` tables, when the baseline sync flow runs, then **US-019-AC1** - `sync_baseline.py` ensures all tables have required metadata columns
- [ ] **US-019-AC2** — Given baseline files for `member` and `claim` tables, when the baseline sync flow runs, then **US-019-AC2** - Baseline validations stay in sync with the baseline generator
- [ ] **US-019-AC3** — Given baseline files for `member` and `claim` tables, when the baseline sync flow runs, then **US-019-AC3** - User customizations (severity changes) are preserved
- [ ] **US-019-AC4** — Given baseline files for `member` and `claim` tables, when the baseline sync flow runs, then **US-019-AC4** - Conflicts (modified rule content) are detected and reported
- [ ] **US-019-AC5** — Given baseline files for `member` and `claim` tables, when the baseline sync flow runs, then **US-019-AC5** - Operation is idempotent

## Edge Cases

- **customizations must survive sync**: customizations must survive sync
- **conflicts need to be reported, not silently merged**: conflicts need to be reported, not silently merged
- **operation should remain idempotent**: operation should remain idempotent

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Sync member and claim baselines | US-019-AC1 | member and claim baseline files | the baseline sync flow runs | **US-019-AC1** - `sync_baseline.py` ensures all tables have required metadata columns |
| Keep generator output aligned | US-019-AC2 | member.baseline.json from generator output | the baseline sync flow runs | **US-019-AC2** - Baseline validations stay in sync with the baseline generator |
| Preserve custom severity overrides | US-019-AC3 | status severity warning->error | the baseline sync flow runs | **US-019-AC3** - User customizations (severity changes) are preserved |
| Report modified rule content | US-019-AC4 | member_id not_null rule modified | the baseline sync flow runs | **US-019-AC4** - Conflicts (modified rule content) are detected and reported |
| Remain idempotent on rerun | US-019-AC5 | same member/claim files rerun | the baseline sync flow runs | **US-019-AC5** - Operation is idempotent |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-012 — Quality Baselines
- **Feature Requirements**: SYNC-01, SYNC-02, SYNC-03
- **PRD Requirements**: FR-13.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- pipeline execution itself
- new baseline generation behavior

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
