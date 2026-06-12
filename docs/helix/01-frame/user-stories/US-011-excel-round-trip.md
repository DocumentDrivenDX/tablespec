---
ddx:
  id: US-011
---

# US-011: Round-Trip UMF Through Excel

**Feature**: FEAT-009 — Excel Bidirectional Conversion
**PRD Requirements**: FR-9.1, FR-9.2, FR-9.3, FR-9.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data steward who works primarily in Excel,
**I want** export a UMF schema to Excel, make edits with validation assistance, and import it back,
**So that** I can review and update table definitions without learning YAML syntax.

## Context

This story covers the round-trip umf through excel slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a round-trip umf through excel fixture or source object.
2. System runs the the Excel round-trip tools run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-011-AC1** — Given a `member.xlsx` workbook with `member_id` and `plan_code` columns, when the Excel round-trip tools run, then **US-011-AC1** - `UMFToExcelConverter` produces a workbook with dropdown validation for data types and nullable values
- [ ] **US-011-AC2** — Given a `member.xlsx` workbook with `member_id` and `plan_code` columns, when the Excel round-trip tools run, then **US-011-AC2** - `ExcelToUMFConverter` imports the workbook back to a valid UMF object
- [ ] **US-011-AC3** — Given a `member.xlsx` workbook with `member_id` and `plan_code` columns, when the Excel round-trip tools run, then **US-011-AC3** - Round-trip (export then import) preserves all UMF fields
- [ ] **US-011-AC4** — Given a `member.xlsx` workbook with `member_id` and `plan_code` columns, when the Excel round-trip tools run, then **US-011-AC4** - Invalid entries in Excel produce clear validation errors on import

## Edge Cases

- **invalid workbook values**: invalid workbook values
- **round-trip preservation of nullability and defaults**: round-trip preservation of nullability and defaults
- **dropdown validation must survive export/import**: dropdown validation must survive export/import

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Export workbook with dropdowns | US-011-AC1 | member.xlsx with member_id and plan_code dropdowns | the Excel round-trip tools run | **US-011-AC1** - `UMFToExcelConverter` produces a workbook with dropdown validation for data types and nullable values |
| Import invalid workbook rows | US-011-AC2 | member.xlsx with invalid cell member_id="abc" | the Excel round-trip tools run | **US-011-AC2** - `ExcelToUMFConverter` imports the workbook back to a valid UMF object |
| Round-trip all UMF fields | US-011-AC3 | member.xlsx with member_id=1, plan_code="PPO", nullable=false | the Excel round-trip tools run | **US-011-AC3** - Round-trip (export then import) preserves all UMF fields |
| Reject invalid Excel entries | US-011-AC4 | member.xlsx with plan_code="TOO_LONG_CODE_123" | the Excel round-trip tools run | **US-011-AC4** - Invalid entries in Excel produce clear validation errors on import |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-009 — Excel Bidirectional Conversion
- **Feature Requirements**: EXCEL-01, EXCEL-02, EXCEL-03
- **PRD Requirements**: FR-9.1, FR-9.2, FR-9.3, FR-9.4
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- review workflows outside the workbook round-trip
- new validation semantics in Excel

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
