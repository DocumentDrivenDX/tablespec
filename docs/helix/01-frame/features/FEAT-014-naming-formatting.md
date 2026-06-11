---
ddx:
  id: FEAT-014
---

# FEAT-014: Naming and Formatting Utilities

**Status**: Approved
**Priority**: P2
**Feature ID**: FEAT-014
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Naming Utilities; Date Format System
**Covered PRD Requirements**: FR-16.1, FR-16.2, FR-16.3, FR-17.1, FR-17.2, FR-17.3
**Cross-Subsystem Rationale**: Cross-subsystem utility surface: identifier normalization and date-format notation are shared formatting primitives.

## Description

Naming conventions, date format definitions, and YAML formatting utilities.

## Components

### Naming (`naming.py`)
- `to_spark_identifier()` - Convert any string to valid lowercase snake_case SQL/Spark identifier
- `position_sort_key()` - Sort key for Excel-style column position ordering
- Handles edge cases: PascalCase, special characters, leading digits

### Date Formats (`date_formats.py`)
- `DateFormat` - Dataclass for format definitions with UMF notation
- `FormatType` enum: DATE, DATETIME, TIME
- Supported format catalog with strftime conversion
- Used by sample data generation, validation, and type conversion

### YAML Formatter (`formatting/yaml_formatter.py`)
- Idempotent YAML formatting using ruamel.yaml
- Alphabetical key sorting, literal block scalars, comment preservation
- 2-space mapping indent, 4-space sequence indent, 72-char line length

### Formatting Constants (`formatting/constants.py`)
- Shared configuration for formatting behavior
## User Stories

- [US-027 — Normalize Names and Date Formats](../user-stories/US-027-normalize-names-and-date-formats.md)

## Source

- `src/tablespec/naming.py`
- `src/tablespec/date_formats.py`
- `src/tablespec/formatting/`
