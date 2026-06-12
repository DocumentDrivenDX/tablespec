---
ddx:
  id: US-003
---

# US-003: Generate SQL DDL from a UMF Schema

**Feature**: FEAT-002 — Schema Generation
**PRD Requirements**: FR-2.1, FR-2.2, FR-2.3
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer maintaining SQL pipelines,
**I want** generate CREATE TABLE DDL from a UMF schema,
**So that** my database table definitions stay in sync with the canonical UMF specification without manual SQL authoring.

## Context

This story covers the generate sql ddl from a umf schema slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate sql ddl from a umf schema fixture or source object.
2. System runs the the schema-generation helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-003-AC1** — Given `member_id INTEGER NOT NULL` and `plan_code VARCHAR(12)` in the `member` UMF, when the schema-generation helpers run, then `generate_sql_ddl(umf)` produces a valid `CREATE TABLE` statement with correct column types, `NOT NULL` constraints, column comments, table comments, and suggested indexes
- [ ] **US-003-AC2** — Given `member_id INTEGER NOT NULL` and `plan_code VARCHAR(12)` in the `member` UMF, when the schema-generation helpers run, then `generate_pyspark_schema(umf)` produces valid PySpark `StructType` Python code with correct type imports
- [ ] **US-003-AC3** — Given `member_id INTEGER NOT NULL`, `plan_code VARCHAR(12)`, `amount DECIMAL(10,2)`, and `service_date DATE` in the `member` UMF, when the schema-generation helpers run, then `generate_json_schema(umf)` produces a valid JSON Schema (draft-07) with type mappings, `maxLength` for `VARCHAR` columns, and sample values as examples
- [ ] **US-003-AC4** — Given `member_id INTEGER NOT NULL`, `plan_code VARCHAR(12)`, and `amount DECIMAL(10,2)` in the `member` UMF, when the schema-generation helpers run, then all three generators use the centralized type mappings from `type_mappings.py`

## Edge Cases

- **member_id and plan_code comments omitted**: `member_id` and `plan_code` comments omitted
- **VARCHAR length and DECIMAL precision must stay consistent**: VARCHAR length and DECIMAL precision must stay consistent
- **JSON Schema and PySpark outputs must stay aligned**: JSON Schema and PySpark outputs must stay aligned

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Emit CREATE TABLE for member | US-003-AC1 | `member_id INTEGER NOT NULL` and `plan_code VARCHAR(12)` | the schema-generation helpers run | `generate_sql_ddl(umf)` produces a valid `CREATE TABLE` statement with correct column types, `NOT NULL` constraints, column comments, table comments, and suggested indexes |
| Emit PySpark schema code | US-003-AC2 | `member_id INTEGER NOT NULL` and `plan_code VARCHAR(12)` | the schema-generation helpers run | `generate_pyspark_schema(umf)` produces valid PySpark `StructType` Python code with correct type imports |
| Emit JSON Schema with examples | US-003-AC3 | `member_id INTEGER NOT NULL`, `plan_code VARCHAR(12)`, `amount DECIMAL(10,2)`, and `service_date DATE` | the schema-generation helpers run | `generate_json_schema(umf)` produces a valid JSON Schema (draft-07) with type mappings, `maxLength` for `VARCHAR` columns, and sample values as examples |
| Keep type maps centralized | US-003-AC4 | `member_id INTEGER NOT NULL`, `plan_code VARCHAR(12)`, and `amount DECIMAL(10,2)` | the schema-generation helpers run | all three generators use the centralized type mappings from `type_mappings.py` |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-002 — Schema Generation
- **Feature Requirements**: DDL-01, DDL-02, DDL-03
- **PRD Requirements**: FR-2.1, FR-2.2, FR-2.3
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- runtime execution of the generated artifacts
- hand-authored SQL outside the shared type mappings

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
