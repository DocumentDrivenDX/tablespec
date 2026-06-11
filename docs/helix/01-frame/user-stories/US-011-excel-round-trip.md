---
ddx:
  id: US-011
---

# US-011: Round-Trip UMF Through Excel

**Feature**: FEAT-009 — Excel Bidirectional Conversion
**PRD Requirements**: FR-9.1, FR-9.2, FR-9.3, FR-9.4
**Priority**: P1
**Status**: Approved

## Story

**As a** data steward who works primarily in Excel,
**I want** export a UMF schema to Excel, make edits with validation assistance, and import it back,
**So that** I can review and update table definitions without learning YAML syntax.

## Acceptance Criteria

- [ ] **US-011-AC1** - `UMFToExcelConverter` produces a workbook with dropdown validation for data types and nullable values
- [ ] **US-011-AC2** - `ExcelToUMFConverter` imports the workbook back to a valid UMF object
- [ ] **US-011-AC3** - Round-trip (export then import) preserves all UMF fields
- [ ] **US-011-AC4** - Invalid entries in Excel produce clear validation errors on import
