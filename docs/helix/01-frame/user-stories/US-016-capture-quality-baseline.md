---
ddx:
  id: US-016
---

# US-016: Capture and Compare Quality Baselines

**Feature**: FEAT-012 — Quality Baselines
**PRD Requirements**: FR-13.1, FR-13.2, FR-13.3, FR-13.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data quality engineer monitoring pipeline health,
**I want** capture a quality baseline from a DataFrame and compare it to previous runs,
**So that** I can detect data drift in row counts, distributions, and statistics.

## Context

This story covers the capture and compare quality baselines slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a capture and compare quality baselines fixture or source object.
2. System runs the the quality baseline capture and comparison flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-016-AC1** — Given a `member` table baseline with 10 rows, then a second snapshot with 12 rows, when the quality baseline capture and comparison flow runs, then **US-016-AC1** - `BaselineService.capture()` records row counts, column distributions, and numeric stats (requires `tablespec[spark]`)
- [ ] **US-016-AC2** — Given a `member` table baseline with 10 rows, then a second snapshot with 12 rows, when the quality baseline capture and comparison flow runs, then **US-016-AC2** - `BaselineService.compare()` produces drift metrics between two baselines
- [ ] **US-016-AC3** — Given a `member` table baseline with 10 rows, then a second snapshot with 12 rows, when the quality baseline capture and comparison flow runs, then **US-016-AC3** - Distribution drift uses Jensen-Shannon divergence
- [ ] **US-016-AC4** — Given a `member` table baseline with 10 rows, then a second snapshot with 12 rows, when the quality baseline capture and comparison flow runs, then **US-016-AC4** - Baselines are stored and retrievable via `BaselineWriter`

## Edge Cases

- **drift can be missing in one snapshot**: drift can be missing in one snapshot
- **Jensen-Shannon divergence should stay the comparison metric**: Jensen-Shannon divergence should stay the comparison metric
- **baseline storage must round-trip**: baseline storage must round-trip

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Capture a member baseline | US-016-AC1 | member baseline with 10 rows | the quality baseline capture and comparison flow runs | **US-016-AC1** - `BaselineService.capture()` records row counts, column distributions, and numeric stats (requires `tablespec[spark]`) |
| Compare two baseline snapshots | US-016-AC2 | member baseline snapshot 10 rows vs 12 rows | the quality baseline capture and comparison flow runs | **US-016-AC2** - `BaselineService.compare()` produces drift metrics between two baselines |
| Measure distribution drift | US-016-AC3 | claim_amount distribution drift | the quality baseline capture and comparison flow runs | **US-016-AC3** - Distribution drift uses Jensen-Shannon divergence |
| Persist baselines to disk | US-016-AC4 | member.baseline.json | the quality baseline capture and comparison flow runs | **US-016-AC4** - Baselines are stored and retrievable via `BaselineWriter` |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-012 — Quality Baselines
- **Feature Requirements**: BASE-01, BASE-02, BASE-03
- **PRD Requirements**: FR-13.1, FR-13.2, FR-13.3, FR-13.4
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- runtime validation execution
- new drift metrics beyond the approved baseline comparison

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
