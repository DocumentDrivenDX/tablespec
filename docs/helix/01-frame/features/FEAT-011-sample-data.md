---
ddx:
  id: FEAT-011
---

# FEAT-011: Sample Data Generation

**Status**: Implemented
**Priority**: P1
**Feature ID**: FEAT-011
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Sample Data Generation
**Covered PRD Requirements**: FR-12.1, FR-12.2, FR-12.3, FR-12.4, FR-12.5, FR-12.6
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Generate realistic healthcare-specific sample data from UMF specifications, respecting constraints, foreign keys, and domain types.

## Components

### Engine (`sample_data/engine.py`)
- Orchestrates generation across multiple tables
- Resolves foreign key dependencies via relationship graph

### Generators (`sample_data/generators.py`)
- `HealthcareDataGenerators` - Domain-specific generators (SSN, NPI, phone, state codes, drug codes)

### Column Value Generator (`sample_data/column_value_generator.py`)
- Type-aware value generation (VARCHAR, INTEGER, DATE, DECIMAL, BOOLEAN)
- Constraint-aware: value sets, regex patterns, min/max ranges

### Constraint Handlers (`sample_data/constraint_handlers.py`)
- Process UMF validation rules into generation constraints

### Foreign Keys (`sample_data/foreign_keys.py`)
- Referential integrity across generated tables

### Graph (`sample_data/graph.py`)
- Dependency DAG for multi-table generation ordering

### Config (`sample_data/config.py`)
- `GenerationConfig` - Row counts, output format, seed, locale

### Filename Generator (`sample_data/filename_generator.py`)
- Generate filenames from UMF file format specifications
## User Stories

- [US-013 — Generate Sample Data from UMF](../user-stories/US-013-generate-sample-data.md)

## Source

- `src/tablespec/sample_data/`
