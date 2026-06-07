---
ddx:
  id: FEAT-003
---

# FEAT-003: Type System Mappings

**Status**: Implemented
**Priority**: P0
**Feature ID**: FEAT-003
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Type Mappings
**Covered PRD Requirements**: FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-3.5
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Central type conversion hub between UMF, PySpark, JSON Schema, and Great Expectations type systems.

## Functions

- `map_to_pyspark_type(data_type)` - UMF to PySpark (e.g., VARCHAR -> StringType())
- `map_to_json_type(data_type)` - UMF to JSON Schema (e.g., INTEGER -> integer)
- `map_to_gx_spark_type(data_type)` - UMF to GX Spark type names

## Supported Types

VARCHAR, STRING, CHAR, INTEGER, INT, BIGINT, SMALLINT, TINYINT, DECIMAL, FLOAT, DOUBLE, BOOLEAN, DATE, TIMESTAMP, TEXT, DATETIME

## Behaviors

- Case-insensitive resolution
- Unknown types default to StringType/string
- DATE maps to StringType (stored as YYYYMMDD strings)
## User Stories

- [US-004 — Convert Column Types Between Type Systems](../user-stories/US-004-convert-types-between-systems.md)

## Source

- `src/tablespec/type_mappings.py`
