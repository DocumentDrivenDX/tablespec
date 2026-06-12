---
ddx:
  id: US-033
---

# US-033: Improve Domain Type Inference

**Feature**: FEAT-020 - Domain Type System Improvements
**PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer enriching healthcare table specs
**I want** domain inference to understand abbreviations, confidence, explanations, and registry extensions
**So that** semantic tags are accurate enough to drive validation and sample data without overconfident false matches

## Context

This story extends the original domain inference feature with the improvements now implemented in the domain registry and related tests.

## Walkthrough

1. User supplies columns with healthcare abbreviations or custom domain packs.
2. System expands names, evaluates registry patterns and values, and reports a ranked inference.
3. User accepts or overrides the inferred domain type.

## Context

This story covers the improve domain type inference slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a improve domain type inference fixture or source object.
2. System runs the the domain inference improvements run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-033-AC1** — Given abbreviated healthcare names like `npi`, `icd10_code`, and `drug_cd`, when the domain inference improvements run, then **US-033-AC1** - Given abbreviated healthcare column names, when inference runs, then expanded-name matches improve confidence without false positives on unknown columns.
- [ ] **US-033-AC2** — Given abbreviated healthcare names like `npi`, `icd10_code`, and `drug_cd`, when the domain inference improvements run, then **US-033-AC2** - Given custom domain packs, when the registry loads them, then inference and sample-data generation can use the added domains.

## Edge Cases

- **abbreviated names can create false positives**: abbreviated names can create false positives
- **custom packs should extend inference safely**: custom packs should extend inference safely
- **sample data should reuse the extended registry**: sample data should reuse the extended registry

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Improve abbreviated-name inference | US-033-AC1 | npi, icd10_code, drug_cd | the domain inference improvements run | **US-033-AC1** - Given abbreviated healthcare column names, when inference runs, then expanded-name matches improve confidence without false positives on unknown columns. |
| Load custom domain packs | US-033-AC2 | custom domain pack with plan_status | the domain inference improvements run | **US-033-AC2** - Given custom domain packs, when the registry loads them, then inference and sample-data generation can use the added domains. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-020 - Domain Type System Improvements
- **Feature Requirements**: DOMAIN-04, DOMAIN-05
- **PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- new PRD-owned domain definitions
- sample-data storage formats

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
