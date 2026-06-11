---
ddx:
  id: FEAT-009
---

# FEAT-009: Excel Bidirectional Conversion

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-009
**Owner**: Data Stewardship
**Covered PRD Subsystem(s)**: Excel Bidirectional Conversion
**Covered PRD Requirements**: FR-9.1, FR-9.2, FR-9.3, FR-9.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Round-trip conversion between Excel workbooks and UMF schemas, designed for non-technical domain expert collaboration.

## Components

### UMF to Excel (`UMFToExcelConverter`)
- Data validation dropdowns for types, nullable, severity
- Column formatting with headers, styles, and conditional formatting
- Helper columns for validation status and error messages

### Excel to UMF (`ExcelToUMFConverter`)
- Strict validation of Excel input against UMF schema rules
- Type inference and constraint extraction from cell values

### Git-Integrated Import (`excel_import_git.py`)
- Atomic per-change commits using UMF diff
- Preserves change attribution in git history

## Dependencies

- openpyxl
## User Stories

- [US-011 — Round-Trip UMF Through Excel](../user-stories/US-011-excel-round-trip.md)

## Source

- `src/tablespec/excel_converter.py`
- `src/tablespec/excel_import_git.py`
