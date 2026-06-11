---
ddx:
  id: US-031
---

# US-031: Validate Custom GX Expectations

**Feature**: FEAT-018 - Custom GX Extensions
**Feature Requirements**: GXEXT-01, GXEXT-02
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

## Acceptance Criteria

- [ ] **US-031-AC1** - Given custom expectation inputs, when validators run on clean and dirty rows, then success and unexpected counts reflect the rule.
- [ ] **US-031-AC2** - Given custom expectations in a suite, when schema/processor code handles them, then supported custom expectation types are recognized and retained.

## Edge Cases

- **Null pairs**: date-order expectations handle null pair policy explicitly.
- **Invalid casts**: castability checks fail only rows that cannot be cast.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Clean/dirty rules | US-031-AC1 | custom expectation fixtures | evaluate validators | correct verdicts/counts |
| Suite handling | US-031-AC2 | suite with custom types | process/validate suite | custom expectations retained |

## Dependencies

- **Feature Spec**: FEAT-018
- **PRD Requirements**: FR-7.5

## Out of Scope

- Adding arbitrary user-defined Python expectations.
