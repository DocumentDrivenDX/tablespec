---
ddx:
  id: US-020
---

# US-020: Resolve Pipeline Dependencies

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.1
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer working with cross-pipeline table references,
**I want** validate dependency versions and detect cycles,
**So that** pipeline ordering is correct and version constraints are satisfied.

## Context

This story covers the resolve pipeline dependencies slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a resolve pipeline dependencies fixture or source object.
2. System runs the the dependency-resolution flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-020-AC1** — Given a dependency chain `member -> claim -> claim_line` with version constraints, when the dependency-resolution flow runs, then **US-020-AC1** - `dependency_resolver.py` loads pipeline dependencies from metadata
- [ ] **US-020-AC2** — Given a dependency chain `member -> claim -> claim_line` with version constraints, when the dependency-resolution flow runs, then **US-020-AC2** - Version constraint validation against packaging specifiers
- [ ] **US-020-AC3** — Given a dependency chain `member -> claim -> claim_line` with version constraints, when the dependency-resolution flow runs, then **US-020-AC3** - Cycle detection in dependency graph
- [ ] **US-020-AC4** — Given a dependency chain `member -> claim -> claim_line` with version constraints, when the dependency-resolution flow runs, then **US-020-AC4** - Clear error reporting for unresolved or conflicting dependencies

## Edge Cases

- **cycle detection must fail closed**: cycle detection must fail closed
- **version constraints can conflict**: version constraints can conflict
- **unresolved dependencies need clear reporting**: unresolved dependencies need clear reporting

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Load dependency chain metadata | US-020-AC1 | member -> claim -> claim_line | the dependency-resolution flow runs | **US-020-AC1** - `dependency_resolver.py` loads pipeline dependencies from metadata |
| Validate version specifiers | US-020-AC2 | tablespec>=1.2,<2.0 and dbt>=1.0 | the dependency-resolution flow runs | **US-020-AC2** - Version constraint validation against packaging specifiers |
| Detect a dependency cycle | US-020-AC3 | member -> claim -> member | the dependency-resolution flow runs | **US-020-AC3** - Cycle detection in dependency graph |
| Report unresolved dependencies | US-020-AC4 | claim_line -> diagnosis | the dependency-resolution flow runs | **US-020-AC4** - Clear error reporting for unresolved or conflicting dependencies |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-010 — UMF Change Management
- **Feature Requirements**: DEP-01, DEP-02, DEP-03
- **PRD Requirements**: FR-11.1
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- topological sorting for non-table graphs
- new dependency metadata types

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
