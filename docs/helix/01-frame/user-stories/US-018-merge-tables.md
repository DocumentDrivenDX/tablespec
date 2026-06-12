---
ddx:
  id: US-018
---

# US-018: Merge Table Files with Survivorship

**Feature**: FEAT-007 — Table Validation
**PRD Requirements**: FR-15.1, FR-15.2, FR-15.3
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer merging vendor files,
**I want** merge multiple table files using UMF survivorship rules,
**So that** deduplication and conflict resolution follow the spec rather than ad-hoc logic.

## Context

This story covers the merge table files with survivorship slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a merge table files with survivorship fixture or source object.
2. System runs the the table merge flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-018-AC1** — Given `member_primary.csv` and `member_override.csv` Spark DataFrames, when the table merge flow runs, then `merge.py` merges multiple Spark DataFrames using UMF metadata (requires `tablespec[spark]`)
- [ ] **US-018-AC2** — Given `member_primary.csv` with `status="active"` and `member_override.csv` with `status="inactive"`, when the table merge flow runs, then survivorship rules from UMF drive conflict resolution
- [ ] **US-018-AC3** — Given `dedupe_latest_by="updated_at"` in the merge configuration, when the table merge flow runs, then the deduplication strategy is configurable

## Edge Cases

- **survivorship rules must control conflicts**: survivorship rules must control conflicts
- **deduplication strategy should be configurable**: deduplication strategy should be configurable
- **merge needs Spark-backed inputs**: merge needs Spark-backed inputs

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Merge primary and override rows | US-018-AC1 | `member_primary.csv` and `member_override.csv` Spark DataFrames | the table merge flow runs | `merge.py` merges multiple Spark DataFrames using UMF metadata (requires `tablespec[spark]`) |
| Apply survivorship to status | US-018-AC2 | `member_primary.csv` with `status="active"` and `member_override.csv` with `status="inactive"` | the table merge flow runs | survivorship rules from UMF drive conflict resolution |
| Use configurable deduplication | US-018-AC3 | `dedupe_latest_by="updated_at"` in the merge configuration | the table merge flow runs | the deduplication strategy is configurable |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-007 — Table Validation
- **Feature Requirements**: MERGE-01, MERGE-02, MERGE-03
- **PRD Requirements**: FR-15.1, FR-15.2, FR-15.3
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- schema validation or profiling
- new conflict-resolution policy beyond survivorship

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
