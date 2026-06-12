---
ddx:
  id: US-017
---

# US-017: Infer Domain Types for Columns

**Feature**: FEAT-013 — Domain Type Inference
**PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer building table specs,
**I want** automatically detect domain types (state code, SSN, phone) from column names and descriptions,
**So that** I can enrich UMF specs with semantic types without manual tagging.

## Context

This story covers the infer domain types for columns slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a infer domain types for columns fixture or source object.
2. System runs the the domain-type inference flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-017-AC1** — Given columns named `npi`, `icd10_code`, and `state_code`, when the domain-type inference flow runs, then **US-017-AC1** - `DomainTypeInference` infers domain types from column name patterns
- [ ] **US-017-AC2** — Given columns named `npi`, `icd10_code`, and `state_code`, when the domain-type inference flow runs, then **US-017-AC2** - `DomainTypeRegistry` loads domain definitions from YAML
- [ ] **US-017-AC3** — Given columns named `npi`, `icd10_code`, and `state_code`, when the domain-type inference flow runs, then **US-017-AC3** - Inferred types integrate with sample data generation and validation
- [ ] **US-017-AC4** — Given columns named `npi`, `icd10_code`, and `state_code`, when the domain-type inference flow runs, then **US-017-AC4** - Unknown columns return no domain type rather than a false match

## Edge Cases

- **unknown columns should not false-match**: unknown columns should not false-match
- **domain packs may add new definitions**: domain packs may add new definitions
- **sample-data generation and validation should reuse the registry**: sample-data generation and validation should reuse the registry

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Infer healthcare domain names | US-017-AC1 | npi, icd10_code, state_code | the domain-type inference flow runs | **US-017-AC1** - `DomainTypeInference` infers domain types from column name patterns |
| Load custom domain registry YAML | US-017-AC2 | domains.yaml with plan_status | the domain-type inference flow runs | **US-017-AC2** - `DomainTypeRegistry` loads domain definitions from YAML |
| Reuse inferred types downstream | US-017-AC3 | npi-aware sample data and validation | the domain-type inference flow runs | **US-017-AC3** - Inferred types integrate with sample data generation and validation |
| Return no false match | US-017-AC4 | unknown_field | the domain-type inference flow runs | **US-017-AC4** - Unknown columns return no domain type rather than a false match |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-013 — Domain Type Inference
- **Feature Requirements**: DOMAIN-01, DOMAIN-02, DOMAIN-03
- **PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- new domain packs not wired through the registry
- sample-data generation internals

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
