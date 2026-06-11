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

## Acceptance Criteria

- [ ] `generate_sql_ddl(umf)` produces a valid CREATE TABLE statement with correct column types, NOT NULL constraints, column comments, table comments, and suggested indexes
- [ ] `generate_pyspark_schema(umf)` produces valid PySpark `StructType` Python code with correct type imports
- [ ] `generate_json_schema(umf)` produces a valid JSON Schema (draft-07) with type mappings, maxLength for VARCHAR columns, and sample values as examples
- [ ] All three generators use the centralized type mappings from `type_mappings.py`
