---
ddx:
  id: US-027
---

# US-027: Normalize Names and Date Formats

**Feature**: FEAT-014 - Naming and Formatting Utilities
**Feature Requirements**: NAME-01, DATE-01, YAML-01
**PRD Requirements**: FR-16.1, FR-16.2, FR-16.3, FR-17.1, FR-17.2, FR-17.3
**Priority**: P2
**Status**: Implemented

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

## Acceptance Criteria

- [ ] **US-027-AC1** - Given mixed identifier inputs, when naming utilities normalize them, then outputs are valid Spark identifiers and preserve deterministic ordering.
- [ ] **US-027-AC2** - Given UMF date formats and YAML specs, when formatting utilities process them, then date notation and YAML layout remain stable across repeated runs.

## Edge Cases

- **Leading digits or punctuation**: identifiers are made valid without producing empty names.
- **Repeated formatting**: formatting is idempotent.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Identifier normalization | US-027-AC1 | mixed names and Excel positions | run naming tests | valid deterministic identifiers and ordering |
| Date/YAML stability | US-027-AC2 | date-format and YAML fixtures | run formatter/date tests | stable converted formats and YAML output |

## Dependencies

- **Feature Spec**: FEAT-014
- **PRD Requirements**: FR-16.x, FR-17.x

## Out of Scope

- Business-specific naming policy beyond the UMF/Spark-safe conventions.
