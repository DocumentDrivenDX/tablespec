---
ddx:
  id: US-009
---

# US-009: Validate a DataFrame Against a UMF Schema

**Feature**: FEAT-007 — Table Validation
**PRD Requirements**: FR-7.1, FR-7.2, FR-7.3, FR-7.4, FR-7.5, FR-7.6
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer running a PySpark pipeline,
**I want** validate a DataFrame against its UMF specification at runtime,
**So that** I catch schema drift, type mismatches, missing columns, and business rule violations before data lands in the target table.

## Context

This story covers the validate a dataframe against a umf schema slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a validate a dataframe against a umf schema fixture or source object.
2. System runs the the DataFrame validation flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-009-AC1** — Given a `member_df` Spark DataFrame with `member_id=1` and `status="active"`, when the DataFrame validation flow runs, then `TableValidator` validates a Spark DataFrame against a UMF schema, checking for missing columns, extra columns, data type mismatches, and LOB-specific nullable violations (requires `tablespec[spark]`)
- [ ] **US-009-AC2** — Given a `member_df` Spark DataFrame with `member_id=1` and `status="active"`, when the DataFrame validation flow runs, then Business rule validation covers uniqueness, format patterns, and value constraints defined in UMF `ValidationRules`
- [ ] **US-009-AC3** — Given a `member_df` Spark DataFrame with `member_id=1` and `status="active"`, when the DataFrame validation flow runs, then Validation errors are returned in a structured format matching `VALIDATION_ERROR_SCHEMA` for programmatic consumption
- [ ] **US-009-AC4** — Given a `member_df` Spark DataFrame with `member_id=1` and `status="active"`, when the DataFrame validation flow runs, then `UMFValidator` validates UMF files themselves against the JSON schema plus business rules (VARCHAR length defaults, DECIMAL precision defaults, duplicate column name fixing)
- [ ] **US-009-AC5** — Given a `member_df` Spark DataFrame with `member_id=1` and `status="active"`, when the DataFrame validation flow runs, then Validation can be run against a single file, a data dictionary, or a directory of UMF files

## Edge Cases

- **missing columns and extra columns**: missing columns and extra columns
- **LOB-specific nullability violations**: LOB-specific nullability violations
- **structured errors must remain machine-readable**: structured errors must remain machine-readable

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Validate a clean member DataFrame | US-009-AC1 | member_df with member_id=1 and status="active" | the DataFrame validation flow runs | `TableValidator` validates a Spark DataFrame against a UMF schema, checking for missing columns, extra columns, data type mismatches, and LOB-specific nullable violations (requires `tablespec[spark]`) |
| Reject missing and extra columns | US-009-AC2 | member_df missing plan_code and containing nickname="Ace" | the DataFrame validation flow runs | Business rule validation covers uniqueness, format patterns, and value constraints defined in UMF `ValidationRules` |
| Report nullable violations | US-009-AC3 | member_df with status=NULL and nullable=false | the DataFrame validation flow runs | Validation errors are returned in a structured format matching `VALIDATION_ERROR_SCHEMA` for programmatic consumption |
| Return structured validation errors | US-009-AC4 | tables/member/table.yaml with duplicate member_id | the DataFrame validation flow runs | `UMFValidator` validates UMF files themselves against the JSON schema plus business rules (VARCHAR length defaults, DECIMAL precision defaults, duplicate column name fixing) |
| Load UMF from file or directory | US-009-AC5 | tables/member/ and tables/claim.yaml | the DataFrame validation flow runs | Validation can be run against a single file, a data dictionary, or a directory of UMF files |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-007 — Table Validation
- **Feature Requirements**: VAL-01, VAL-02, VAL-03
- **PRD Requirements**: FR-7.1, FR-7.2, FR-7.3, FR-7.4, FR-7.5, FR-7.6
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- SQL DDL emission
- pipeline blocking and report formatting

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
