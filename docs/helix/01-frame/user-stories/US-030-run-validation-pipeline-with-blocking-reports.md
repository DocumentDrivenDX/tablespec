---
ddx:
  id: US-030
---

# US-030: Run Validation Pipeline with Blocking Reports

**Feature**: FEAT-017 - Validation Pipeline Improvements
**Feature Requirements**: VALPIPE-01, VALPIPE-02, VALPIPE-03
**PRD Requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3
**Priority**: P0
**Status**: Approved

## Story

**As a** data quality engineer operating a validation run
**I want** suite execution, blocking policy, baseline comparison, and reports coordinated through one pipeline
**So that** validation failures are actionable and severity-aware rather than scattered across separate tools

## Context

This story links the cross-subsystem validation-pipeline feature to the GX, validation, and baseline PRD families. It preserves the feature's cross-subsystem rationale without splitting a single operational workflow.

## Walkthrough

1. User runs validation or quality execution against a table.
2. System evaluates suite expectations, applies blocking policy, compares relevant baselines, and emits structured reports.
3. User sees whether the run blocks and why.

## Acceptance Criteria

- [ ] **US-030-AC1** - Given passing and failing expectations with severity metadata, when quality execution runs, then blocking decisions match configured severity policy.
- [ ] **US-030-AC2** - Given validation output, when reports are generated, then structured failure details are available for programmatic and human review.

## Edge Cases

- **Mixed severities**: non-blocking failures are reported without blocking the run.
- **Missing baseline**: comparison reports an initialization path rather than false drift.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Blocking policy | US-030-AC1 | mixed-severity results | run quality executor | expected blocked/not-blocked result |
| Report shape | US-030-AC2 | validation results | generate report | structured failure details |

## Dependencies

- **Feature Spec**: FEAT-017
- **PRD Requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3

## Out of Scope

- Connect-specific native execution, which is owned by US-022 / FEAT-025.
