---
ddx:
  id: US-022
---

# US-022: Validate a Compiled Suite on Spark Connect Without Silent Failure

**Feature**: FEAT-025 — Connect-Safe GX Suite Validation
**Feature Requirements**: VAL-CONNECT-01, VAL-CONNECT-04, VAL-CONNECT-05, VAL-CONNECT-09
**PRD Requirements**: FR-7.7, FR-7.8 (with FR-20.4)
**Priority**: P0
**Status**: Approved (all acceptance criteria met; baseline + custom parity proven on the Sail Connect lane)

## Story

**As a** data-quality engineer running validation on Databricks serverless / Spark Connect
**I want** a compiled GX suite to return the same pass/fail verdict it returns on classic Spark
**So that** I can trust validation results on the platform production actually runs on, with no silent false-negatives masking dirty data or false-failing clean data.

## Context

Before this works, running a compiled GX suite on Spark Connect routes through GX's `add_spark` engine, whose classic `pyspark.sql.functions` assert a JVM `SparkContext` that does not exist on Connect; the assertion fails, the error is swallowed, and every data-scanning expectation returns `success=False` / `result={}` (`src/tablespec/validation/native_executor.py:1-31`). A clean table fails validation and a uniform false-negative can hide real problems. This story exercises FEAT-025's per-DataFrame routing (`gx_executor.py:211-239`) and the native DataFrame-API evaluators so the verdict is correct on Connect.

## Walkthrough

1. The engineer obtains a Spark Connect session (Sail locally, or Databricks serverless) and a DataFrame from it.
2. The engineer calls `GXSuiteExecutor(...).execute_suite(df, expectations)` with a compiled baseline suite.
3. The executor detects the DataFrame is a Connect DataFrame (its module starts with `pyspark.sql.connect`) and routes it to the native DataFrame-API path instead of GX `add_spark`.
4. Each expectation is evaluated with engine-correct functions selected from the DataFrame (`_functions_for`, bound `df[col]`), producing the same `ExpectationResult` shape as the classic path.
5. The engineer receives a `SuiteExecutionResult` whose per-expectation verdicts match what the same suite returns on a classic Spark DataFrame with the same data — clean data passes, dirty data fails.

## Acceptance Criteria

- [x] **US-022-AC1** — Given a Spark Connect DataFrame with clean data, when a compiled baseline suite is executed, then every expectation reports `success=True` (no `success=False`/`result={}` silent false-negative). *(`tests/unit/test_validation_connect_sail.py`)*
- [x] **US-022-AC2** — Given the same suite and data on a classic Spark DataFrame and on a Connect DataFrame, when both are executed, then the per-expectation pass/fail verdicts are identical. *(baseline: `test_validation_connect_sail.py`; the four custom expectations: `tests/unit/test_custom_gx_parity.py`, now also value-equal on `partial_unexpected_list`)*
- [x] **US-022-AC3** — Given a Connect DataFrame with a known violation (e.g. a null in a not-null column or an out-of-range value), when the suite is executed, then the violating expectation reports `success=False` with a populated `unexpected_count`. *(`test_validation_connect_sail.py`, `test_custom_gx_parity.py` dirty lanes)*
- [x] **US-022-AC4** — Given an expectation that GX would drop from its results (same-type collation or a raised metric), when the suite is executed, then the dropped `(type, column)` is re-evaluated standalone and never silently reported as a pass. *(`test_custom_gx_parity.py` exercises the custom collation path through `execute_suite`)*

## Edge Cases

- **Connect build lacks `try_to_timestamp(col, fmt)`**: date-format expectations fall back to a format-less parse behind a structural prefilter regex, gated on the per-session capability probe.
- **Numeric bound against a string-typed column**: the column is cast to double (NULL-on-failure) so the comparison is numeric, not lexicographic.
- **Expectation type with no native evaluator**: surfaced as a failed result with
  an explanatory `observed_value`; unsupported expectations fail closed instead
  of silently passing.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Clean data on Connect | US-022-AC1 | Sail Connect DataFrame, clean rows, baseline suite | `execute_suite(df, exps)` | All expectations `success=True` |
| Classic vs Connect parity | US-022-AC2 | Same suite + data on a classic Spark df and a Connect df | Execute both | Identical per-expectation verdicts |
| Dirty data on Connect | US-022-AC3 | Connect df with a null in a not-null column | `execute_suite(df, exps)` | Not-null expectation `success=False`, `unexpected_count>0` |
| Dropped result fails closed | US-022-AC4 | Two same-type custom expectations GX collates to one | `execute_suite(df, exps)` | Missing `(type,column)` re-evaluated standalone; never a silent pass |

## Dependencies

- **Stories**: US-009 (validate a DataFrame against UMF) — the validator that drives suite execution.
- **Feature Spec**: FEAT-025
- **Feature Requirements**: VAL-CONNECT-01, VAL-CONNECT-04, VAL-CONNECT-05, VAL-CONNECT-09
- **PRD Requirements**: FR-7.7, FR-7.8 (with FR-20.4)
- **External**: Great Expectations 1.x; pysail (Sail local Connect test lane) or Databricks serverless.

## Out of Scope

- Compile-time generation of the GX suite artifact (FEAT-004 / FEAT-017).
- Staged raw/ingested routing as a separate concern (covered by FR-7.8 within FEAT-025's executor but exercised by its own scenarios).
- Pipeline blocking behavior and report formatting (`quality/executor.py`, FEAT-017).

## Review Checklist

- [x] Stored as its own file `US-022-<slug>.md`
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent `FEAT-025` and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-022-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
