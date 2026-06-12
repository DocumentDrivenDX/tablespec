---
ddx:
  id: US-006
---

# US-006: Extract UMF Constraints from an Existing GX Suite

**Feature**: FEAT-004 — Great Expectations Integration
**PRD Requirements**: FR-4.4, FR-4.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data quality engineer with existing Great Expectations suites,
**I want** extract validation constraints from those suites back into UMF format,
**So that** I can consolidate tribal knowledge already captured in GX into the canonical UMF schema and avoid maintaining rules in two places.

## Context

This story covers the extract umf constraints from an existing gx suite slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a extract umf constraints from an existing gx suite fixture or source object.
2. System runs the the GX constraint extractor runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-006-AC1** — Given a GX suite for `member_id`, `plan_code`, and `status` constraints, when the GX constraint extractor runs, then `GXConstraintExtractor` parses an existing GX suite and extracts value sets, regex patterns, strftime format strings, and metadata hints into UMF `ValidationRules`
- [ ] **US-006-AC2** — Given a GX suite for `member_id`, `plan_code`, and `status` constraints, when the GX constraint extractor runs, then Extracted constraints can be merged into an existing UMF schema
- [ ] **US-006-AC3** — Given a GX suite for `member_id`, `plan_code`, and `status` constraints, when the GX constraint extractor runs, then Sample values are generated from extracted regex patterns for documentation purposes
- [ ] **US-006-AC4** — Given a GX suite for `member_id`, `plan_code`, and `status` constraints, when the GX constraint extractor runs, then `GXSchemaValidator` validates expectation types against the GX library and produces corrected schemas containing only valid types

## Edge Cases

- **unknown GX types are rejected or corrected**: unknown GX types are rejected or corrected
- **regex and value-set extraction must preserve metadata**: regex and value-set extraction must preserve metadata
- **merged UMF facts should not duplicate rules**: merged UMF facts should not duplicate rules

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Extract value-set and regex rules | US-006-AC1 | status in ("active", "inactive"); regex ^[A-Z]{2}$; format yyyy-MM-dd | the GX constraint extractor runs | `GXConstraintExtractor` parses an existing GX suite and extracts value sets, regex patterns, strftime format strings, and metadata hints into UMF `ValidationRules` |
| Merge extracted constraints into UMF | US-006-AC2 | member UMF with status="active" and service_date="2024-01-01" | the GX constraint extractor runs | Extracted constraints can be merged into an existing UMF schema |
| Generate sample values from regex | US-006-AC3 | plan_code regex ^P[0-9]{3}$ | the GX constraint extractor runs | Sample values are generated from extracted regex patterns for documentation purposes |
| Correct unknown expectation types | US-006-AC4 | unknown expectation type expect_column_values_to_have_entropy | the GX constraint extractor runs | `GXSchemaValidator` validates expectation types against the GX library and produces corrected schemas containing only valid types |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-004 — Great Expectations Integration
- **Feature Requirements**: GX-04, GX-05, GX-06
- **PRD Requirements**: FR-4.4, FR-4.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- suite execution itself
- introducing new GX expectation types

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
