---
ddx:
  id: US-014
---

# US-014: Generate Changelog from Git History

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.3, FR-11.4, FR-11.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data governance lead,
**I want** generate a changelog of schema changes from git history,
**So that** I can track who changed what and when for audit and compliance purposes.

## Context

This story covers the generate changelog from git history slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate changelog from git history fixture or source object.
2. System runs the the changelog generator runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-014-AC1** — Given a git history that touches `tables/member/table.yaml` and `tables/claim/table.yaml`, when the changelog generator runs, then **US-014-AC1** - `ChangelogGenerator` produces structured entries from git commits in a table directory
- [ ] **US-014-AC2** — Given a git history that touches `tables/member/table.yaml` and `tables/claim/table.yaml`, when the changelog generator runs, then **US-014-AC2** - Each entry includes timestamp, author, change type, and affected components
- [ ] **US-014-AC3** — Given a git history that touches `tables/member/table.yaml` and `tables/claim/table.yaml`, when the changelog generator runs, then **US-014-AC3** - YAML diff parsing detects column, validation, metadata, and relationship changes
- [ ] **US-014-AC4** — Given a git history that touches `tables/member/table.yaml` and `tables/claim/table.yaml`, when the changelog generator runs, then **US-014-AC4** - `tablespec changelog` CLI command outputs formatted changelog

## Edge Cases

- **git history may include mixed file types**: git history may include mixed file types
- **changes must stay attributable to the touched table directory**: changes must stay attributable to the touched table directory
- **CLI output should stay formatted**: CLI output should stay formatted

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Read table-directory git history | US-014-AC1 | git history touching tables/member/table.yaml and tables/claim/table.yaml | the changelog generator runs | **US-014-AC1** - `ChangelogGenerator` produces structured entries from git commits in a table directory |
| Capture structured changelog entries | US-014-AC2 | commit author erik and timestamp 2026-06-10 | the changelog generator runs | **US-014-AC2** - Each entry includes timestamp, author, change type, and affected components |
| Parse YAML diffs by component | US-014-AC3 | YAML diff for plan_code, nullable, relationships.member_id | the changelog generator runs | **US-014-AC3** - YAML diff parsing detects column, validation, metadata, and relationship changes |
| Format changelog CLI output | US-014-AC4 | tablespec changelog on tables/member | the changelog generator runs | **US-014-AC4** - `tablespec changelog` CLI command outputs formatted changelog |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-010 — UMF Change Management
- **Feature Requirements**: CHANGE-01, CHANGE-02, CHANGE-03
- **PRD Requirements**: FR-11.3, FR-11.4, FR-11.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- Git history rewrite tooling
- commit policy beyond changelog extraction

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
