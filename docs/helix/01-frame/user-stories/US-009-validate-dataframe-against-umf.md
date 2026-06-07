---
ddx:
  id: US-009
---

# US-009: Validate a DataFrame Against a UMF Schema

**Feature**: FEAT-007 — Table Validation
**PRD Requirements**: FR-7.1, FR-7.2, FR-7.3, FR-7.4, FR-7.5, FR-7.6
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer running a PySpark pipeline,
**I want** validate a DataFrame against its UMF specification at runtime,
**So that** I catch schema drift, type mismatches, missing columns, and business rule violations before data lands in the target table.

## Acceptance Criteria

- [ ] `TableValidator` validates a Spark DataFrame against a UMF schema, checking for missing columns, extra columns, data type mismatches, and LOB-specific nullable violations (requires `tablespec[spark]`)
- [ ] Business rule validation covers uniqueness, format patterns, and value constraints defined in UMF `ValidationRules`
- [ ] Validation errors are returned in a structured format matching `VALIDATION_ERROR_SCHEMA` for programmatic consumption
- [ ] `UMFValidator` validates UMF files themselves against the JSON schema plus business rules (VARCHAR length defaults, DECIMAL precision defaults, duplicate column name fixing)
- [ ] Validation can be run against a single file, a data dictionary, or a directory of UMF files
