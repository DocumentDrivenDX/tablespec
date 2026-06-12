---
ddx:
  id: US-012
---

# US-012: Load UMF from Split-Format Directory

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer using git for schema version control,
**I want** store UMF specs as a directory of YAML files (one per column) and load them transparently,
**So that** git diffs show per-column changes and merge conflicts are isolated, while legacy single-file YAML stays outside the canonical path.

## Context

This story covers the load umf from split-format directory slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a load umf from split-format directory fixture or source object.
2. System runs the the split-format loader runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-012-AC1** — Given a `tables/member/` directory that contains `table.yaml` and `columns/member_id.yaml`, when the split-format loader runs, then **US-012-AC1** - `UMFLoader` auto-detects split format from a directory containing `table.yaml` + `columns/`
- [ ] **US-012-AC2** — Given a `tables/member/` directory that contains `table.yaml` and `columns/member_id.yaml`, when the split-format loader runs, then **US-012-AC2** - `UMFLoader` auto-detects JSON format from a `.json` file
- [ ] **US-012-AC3** — Given a `tables/member/` directory that contains `table.yaml` and `columns/member_id.yaml`, when the split-format loader runs, then **US-012-AC3** - Loading from either format produces the same `UMF` object
- [ ] **US-012-AC4** — Given a `tables/member/` directory that contains `table.yaml` and `columns/member_id.yaml`, when the split-format loader runs, then **US-012-AC4** - `UMFLoader` converts between formats bidirectionally
- [ ] **US-012-AC5** — Given a `tables/member/` directory that contains `table.yaml` and `columns/member_id.yaml`, when the split-format loader runs, then **US-012-AC5** - Single-file YAML UMF documents require an explicit legacy migration path and are not auto-detected as canonical input

## Edge Cases

- **missing `columns/` dir**: missing `columns/` dir
- **split and JSON loaders must agree on the resulting UMF**: split and JSON loaders must agree on the resulting UMF
- **legacy single-file YAML needs an explicit migration path**: legacy single-file YAML needs an explicit migration path

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Detect split-format directory | US-012-AC1 | tables/member/ with table.yaml + columns/member_id.yaml | the split-format loader runs | **US-012-AC1** - `UMFLoader` auto-detects split format from a directory containing `table.yaml` + `columns/` |
| Detect JSON UMF file | US-012-AC2 | member.json | the split-format loader runs | **US-012-AC2** - `UMFLoader` auto-detects JSON format from a `.json` file |
| Load either format equivalently | US-012-AC3 | tables/member/ and member.json | the split-format loader runs | **US-012-AC3** - Loading from either format produces the same `UMF` object |
| Convert bidirectionally | US-012-AC4 | tables/member/ round-trip through split and JSON | the split-format loader runs | **US-012-AC4** - `UMFLoader` converts between formats bidirectionally |
| Require explicit legacy migration | US-012-AC5 | legacy single-file member.yaml | the split-format loader runs | **US-012-AC5** - Single-file YAML UMF documents require an explicit legacy migration path and are not auto-detected as canonical input |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-010 — UMF Change Management
- **Feature Requirements**: LOAD-01, LOAD-02, LOAD-03
- **PRD Requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- runtime artifact emission
- legacy single-file YAML as canonical input

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
