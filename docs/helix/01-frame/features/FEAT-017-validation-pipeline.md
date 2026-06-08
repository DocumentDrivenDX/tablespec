---
ddx:
  id: FEAT-017
---

# FEAT-017: Validation Pipeline Improvements

**Status**: Implemented
**Priority**: P0
**Feature ID**: FEAT-017
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Great Expectations Integration; Table Validation; Quality Baselines
**Covered PRD Requirements**: FR-4.3, FR-7.5, FR-7.6, FR-13.3
**Cross-Subsystem Rationale**: Cross-subsystem validation workflow: suite execution, blocking behavior, reporting, and baselines are one user-visible validation pipeline.

## Description

Fix structural issues in the validation pipeline: redundant expectations, missing execution paths, non-functional blocking behavior, and lack of reporting.

## Components

### Suite-Level GX Execution (`src/tablespec/gx_wrapper.py`)

Replace per-call validator creation in `gx_wrapper.py` with batch execution. One datasource, one validator, one pass for all expectations in a suite. Eliminates repeated GX context setup overhead.

### Staged Execution (`src/tablespec/gx_wrapper.py`)

`GXSuiteExecutor.execute_staged()` classifies expectations by stage using `classify_validation_type()`, then executes:

- **Raw expectations** against string data (all columns VARCHAR).
- **Ingested expectations** against typed data (columns cast to UMF-declared types).

This connects the existing `classify_validation_type()` function (currently unused) to the execution pipeline.

### Baseline Generator Fixes (`src/tablespec/gx_baseline.py`)

`BaselineExpectationGenerator` currently generates redundant expectation types:

- `expect_column_to_exist` -- redundant when column-level expectations already imply existence.
- `expect_column_values_to_be_of_type` -- redundant at raw stage where all columns are strings.

Stop generating these. Enforce via Hypothesis property test: no generated suite contains redundant types.

NOTE: There is a codebase contradiction to reconcile. `REQUIRED_BASELINE_EXPECTATION_TYPES` in `gx_baseline.py` includes `expect_column_to_exist`, while `REDUNDANT_VALIDATION_TYPES` in `models/umf.py` lists it as redundant. The fix should remove `expect_column_to_exist` from `REQUIRED_BASELINE_EXPECTATION_TYPES` or reconcile these two sets so they are consistent.

### Profiling to Expectations (`src/tablespec/gx_baseline.py`)

Implement the TODO stub in `gx_baseline.py` that converts profiling statistics to expectations:

- High cardinality -> `expect_column_values_to_be_unique`
- Min/max values -> `expect_column_values_to_be_between`
- High completeness -> `expect_column_values_to_not_be_null`
- Regex patterns -> `expect_column_values_to_match_regex` (for columns with detected format patterns)

Test via GX harness (FEAT-016) against actual data to verify generated expectations are correct.

Ingested-stage checks to implement, in priority order:

1. `expect_column_values_to_be_between` -- numeric and date range validation on typed data.
2. `expect_column_pair_values_a_to_be_greater_than_b` -- cross-column ordering (e.g., end_date > start_date).
3. `expect_column_pair_values_to_be_equal` -- cross-column equality constraints.

### Blocking Behavior (`src/tablespec/quality/executor.py`)

Implement `should_block_pipeline()` in `quality/executor.py`. Currently always returns `False`.

Must consider:
- Individual expectation severity
- `blocking` flag on expectation meta
- Suite-level thresholds
- Aggregate failure rates across the suite

### Validation Reporting (`src/tablespec/quality/executor.py`)

`ValidationReport` class producing:

- Human-readable summaries (pass/fail counts, failure details)
- Structured failure details with expectation type, column, observed vs expected
- Rich-formatted tables for CLI output
- Machine-readable dicts for programmatic consumption
## User Stories

- [US-030 — Run Validation Pipeline with Blocking Reports](../user-stories/US-030-run-validation-pipeline-with-blocking-reports.md)

## Source

- `src/tablespec/gx_wrapper.py`
- `src/tablespec/gx_baseline.py`
- `src/tablespec/quality/executor.py`
- `src/tablespec/models/umf.py`

## Dependencies

- ADR-005 (unified expectation model)
- FEAT-016 (test harness for validation testing)
