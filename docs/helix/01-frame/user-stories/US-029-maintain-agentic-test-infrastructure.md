---
ddx:
  id: US-029
---

# US-029: Maintain Agentic Test Infrastructure

**Feature**: FEAT-016 - Testing Infrastructure for Agentic Development
**PRD Requirements**: FR-20.3
**Priority**: P0
**Status**: Approved

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

## Context

This story covers the maintain agentic test infrastructure slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a maintain agentic test infrastructure fixture or source object.
2. System runs the the test-harness helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-029-AC1** — Given a test that needs both a `member` UMF and a `member.suite.json` fixture, when the test-harness helpers run, then **US-029-AC1** - Given a test that needs a UMF or GX suite, when it uses the builder/harness helpers, then setup is deterministic and concise.
- [ ] **US-029-AC2** — Given a test that needs both a `member` UMF and a `member.suite.json` fixture, when the test-harness helpers run, then **US-029-AC2** - Given tests with Spark or no-Spark requirements, when pytest collects them, then markers allow the intended lane to run or skip explicitly.

## Edge Cases

- **Spark tests and no-Spark tests need explicit lane control**: Spark tests and no-Spark tests need explicit lane control
- **fixture setup should stay deterministic**: fixture setup should stay deterministic
- **harness helpers should be concise**: harness helpers should be concise

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Set up a UMF plus suite fixture | US-029-AC1 | member UMF and member.suite.json fixture | the test-harness helpers run | **US-029-AC1** - Given a test that needs a UMF or GX suite, when it uses the builder/harness helpers, then setup is deterministic and concise. |
| Route Spark and no-Spark tests | US-029-AC2 | pytest.mark.spark and pytest.mark.no_spark | the test-harness helpers run | **US-029-AC2** - Given tests with Spark or no-Spark requirements, when pytest collects them, then markers allow the intended lane to run or skip explicitly. |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-016 - Testing Infrastructure for Agentic Development
- **Feature Requirements**: TEST-01, TEST-02
- **PRD Requirements**: FR-20.3
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- adding new test frameworks
- changing the underlying fixture semantics

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
