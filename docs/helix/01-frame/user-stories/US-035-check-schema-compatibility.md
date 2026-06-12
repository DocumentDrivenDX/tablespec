---
ddx:
  id: US-035
---

# US-035: Check Schema Compatibility

**Feature**: FEAT-022 - Schema Compatibility Checker
**PRD Requirements**: FR-11.1, FR-11.2
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer reviewing a schema change
**I want** compatibility analysis to distinguish breaking changes, safe widenings, nullable changes, and aliases
**So that** I can approve safe changes and block risky ones with clear explanations

## Context

Compatibility checking builds on UMF diff and change application. It turns raw diffs into review decisions for schema evolution.

## Walkthrough

1. User compares old and new UMF versions.
2. System classifies changes by compatibility impact and explanation.
3. User sees whether the change is backward compatible.

## Context

This story covers the check schema compatibility slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a check schema compatibility fixture or source object.
2. System runs the the compatibility analysis runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-035-AC1** — Given a type change from `VARCHAR(20)` to `VARCHAR(40)` or `INTEGER` to `BIGINT`, when the compatibility analysis runs, then **US-035-AC1** - Given type changes, when compatibility analysis runs, then safe widenings are distinguished from breaking changes.
- [ ] **US-035-AC2** — Given a type change from `VARCHAR(20)` to `VARCHAR(40)` or `INTEGER` to `BIGINT`, when the compatibility analysis runs, then **US-035-AC2** - Given nullable or rename-with-alias changes, when analysis runs, then context-specific compatibility is reported accurately.

## Edge Cases

- **nullable and alias changes need context**: nullable and alias changes need context
- **safe widenings should not be flagged as breaking**: safe widenings should not be flagged as breaking
- **breaking changes should be called out clearly**: breaking changes should be called out clearly

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Compare widenings versus breaks | US-035-AC1 | VARCHAR(20)->VARCHAR(40) or INTEGER->BIGINT | the compatibility analysis runs | **US-035-AC1** - Given type changes, when compatibility analysis runs, then safe widenings are distinguished from breaking changes. |
| Report nullable and alias changes | US-035-AC2 | claim_id and claim_key alias changes | the compatibility analysis runs | **US-035-AC2** - Given nullable or rename-with-alias changes, when analysis runs, then context-specific compatibility is reported accurately. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-022 - Schema Compatibility Checker
- **Feature Requirements**: COMPAT-01, COMPAT-02
- **PRD Requirements**: FR-11.1, FR-11.2
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- changing the compatibility policy itself
- runtime schema migration

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
