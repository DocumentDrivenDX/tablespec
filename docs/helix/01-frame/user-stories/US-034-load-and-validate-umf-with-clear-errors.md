---
ddx:
  id: US-034
---

# US-034: Load and Validate UMF with Clear Errors

**Feature**: FEAT-021 - UMF Loader & Validator Improvements
**Feature Requirements**: LOAD-04, LOAD-05
**PRD Requirements**: FR-1.7, FR-10.2, FR-10.3
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer fixing malformed UMF files
**I want** loader and validator errors to identify the failing path, column file, and expectation type
**So that** I can repair specs quickly instead of debugging generic parse failures

## Context

This story connects loader diagnostics, expectation validation, and split-format roundtrip hardening to the UMF I/O and Split-Format PRD families.

## Walkthrough

1. User loads a malformed split-format or JSON UMF.
2. System reports the missing/malformed file or invalid expectation type with context.
3. User fixes the specific input and re-runs the loader.

## Context

This story covers the load and validate umf with clear errors slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a load and validate umf with clear errors fixture or source object.
2. System runs the the split-format loader runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-034-AC1** — Given split-format input missing `columns/member_id.yaml` or containing a malformed `table.yaml`, when the split-format loader runs, then errors name the missing or invalid file and expected structure.
- [ ] **US-034-AC2** — Given `tables/member/table.yaml` and `tables/member/columns/member_id.yaml` with valid UMF content, when the split-format loader runs, then roundtrip preserves fields across the saved and reloaded files.

## Edge Cases

- **missing `columns/member_id.yaml` must produce explicit errors**: missing `columns/member_id.yaml` must produce explicit errors
- **round-trip member files should preserve all fields**: round-trip `tables/member/table.yaml` and `tables/member/columns/member_id.yaml` should preserve all fields
- **legacy split-format shape must remain discoverable**: legacy split-format shape must remain discoverable

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Reject malformed split inputs | US-034-AC1 | missing `columns/member_id.yaml` or malformed `tables/member/table.yaml` | the split-format loader runs | errors name the missing or invalid file and expected structure |
| Round-trip split UMF fields | US-034-AC2 | `tables/member/table.yaml` and `tables/member/columns/member_id.yaml` | the split-format loader runs | roundtrip preserves fields across the saved and reloaded files |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-021 - UMF Loader & Validator Improvements
- **Feature Requirements**: LOAD-04, LOAD-05
- **PRD Requirements**: FR-1.7, FR-10.2, FR-10.3
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- new loader formats beyond split and JSON
- runtime compilation from the loaded UMF

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
