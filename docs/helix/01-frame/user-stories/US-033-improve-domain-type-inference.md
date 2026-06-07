---
ddx:
  id: US-033
---

# US-033: Improve Domain Type Inference

**Feature**: FEAT-020 - Domain Type System Improvements
**Feature Requirements**: DOMAIN-01, DOMAIN-02, DOMAIN-03
**PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Priority**: P1
**Status**: Implemented

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

## Acceptance Criteria

- [ ] **US-033-AC1** - Given abbreviated healthcare column names, when inference runs, then expanded-name matches improve confidence without false positives on unknown columns.
- [ ] **US-033-AC2** - Given custom domain packs, when the registry loads them, then inference and sample-data generation can use the added domains.

## Edge Cases

- **Ambiguous matches**: inference reports confidence/runner-up instead of hiding uncertainty.
- **Unknown columns**: no domain type is returned when evidence is insufficient.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Abbreviation match | US-033-AC1 | abbreviated column names | run inference | accurate confidence-ranked result |
| Custom pack | US-033-AC2 | custom registry/domain pack | infer/generate | added domain used |

## Dependencies

- **Feature Spec**: FEAT-020
- **PRD Requirements**: FR-14.x

## Out of Scope

- Automated semantic approval without user review.
