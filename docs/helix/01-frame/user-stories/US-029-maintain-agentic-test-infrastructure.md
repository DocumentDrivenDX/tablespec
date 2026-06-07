---
ddx:
  id: US-029
---

# US-029: Maintain Agentic Test Infrastructure

**Feature**: FEAT-016 - Testing Infrastructure for Agentic Development
**Feature Requirements**: TEST-01, TEST-02, TEST-03
**PRD Requirements**: FR-20.3
**Priority**: P0
**Status**: Implemented

## Story

**As a** contributor changing tablespec behavior
**I want** reusable builders, GX harnesses, golden runners, strategies, and markers
**So that** I can verify changes quickly without hand-constructing every UMF, GX suite, or engine fixture

## Context

The testing infrastructure is a verification feature rather than a user-facing subsystem. It supports the Runtime Platform requirement that supported environments remain first-class by keeping local, no-Spark, Spark, and Connect lanes explicit.

## Walkthrough

1. Contributor writes a focused test using the builders, GX harness, or golden helpers.
2. System creates valid UMF/test data fixtures with clear markers.
3. Contributor runs the selected lane and gets deterministic results.

## Acceptance Criteria

- [ ] **US-029-AC1** - Given a test that needs a UMF or GX suite, when it uses the builder/harness helpers, then setup is deterministic and concise.
- [ ] **US-029-AC2** - Given tests with Spark or no-Spark requirements, when pytest collects them, then markers allow the intended lane to run or skip explicitly.

## Edge Cases

- **Optional engines absent**: tests skip visibly rather than passing silently.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Harness setup | US-029-AC1 | GX harness tests | run unit tests | deterministic expectations and fixtures |
| Marker discipline | US-029-AC2 | marked Spark/no-Spark tests | collect/run pytest | explicit lane behavior |

## Dependencies

- **Feature Spec**: FEAT-016
- **PRD Requirements**: FR-20.3

## Out of Scope

- Adding new product behavior through test helpers.
