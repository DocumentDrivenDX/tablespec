---
ddx:
  id: US-027
---

# US-027: Normalize Names and Date Formats

**Feature**: FEAT-014 - Naming and Formatting Utilities
**PRD Requirements**: FR-16.1, FR-16.2, FR-16.3, FR-17.1, FR-17.2, FR-17.3
**Priority**: P2
**Status**: Approved

## Story

**As a** data engineer maintaining UMF specs across Excel, YAML, SQL, and Spark
**I want** identifiers, column positions, date formats, and YAML output normalized consistently
**So that** generated artifacts are stable, valid, and reviewable across tools

## Context

Naming and formatting utilities are shared by authoring, generation, validation, and review workflows. This story links the implemented utility surface to the Naming Utilities and Date Format System PRD families.

## Walkthrough

1. User supplies mixed-case or punctuation-heavy identifiers, Excel-style positions, and UMF date notation.
2. System normalizes Spark identifiers, sorts positions predictably, converts date notation, and writes stable YAML.
3. User reviews deterministic generated output with no tool-specific naming drift.

## Context

This story covers the normalize names and date formats slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a normalize names and date formats fixture or source object.
2. System runs the the naming and formatting helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-027-AC1** — Given mixed identifiers such as `MemberClaimID`, `claim-status`, `A12`, and `B3`, when the naming and formatting helpers run, then **US-027-AC1** - Given mixed identifier inputs, when naming utilities normalize them, then outputs are valid Spark identifiers and preserve deterministic ordering.
- [ ] **US-027-AC2** — Given mixed identifiers such as `MemberClaimID`, `claim-status`, `A12`, and `B3`, when the naming and formatting helpers run, then **US-027-AC2** - Given UMF date formats and YAML specs, when formatting utilities process them, then date notation and YAML layout remain stable across repeated runs.

## Edge Cases

- **leading digits or punctuation need safe normalization**: leading digits or punctuation need safe normalization
- **repeated formatting should stay idempotent**: repeated formatting should stay idempotent
- **date notation must not drift across runs**: date notation must not drift across runs

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Normalize mixed identifiers | US-027-AC1 | MemberClaimID, claim-status, A12, B3 | the naming and formatting helpers run | **US-027-AC1** - Given mixed identifier inputs, when naming utilities normalize them, then outputs are valid Spark identifiers and preserve deterministic ordering. |
| Stabilize date formats and YAML | US-027-AC2 | member.yaml date formats yyyy-MM-dd and dd/MM/yyyy | the naming and formatting helpers run | **US-027-AC2** - Given UMF date formats and YAML specs, when formatting utilities process them, then date notation and YAML layout remain stable across repeated runs. |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-014 - Naming and Formatting Utilities
- **Feature Requirements**: NAME-01, DATE-01, YAML-01
- **PRD Requirements**: FR-16.1, FR-16.2, FR-16.3, FR-17.1, FR-17.2, FR-17.3
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- business-specific naming policy beyond Spark-safe conventions
- changing the canonical date-format catalog

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
