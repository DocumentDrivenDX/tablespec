---
ddx:
  id: US-030
---

# US-030: Run Validation Pipeline with Blocking Reports

**Feature**: FEAT-017 - Validation Pipeline Improvements
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

## Context

This story covers the run validation pipeline with blocking reports slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a run validation pipeline with blocking reports fixture or source object.
2. System runs the the blocking report pipeline runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-030-AC1** — Given one passing expectation and one failing expectation with `severity=error` and `blocking=true`, when the blocking report pipeline runs, then **US-030-AC1** - Given passing and failing expectations with severity metadata, when quality execution runs, then blocking decisions match configured severity policy.
- [ ] **US-030-AC2** — Given one passing expectation and one failing expectation with `severity=error` and `blocking=true`, when the blocking report pipeline runs, then **US-030-AC2** - Given validation output, when reports are generated, then structured failure details are available for programmatic and human review.

## Edge Cases

- **mixed severities should not all block**: mixed severities should not all block
- **reports need structured detail**: reports need structured detail
- **blocking policy must honor the `blocking` flag**: blocking policy must honor the `blocking` flag

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Evaluate blocking policy inputs | US-030-AC1 | severity=error and blocking=true expectation pair | the blocking report pipeline runs | **US-030-AC1** - Given passing and failing expectations with severity metadata, when quality execution runs, then blocking decisions match configured severity policy. |
| Render structured failure reports | US-030-AC2 | member_id, status, claim_amount report | the blocking report pipeline runs | **US-030-AC2** - Given validation output, when reports are generated, then structured failure details are available for programmatic and human review. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-017 - Validation Pipeline Improvements
- **Feature Requirements**: VALPIPE-01, VALPIPE-02, VALPIPE-03
- **PRD Requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- Connect-specific executor internals
- baseline capture and comparison

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
