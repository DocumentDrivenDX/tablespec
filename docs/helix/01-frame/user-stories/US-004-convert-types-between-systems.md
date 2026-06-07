---
ddx:
  id: US-004
---

# US-004: Convert Column Types Between Type Systems

**Feature**: FEAT-003 — Type System Mappings
**PRD Requirements**: FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-3.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer working across PySpark and SQL environments,
**I want** convert UMF column types to PySpark, JSON Schema, and Great Expectations type representations,
**So that** I can use a single UMF schema as the source of truth across all downstream systems without manually mapping types.

## Acceptance Criteria

- [ ] `map_to_pyspark_type(data_type)` returns the correct PySpark type for all supported UMF types (VARCHAR, INTEGER, DECIMAL, DATE, BOOLEAN, etc.)
- [ ] `map_to_json_type(data_type)` returns correct JSON Schema type strings
- [ ] `map_to_gx_spark_type(data_type)` returns correct Great Expectations Spark type names
- [ ] Type resolution is case-insensitive (e.g., "varchar" and "VARCHAR" both work)
- [ ] Unknown/unrecognized types default gracefully to string equivalents rather than raising errors
- [ ] DATE types map to StringType (reflecting YYYYMMDD string storage convention)
