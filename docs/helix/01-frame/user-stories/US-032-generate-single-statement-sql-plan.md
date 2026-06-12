---
ddx:
  id: US-032
---

# US-032: Generate a Single-Statement SQL Plan

**Feature**: FEAT-019 - SQL Generator CTE Mode
**PRD Requirements**: FR-19.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer embedding generated SQL in a single-statement context
**I want** the SQL plan generator to emit CTE SQL as an alternative to temporary views
**So that** generated transforms can run in dbt-like or warehouse contexts that reject multi-statement scripts

## Context

The direct SQL emitter remains a committed-artifact path. CTE mode is a structural emission option that preserves the same semantics while changing the statement shape.

## Walkthrough

1. User requests a SQL plan in CTE mode.
2. System emits one `WITH ... SELECT` statement with dependencies ordered correctly.
3. User executes or embeds the statement without creating temporary views.

## Context

This story covers the generate a single-statement sql plan slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate a single-statement sql plan fixture or source object.
2. System runs the the CTE planning flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-032-AC1** — Given a multi-step plan with `filtered_claims`, `deduped_claims`, and `final_claims`, when the CTE planning flow runs, then **US-032-AC1** - Given a multi-step SQL plan, when CTE mode is selected, then output is a single statement with ordered CTE dependencies.
- [ ] **US-032-AC2** — Given a multi-step plan with `filtered_claims`, `deduped_claims`, and `final_claims`, when the CTE planning flow runs, then **US-032-AC2** - Given equivalent fixtures, when view and CTE modes execute, then they produce semantically equivalent results.

## Edge Cases

- **the emitted SQL must stay a single statement**: the emitted SQL must stay a single statement
- **equivalent fixtures should agree across modes**: equivalent fixtures should agree across modes
- **ordering of CTE dependencies matters**: ordering of CTE dependencies matters

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Emit a single-statement CTE plan | US-032-AC1 | filtered_claims, deduped_claims, final_claims | the CTE planning flow runs | **US-032-AC1** - Given a multi-step SQL plan, when CTE mode is selected, then output is a single statement with ordered CTE dependencies. |
| Match view and CTE results | US-032-AC2 | member and claim fixtures with claim_id=17 | the CTE planning flow runs | **US-032-AC2** - Given equivalent fixtures, when view and CTE modes execute, then they produce semantically equivalent results. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-019 - SQL Generator CTE Mode
- **Feature Requirements**: SQL-CTE-01, SQL-CTE-02
- **PRD Requirements**: FR-19.4
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- runtime execution engines
- SQL plan semantics outside the CTE mode choice

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
