---
ddx:
  id: US-005
---

# US-005: Generate a Great Expectations Baseline from UMF

**Feature**: FEAT-004 — Great Expectations Integration
**PRD Requirements**: FR-4.1, FR-4.2, FR-4.3, FR-4.7
**Priority**: P1
**Status**: Approved

## Story

**As a** data quality engineer setting up validation for a new table,
**I want** generate a baseline Great Expectations suite directly from a UMF schema,
**So that** I get deterministic structural and type expectations (column existence, order, types, nullability, lengths) without writing expectations by hand.

## Context

This story covers the generate a great expectations baseline from umf slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate a great expectations baseline from umf fixture or source object.
2. System runs the the baseline suite generator runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-005-AC1** — Given a `member` UMF with `member_id`, `plan_code`, and `status` facts, when the baseline suite generator runs, then `BaselineExpectationGenerator` produces structural expectations: column count and column order
- [ ] **US-005-AC2** — Given a `member` UMF with `member_id`, `plan_code`, and `status` facts, when the baseline suite generator runs, then Per-column expectations include: column existence, type matching, LOB-specific nullability, length constraints, and date format checks
- [ ] **US-005-AC3** — Given a `member` UMF with `member_id`, `plan_code`, and `status` facts, when the baseline suite generator runs, then `UmfToGxMapper` composes a complete suite by merging baseline, profiling, and AI-generated expectations
- [ ] **US-005-AC4** — Given a `member` UMF with `member_id`, `plan_code`, and `status` facts, when the baseline suite generator runs, then `GXExpectationProcessor` merges and deduplicates expectations using type:column signatures
- [ ] **US-005-AC5** — Given a `member` UMF with `member_id`, `plan_code`, and `status` facts, when the baseline suite generator runs, then Output conforms to GX 1.6+ format (legacy fields are rejected)

## Edge Cases

- **baseline-only output must still be valid**: baseline-only output must still be valid
- **profile-derived expectations may be merged later**: profile-derived expectations may be merged later
- **legacy redundant expectations stay out of the suite**: legacy redundant expectations stay out of the suite

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Generate structural baseline expectations | US-005-AC1 | member_id, plan_code, status | the baseline suite generator runs | `BaselineExpectationGenerator` produces structural expectations: column count and column order |
| Generate per-column baseline checks | US-005-AC2 | member_id, plan_code, status | the baseline suite generator runs | Per-column expectations include: column existence, type matching, LOB-specific nullability, length constraints, and date format checks |
| Merge profile-derived expectations | US-005-AC3 | member_id, plan_code, status with profile-derived rules | the baseline suite generator runs | `UmfToGxMapper` composes a complete suite by merging baseline, profiling, and AI-generated expectations |
| Deduplicate by type and column | US-005-AC4 | member_id and status signatures | the baseline suite generator runs | `GXExpectationProcessor` merges and deduplicates expectations using type:column signatures |
| Stay on GX 1.6+ format | US-005-AC5 | GX 1.6+ expectation payload with legacy fields removed | the baseline suite generator runs | Output conforms to GX 1.6+ format (legacy fields are rejected) |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-004 — Great Expectations Integration
- **Feature Requirements**: GX-01, GX-02, GX-03
- **PRD Requirements**: FR-4.1, FR-4.2, FR-4.3, FR-4.7
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- Connect-safe execution routing
- baseline comparison or blocking policy

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
