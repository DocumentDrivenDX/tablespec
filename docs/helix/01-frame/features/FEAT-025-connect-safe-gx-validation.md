---
ddx:
  id: FEAT-025
---

# Feature Specification: FEAT-025 — Connect-Safe GX Suite Validation

**Feature ID**: FEAT-025
**Status**: Implemented
**Priority**: P0
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Table Validation
**Covered PRD Requirements**: FR-7.7, FR-7.8 (with the Runtime-Platform contract FR-20.4)
**Cross-Subsystem Rationale**: None — single subsystem (Table Validation). The Runtime-Platform requirements (FR-20.x) are the platform contract this feature *applies*, governed by ADR-010; they are not owned here.

## Overview

This feature makes a compiled Great Expectations suite execute with correct verdicts on Spark Connect and Databricks serverless, not only on classic Spark. It exists because GX 1.x's `add_spark` engine silently returns wrong answers on Connect (PRD FR-7.7), which would otherwise let dirty data pass and clean data fail on the exact platforms production runs on.

## Ideal Future State

A data-quality engineer runs a compiled GX suite against a DataFrame and gets the same pass/fail verdict regardless of whether the session is classic Spark in CI, Sail (local Spark Connect) in the test lane, or Databricks serverless in production. They never have to know which engine is underneath: the executor detects it from the DataFrame and picks an execution path that is correct for that engine. A clean table passes everywhere; a dirty table fails everywhere; there are no silent false-negatives.

## Problem Statement

- **Current situation**: `GXSuiteExecutor` ran every suite through GX's `add_spark` / `SparkDFExecutionEngine`. That engine uses classic `pyspark.sql.functions` (`F.lit`, `F.count`) which assert `SparkContext._active_spark_context is not None` (`src/tablespec/validation/native_executor.py:1-31`).
- **Pain points**: On Spark Connect (Sail, Databricks serverless) there is no JVM `SparkContext`; the assertion fails, the error is swallowed, and **every data-scanning expectation silently returns `success=False` / `result={}`**. A clean DataFrame fails validation, and a uniform false-negative can mask real data problems. The failure is silent — no exception, just wrong answers.
- **Desired outcome**: A compiled suite yields identical verdicts on classic Spark, Sail, and Databricks serverless. Measured by the Sail Connect lane and the cross-engine conformance harness showing classic-vs-Connect parity for every supported expectation type.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Engine detection & routing | "Which execution path is correct for this DataFrame?" | Detect Connect vs classic from the DataFrame's own module and route per-DataFrame (`gx_executor.py:211-239`). |
| Native expectation evaluation | "Will my baseline expectations evaluate correctly on Connect?" | Re-implement each baseline expectation type via the DataFrame API with engine-correct functions, returning the same result shape (`native_executor.py`). |
| Custom-expectation native handlers | "Do my cast/domain/date-order checks run on Connect?" | Provide Connect-safe handlers for the tablespec custom expectations (`gx_executor.py:297-339`). |
| Dropped-result reconciliation | "Can a dropped expectation silently pass?" | Re-evaluate any GX-dropped `(type, column)` standalone and fail closed (`gx_executor.py:411-489`). |

## Requirements

### Functional Requirements by Area

#### Engine detection & routing

VAL-CONNECT-01. The executor MUST classify a DataFrame as Spark Connect iff its type's module starts with `pyspark.sql.connect`, and route Connect DataFrames to the native DataFrame-API path and classic DataFrames to the GX `add_spark` path.
VAL-CONNECT-02. Routing MUST key off the DataFrame in hand, never a process-global flag, so a classic and a Connect session may coexist in one process (the Sail test lane) and each routes correctly.
VAL-CONNECT-03. The classic `add_spark` path MUST remain behaviorally unchanged for classic Spark DataFrames.

#### Native expectation evaluation

VAL-CONNECT-04. Each baseline expectation type the `BaselineExpectationGenerator` emits MUST have a native evaluator that produces a GX-shaped `{success, result}` dict matching what the `add_spark` path produces, so downstream consumers (`report.py`, `quality/executor.py`, `table_validator.py`) are unaffected.
VAL-CONNECT-05. Native evaluators MUST select the `functions` module / Column engine from the DataFrame itself (`_functions_for`, bound `df[col]`) so the same code is correct on classic Spark and Connect.
VAL-CONNECT-06. Native evaluators MUST honor the `mostly` threshold and GX non-null population semantics (only non-null values considered, except not-null itself), and honor a `row_condition` (`condition_parser="spark"`) when present.
VAL-CONNECT-07. An expectation type with no native evaluator MUST surface as a passing result with an explanatory `observed_value` (not a silent crash); `is_natively_supported()` MUST let callers assert coverage in tests.

#### Custom-expectation native handlers

VAL-CONNECT-08. The tablespec custom expectations (`expect_column_values_to_cast_to_type`, `expect_column_pair_values_a_to_be_greater_than_b`, `expect_column_date_to_be_in_current_year`, `expect_column_values_to_match_domain_type`) MUST evaluate Connect-safely via dedicated handlers.

#### Dropped-result reconciliation

VAL-CONNECT-09. When GX returns FEWER results than were fed (same-type collation, or a raised metric), each missing `(type, column)` MUST be re-evaluated standalone via the native validators; if it cannot be re-evaluated, it MUST fail closed (never silently pass).

### Non-Functional Requirements

- **Correctness**: Suite verdict for every supported expectation type is identical on classic Spark and Spark Connect (zero divergence in the conformance harness).
- **Performance**: The native path materializes only aggregates and bounded samples (`.count()`, `limit(10)`), never the full dataset to the driver.
- **Reliability**: A single failing expectation MUST NOT abort the suite; it is recorded as a failure with diagnostic detail.
- **Compatibility**: No change to the `ExpectationResult` / `SuiteExecutionResult` shapes consumed downstream.
## User Stories

- [US-022 — Validate a Compiled Suite on Spark Connect Without Silent Failure](../user-stories/US-022-validate-suite-on-connect-without-silent-failure.md)

## Edge Cases and Error Handling

- **Connect build lacks `try_to_timestamp(col, fmt)`**: fall back to format-less `try_to_timestamp` behind a structural prefilter regex (`native_executor.py:424-445`), gated on the per-session capability probe.
- **Numeric bounds against a string column**: cast to double (NULL-on-failure) so the comparison is numeric, not lexicographic (`native_executor.py:258-298`).
- **Unknown expectation type on the native path**: surfaced as a passing result with an explanatory `observed_value`; baseline suites only emit handled types.
- **GX collates two same-type custom expectations into one result on clean data**: reconciliation re-evaluates each standalone so the benign case is not false-failed and a real failure is not masked.

## Success Metrics

- Sail Connect lane (`tests/unit/test_validation_connect_sail.py`) passes every baseline + custom expectation type with verdicts equal to the classic `add_spark` path. The four custom expectations are additionally pinned to classic-vs-Connect parity — identical `success`, `unexpected_count`, AND `partial_unexpected_list` — by `tests/unit/test_custom_gx_parity.py` (VAL-CONNECT-08 / US-022-AC2 met for the custom surface).
- Cross-engine conformance harness shows identical suite verdicts across classic Spark / Sail / Databricks serverless.
- Zero observed silent false-negatives (`success=False`/`result={}` on a clean Connect DataFrame) after the routing change.

## Constraints and Assumptions

- Requires `tablespec[spark]` (a Spark or Sail session) at execution time; the suite artifact itself is produced without Spark.
- Native evaluators must stay in GX-semantic parity; adding a baseline expectation type requires adding a native evaluator (or it falls to the unsupported-passing stub).
- This feature applies the Runtime-Platform contract (ADR-010) to GX execution; it does not own the per-session capability probing or `_functions_for` dispatch seam.

## Dependencies

- **Other features**: FEAT-007 (Table Validation) — this feature is the Connect-safe execution layer beneath the validators; FEAT-005 (native profiler — shares `_functions_for`).
- **External services**: Great Expectations 1.x; PySpark (classic) or pysail (Connect test lane).
- **PRD requirements**: FR-7.7 (P0), FR-7.8 (P0), FR-20.4 (P0 platform contract).

## Out of Scope

- Per-session capability probing and engine-correct dispatch as a general mechanism (owned by the Runtime-Platform subsystem, ADR-010 / FR-20.x).
- The compile-time generation of the GX suite artifact (owned by FEAT-004 / FEAT-017).
- Pipeline blocking behavior and reporting (owned by FEAT-017 / `quality/executor.py`).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements (`FR-n`) are listed; single subsystem with explicit cross-subsystem note
- [x] Functional areas are subordinate parts of this one capability
- [x] Overview connects this feature to a specific PRD requirement
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is broken
- [x] Functional areas are mapped
- [x] Requirements are grouped by functional area
- [x] Domain objects that sound similar are explicitly separated (native executor vs GX add_spark engine)
- [x] Every functional requirement is testable
- [x] Acceptance criteria are defined in the user stories
- [x] Non-functional requirements have specific targets
- [x] Edge cases cover realistic failure scenarios
- [x] Success metrics are specific to this feature
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes things someone might reasonably assume are in scope
- [x] No implementation-prescription beyond citing the shipped evidence
- [x] Feature is consistent with governing PRD requirements
- [x] No `[NEEDS CLARIFICATION]` markers remain
