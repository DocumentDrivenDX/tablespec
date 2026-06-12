---
ddx:
  id: US-031
---

# US-031: Validate Custom GX Expectations

**Feature**: FEAT-018 - Custom GX Extensions
**PRD Requirements**: FR-7.5
**Priority**: P0
**Status**: Approved

## Story

**As a** data quality engineer encoding healthcare validation rules
**I want** custom GX expectations for domain type, castability, current-year dates, and date ordering
**So that** common business rules run as first-class expectations in the suite

## Context

The custom expectations extend table validation for rules that are not covered cleanly by baseline GX expectations. Connect parity for this surface is covered by US-022; this story covers the expectation behaviors themselves.

## Walkthrough

1. User includes a custom expectation in a suite.
2. System evaluates the expectation and returns GX-shaped results.
3. User receives pass/fail verdicts and unexpected counts for clean and dirty data.

## Context

This story covers the validate custom gx expectations slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a validate custom gx expectations fixture or source object.
2. System runs the the custom GX validation flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-031-AC1** — Given a dirty row like `end_date=2024-01-01` and `start_date=2024-01-02`, when the custom GX validation flow runs, then **US-031-AC1** - Given custom expectation inputs, when validators run on clean and dirty rows, then success and unexpected counts reflect the rule.
- [ ] **US-031-AC2** — Given a dirty row like `end_date=2024-01-01` and `start_date=2024-01-02`, when the custom GX validation flow runs, then **US-031-AC2** - Given custom expectations in a suite, when schema/processor code handles them, then supported custom expectation types are recognized and retained.

## Edge Cases

- **dirty rows should fail closed**: dirty rows should fail closed
- **custom expectation types must be retained**: custom expectation types must be retained
- **supported custom expectations should still be recognized**: supported custom expectations should still be recognized

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Validate dirty comparison rows | US-031-AC1 | end_date=2024-01-01 and start_date=2024-01-02 | the custom GX validation flow runs | **US-031-AC1** - Given custom expectation inputs, when validators run on clean and dirty rows, then success and unexpected counts reflect the rule. |
| Retain supported custom expectations | US-031-AC2 | custom pair and collation expectation suite | the custom GX validation flow runs | **US-031-AC2** - Given custom expectations in a suite, when schema/processor code handles them, then supported custom expectation types are recognized and retained. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-018 - Custom GX Extensions
- **Feature Requirements**: GX-EXT-01, GX-EXT-02
- **PRD Requirements**: FR-7.5
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- native profiler statistics behavior
- baseline suite generation

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
