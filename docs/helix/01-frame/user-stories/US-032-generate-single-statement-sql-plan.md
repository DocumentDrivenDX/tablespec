---
ddx:
  id: US-032
---

# US-032: Generate a Single-Statement SQL Plan

**Feature**: FEAT-019 - SQL Generator CTE Mode
**Feature Requirements**: SQLCTE-01, SQLCTE-02
**PRD Requirements**: FR-19.4
**Priority**: P1
**Status**: Implemented

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

## Acceptance Criteria

- [ ] **US-032-AC1** - Given a multi-step SQL plan, when CTE mode is selected, then output is a single statement with ordered CTE dependencies.
- [ ] **US-032-AC2** - Given equivalent fixtures, when view and CTE modes execute, then they produce semantically equivalent results.

## Edge Cases

- **Diamond dependencies**: common upstream work is not duplicated incorrectly.
- **Unknown relation**: generation fails closed.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| CTE shape | US-032-AC1 | multi-step plan | generate CTE SQL | one ordered statement |
| Equivalence | US-032-AC2 | same fixture | run both modes | same rows |

## Dependencies

- **Feature Spec**: FEAT-019
- **PRD Requirements**: FR-19.4

## Out of Scope

- Replacing dbt or LDP emitters with CTE-only output.
