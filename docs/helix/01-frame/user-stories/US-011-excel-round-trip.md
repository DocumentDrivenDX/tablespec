---
ddx:
  id: US-011
---

# US-011: Round-Trip UMF Through Excel

**Feature**: FEAT-009 — Excel Bidirectional Conversion
**PRD Requirements**: FR-9.1, FR-9.2, FR-9.3, FR-9.4
**Priority**: P1
**Status**: Implemented

## Story

**As a** data steward who works primarily in Excel,
**I want** export a UMF schema to Excel, make edits with validation assistance, and import it back,
**So that** I can review and update table definitions without learning YAML syntax.

## Acceptance Criteria

- [ ] `UMFToExcelConverter` produces a workbook with dropdown validation for data types and nullable values
- [ ] `ExcelToUMFConverter` imports the workbook back to a valid UMF object
- [ ] Round-trip (export then import) preserves all UMF fields
- [ ] Invalid entries in Excel produce clear validation errors on import
