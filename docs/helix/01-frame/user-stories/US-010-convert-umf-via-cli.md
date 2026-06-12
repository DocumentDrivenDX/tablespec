---
ddx:
  id: US-010
---

# US-010: Convert UMF Formats via CLI

**Feature**: FEAT-008 — CLI Interface
**PRD Requirements**: FR-8.1, FR-8.2, FR-8.3, FR-8.4, FR-8.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer managing table specs,
**I want** convert UMF between JSON, split, and Excel formats from the command line,
**So that** I can work with specs in the format best suited to each workflow (git for split, artifact for JSON, review for Excel), while treating legacy single-file YAML as a migration-only input.

## Context

This story covers the convert umf formats via cli slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a convert umf formats via cli fixture or source object.
2. System runs the the CLI conversion command runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-010-AC1** — Given a `member.json` file and a `tables/member/` split-format directory, when the CLI conversion command runs, then `tablespec convert input.json output/` converts JSON to split-format directory
- [ ] **US-010-AC2** — Given a `member.json` file and a `tables/member/` split-format directory, when the CLI conversion command runs, then `tablespec convert tables/my_table/ output.json` converts split to JSON
- [ ] **US-010-AC3** — Given a `member.json` file and a `tables/member/` split-format directory, when the CLI conversion command runs, then `tablespec batch-convert tables/ output/ --format json` batch-converts a directory
- [ ] **US-010-AC4** — Given a `member.json` file and a `tables/member/` split-format directory, when the CLI conversion command runs, then Format is auto-detected from input path (file vs directory) for split and JSON inputs; legacy single-file YAML requires explicit migration
- [ ] **US-010-AC5** — Given a `member.json` file and a `tables/member/` split-format directory, when the CLI conversion command runs, then Errors are displayed with Rich formatting and clear messages

## Edge Cases

- **legacy single-file YAML is not canonical input**: legacy single-file YAML is not canonical input
- **format detection must follow file-vs-directory shape**: format detection must follow file-vs-directory shape
- **errors should stay Rich-formatted**: errors should stay Rich-formatted

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Convert JSON to split format | US-010-AC1 | member.json -> tables/member/ | the CLI conversion command runs | `tablespec convert input.json output/` converts JSON to split-format directory |
| Convert split format to JSON | US-010-AC2 | tables/member/ -> member.json | the CLI conversion command runs | `tablespec convert tables/my_table/ output.json` converts split to JSON |
| Batch-convert table directories | US-010-AC3 | tables/member/ and tables/claim/ | the CLI conversion command runs | `tablespec batch-convert tables/ output/ --format json` batch-converts a directory |
| Auto-detect input shape | US-010-AC4 | input path tables/member/ versus tables/member.json | the CLI conversion command runs | Format is auto-detected from input path (file vs directory) for split and JSON inputs; legacy single-file YAML requires explicit migration |
| Reject malformed YAML | US-010-AC5 | malformed member.yaml containing columns: [ | the CLI conversion command runs | Errors are displayed with Rich formatting and clear messages |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-008 — CLI Interface
- **Feature Requirements**: CLI-01, CLI-02, CLI-03
- **PRD Requirements**: FR-8.1, FR-8.2, FR-8.3, FR-8.4, FR-8.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- editing the canonical source format by hand
- new migration semantics for legacy YAML

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
