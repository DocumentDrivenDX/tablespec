---
ddx:
  id: US-004
---

# US-004: Convert Column Types Between Type Systems

**Feature**: FEAT-003 — Type System Mappings
**PRD Requirements**: FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-3.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer working across PySpark and SQL environments,
**I want** convert UMF column types to PySpark, JSON Schema, and Great Expectations type representations,
**So that** I can use a single UMF schema as the source of truth across all downstream systems without manually mapping types.

## Context

This story covers the convert column types between type systems slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a convert column types between type systems fixture or source object.
2. System runs the the type-mapping helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-004-AC1** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then `map_to_pyspark_type(data_type)` returns the correct PySpark type for all supported UMF types (VARCHAR, INTEGER, DECIMAL, DATE, BOOLEAN, etc.)
- [ ] **US-004-AC2** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then `map_to_json_type(data_type)` returns correct JSON Schema type strings
- [ ] **US-004-AC3** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then `map_to_gx_spark_type(data_type)` returns correct Great Expectations Spark type names
- [ ] **US-004-AC4** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then Type resolution is case-insensitive (e.g., "varchar" and "VARCHAR" both work)
- [ ] **US-004-AC5** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then Unknown/unrecognized types default gracefully to string equivalents rather than raising errors
- [ ] **US-004-AC6** — Given supported types such as `VARCHAR(20)`, `DECIMAL(10,2)`, and `DATE`, when the type-mapping helpers run, then DATE types map to StringType (reflecting YYYYMMDD string storage convention)

## Edge Cases

- **case-insensitive type strings**: case-insensitive type strings
- **unknown types fall back to string-like behavior**: unknown types fall back to string-like behavior
- **DATE maps to the storage convention used by the product**: DATE maps to the storage convention used by the product

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Map supported UMF types to PySpark | US-004-AC1 | VARCHAR(20), INTEGER, DECIMAL(10,2), DATE, BOOLEAN | the type-mapping helpers run | `map_to_pyspark_type(data_type)` returns the correct PySpark type for all supported UMF types (VARCHAR, INTEGER, DECIMAL, DATE, BOOLEAN, etc.) |
| Map UMF types to JSON Schema | US-004-AC2 | data_type="VARCHAR(20)" and data_type="INTEGER" | the type-mapping helpers run | `map_to_json_type(data_type)` returns correct JSON Schema type strings |
| Map UMF types to GX names | US-004-AC3 | data_type="VARCHAR(20)" and data_type="DATE" | the type-mapping helpers run | `map_to_gx_spark_type(data_type)` returns correct Great Expectations Spark type names |
| Lookup types case-insensitively | US-004-AC4 | data_type="varchar" and data_type="DECIMAL" | the type-mapping helpers run | Type resolution is case-insensitive (e.g., "varchar" and "VARCHAR" both work) |
| Fallback unknown types safely | US-004-AC5 | data_type="GEOGRAPHY" | the type-mapping helpers run | Unknown/unrecognized types default gracefully to string equivalents rather than raising errors |
| Store DATE as StringType | US-004-AC6 | data_type="DATE" | the type-mapping helpers run | DATE types map to StringType (reflecting YYYYMMDD string storage convention) |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-003 — Type System Mappings
- **Feature Requirements**: TYPE-01, TYPE-02, TYPE-03
- **PRD Requirements**: FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-3.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- new data types not already governed by the feature spec
- runtime schema inference

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
