---
ddx:
  id: US-035
---

# US-035: Check Schema Compatibility

**Feature**: FEAT-022 - Schema Compatibility Checker
**Feature Requirements**: COMPAT-01, COMPAT-02
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

## Acceptance Criteria

- [ ] **US-035-AC1** - Given type changes, when compatibility analysis runs, then safe widenings are distinguished from breaking changes.
- [ ] **US-035-AC2** - Given nullable or rename-with-alias changes, when analysis runs, then context-specific compatibility is reported accurately.

## Edge Cases

- **LOB-specific nullability**: tightening one LOB does not imply every LOB changed.
- **Alias rename**: aliases prevent remove/add false positives.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Type lattice | US-035-AC1 | widening/breaking type changes | check compatibility | correct severity |
| Nullable/alias | US-035-AC2 | LOB nullable or alias rename | check compatibility | contextual report |

## Dependencies

- **Feature Spec**: FEAT-022
- **PRD Requirements**: FR-11.1, FR-11.2

## Out of Scope

- Automatically migrating downstream production data.
