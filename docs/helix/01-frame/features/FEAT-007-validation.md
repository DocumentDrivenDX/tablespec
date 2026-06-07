---
ddx:
  id: FEAT-007
---

# FEAT-007: Table Validation

**Status**: Implemented
**Priority**: P0
**Feature ID**: FEAT-007
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Table Validation; Table Merge
**Cross-Subsystem Rationale**: Cross-subsystem validation workflow: table merge uses UMF survivorship and validation metadata, and US-018 is the merge slice under this validation-facing feature. Runtime-platform behavior is governed by FR-20.x and ADR-010.
**Covered PRD Requirements**: FR-7.1–FR-7.8, FR-15.1, FR-15.2, FR-15.3 (with the Runtime-Platform contract FR-20.4)

## Description

Validate Spark DataFrames against UMF specifications and validate UMF files against JSON schema. Suite execution is **Connect-safe**: a compiled Great Expectations suite runs with identical verdicts on classic Spark, Sail (local Spark Connect), and Databricks serverless — see FEAT-025, ADR-010, ADR-011.

## Components

### Suite Executor (`validation/gx_executor.py`, `validation/native_executor.py`) [requires PySpark]
- `GXSuiteExecutor` — execute a compiled GX suite in a single batch pass.
- **Per-DataFrame engine routing** (FR-7.7): Spark Connect DataFrames (Sail / Databricks serverless) route to the native DataFrame-API executor; classic Spark DataFrames keep the unchanged GX `add_spark` path. Routing keys off the DataFrame's own module (`gx_executor.py:211-239`), never a process-global flag.
- **Why**: GX 1.x `add_spark` / `SparkDFExecutionEngine` asserts a live JVM `SparkContext` that does not exist on Connect, so data-scanning expectations otherwise silently return `success=False`/`result={}` (`native_executor.py:1-31`).
- `native_executor.evaluate_expectation()` — Connect-safe evaluators for every baseline expectation type, engine-correct via `_functions_for` / bound `df[col]`, returning the same `ExpectationResult` shape as the classic path.
- **Staged execution** (FR-7.8): `execute_staged()` classifies raw (string) vs ingested (typed) expectations and routes each to the correct DataFrame.
- **Fail-closed reconciliation**: GX-dropped results are re-evaluated standalone via the native validators so a dropped expectation never silently passes (`gx_executor.py:411-489`).

### Table Validator (`validation/table_validator.py`) [requires PySpark]
- `TableValidator` - Validate DataFrame against UMF
- Schema validation (missing/extra columns)
- Data type validation
- LOB-specific nullable validation
- Business rule validation (uniqueness, format, value constraints)
- Structured error output via `VALIDATION_ERROR_SCHEMA`

### UMF Validator (`umf_validator.py`)
- `UMFValidator` - Validate UMF files against JSON schema + business rules
- File, data, and directory validation
- Default specification application (VARCHAR length 255, DECIMAL precision 18/scale 2)
- Duplicate column name fixing

### Completeness Validator (`completeness_validator.py`)
- Validate completeness of UMF specifications against expected fields

### Relationship Validator (`relationship_validator.py`)
- Validate foreign key relationships and referential integrity definitions

### Naming Validator (`naming_validator.py`)
- Validate column and table names against naming conventions

## Source

- `src/tablespec/validation/gx_executor.py`
- `src/tablespec/validation/native_executor.py`
- `src/tablespec/validation/table_validator.py`
- `src/tablespec/umf_validator.py`
- `src/tablespec/completeness_validator.py`
- `src/tablespec/relationship_validator.py`
- `src/tablespec/naming_validator.py`
## User Stories

- [US-009 — Validate a DataFrame Against a UMF Schema](../user-stories/US-009-validate-dataframe-against-umf.md)
- [US-018 — Merge Table Files with Survivorship](../user-stories/US-018-merge-tables.md)

## Related

- FEAT-025 (Connect-safe GX suite validation — the execution layer beneath these validators)
- ADR-010 (Spark Connect / serverless runtime model), ADR-011 (Connect-safe GX native-executor routing), ADR-005 (unified expectation model)
