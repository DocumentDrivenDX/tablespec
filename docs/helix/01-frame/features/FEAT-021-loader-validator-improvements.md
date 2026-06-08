---
ddx:
  id: FEAT-021
---

# FEAT-021: UMF Loader & Validator Improvements

**Status**: Implemented
**Priority**: P1
**Feature ID**: FEAT-021
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: UMF Model and I/O; Split-Format UMF
**Covered PRD Requirements**: FR-1.7, FR-10.2, FR-10.3
**Cross-Subsystem Rationale**: Cross-subsystem hardening: loader diagnostics and validator checks protect the same UMF load path.

## Description

Improve error reporting and validation coverage in the UMF loading and validation pipeline.

## Components

### Targeted Error Messages (`src/tablespec/umf_loader.py`)

Replace generic "Cannot detect format" errors in `umf_loader.py` with specific diagnostic messages:

- "No `table.yaml` found in {path}" when the table metadata file is missing.
- "No `columns/` subdirectory found in {path}" when column definitions are absent.
- "Found `table.yaml` but it is empty or malformed: {detail}" for parse errors.
- "Column file `{name}.yaml` failed validation: {detail}" for individual column issues.

Each message should include the path searched and what was expected.

### Expectation Type Validation (`src/tablespec/umf_validator.py`)

Validator checks that expectation types referenced in the suite are recognized GX expectation types. Unknown types produce warnings (not errors) to allow forward compatibility with newer GX versions.

Uses a known-types registry derived from GX's built-in expectation list, updatable without code changes.

### Split Format Roundtrip Property Test (`tests/unit/test_umf_loader.py`)

Hypothesis property test: any valid UMF produced by `umf_object()` strategy survives `save -> load` through split format with all fields preserved. Catches serialization edge cases (empty lists, None vs missing, special characters in descriptions).
## User Stories

- [US-034 — Load and Validate UMF with Clear Errors](../user-stories/US-034-load-and-validate-umf-with-clear-errors.md)

## Source

- `src/tablespec/umf_loader.py`
- `src/tablespec/umf_validator.py`

## Dependencies

- FEAT-016 (Hypothesis strategies, property testing patterns)
