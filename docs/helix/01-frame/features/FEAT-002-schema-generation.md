---
ddx:
  id: FEAT-002
---

# FEAT-002: Schema Generation

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-002
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Schema Generation
**Covered PRD Requirements**: FR-2.1, FR-2.2, FR-2.3
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Generate schema definitions in multiple output formats from UMF metadata.

## Supported Formats

1. **SQL DDL** (`generate_sql_ddl`) - CREATE TABLE with NOT NULL, column/table comments, suggested indexes
2. **PySpark** (`generate_pyspark_schema`) - StructType Python code with correct type imports
3. **JSON Schema** (`generate_json_schema`) - Draft-07 schema with type mapping, maxLength, examples
## User Stories

- [US-003 — Generate SQL DDL from a UMF Schema](../user-stories/US-003-generate-sql-ddl-from-umf.md)

## Source

- `src/tablespec/schemas/generators.py`
- Type conversions via `src/tablespec/type_mappings.py`
