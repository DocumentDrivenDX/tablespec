---
ddx:
  id: data-quality-expectations
---

# Data Quality Expectations

## Overview and Scope

This document is the executable data-quality contract for the artifacts tablespec
**compiles** from one UMF and the runtime **backbone** executes. The medallion
layers map onto tablespec's pipeline as:

- **Bronze = RAW landing** — the all-`STRING` raw table (`+ _source_file +
  _load_ts`) produced by the compiled split ingest SQL. Raw-stage expectations run
  against the string DataFrame. *Forward note (ADR-015 / FEAT-031, planned):
  this all-STRING contract is the text-landed variant; typed sources
  (parquet, JDBC) will land native-typed raw, with raw-stage string checks
  replaced by schema-type expectations (FR-21.5). The Bronze sections below
  describe the text-landed regime.*
- **Silver = INGESTED (typed)** — the typed table produced by the compiled cast +
  MERGE/INSERT transform. Ingested-stage expectations run against the typed
  DataFrame.
- **Gold = derived** — the tables produced by the gold SQL plan / gold dbt DAG / LDP
  gold datasets (joins, survivorship, window aggregations, FK integrity).

The expectations here are **not hand-written for one dataset** — they are the GX
expectation *types* the `BaselineExpectationGenerator` emits from UMF metadata
(`src/tablespec/gx_baseline.py`), co-mingled into one compiled suite and **staged at
execute time** by `GXSuiteExecutor.execute_staged` (`validation/gx_executor.py:140`)
against the raw vs. typed DataFrame. Each expectation carries an explicit
`meta.validation_stage` (`raw`/`ingested`) or is classified by type. References:
[../01-frame/prd.md](../01-frame/prd.md) FR-4.x/FR-7.x and the
[data architecture](../02-design/architecture.md) layer model.

**Execution model that matters for every expectation below:** the suite runs
Connect-safely — Connect DataFrames route to the native DataFrame-API executor,
classic Spark to GX `add_spark` — because GX `add_spark` otherwise *silently* returns
`success=False`/`result={}` on Connect (ADR-011). A data-quality false-negative that
*looks* green is the worst failure mode this contract exists to prevent.

### Quality Dimensions

| Dimension | Definition | P0 Threshold | P1 Threshold | Enforcement |
|-----------|-----------|--------------|--------------|------------|
| Completeness | non-null on UMF `nullable: false` (per-LOB) columns | 0 nulls | n/a | Reject (raw + ingested) |
| Castability | raw STRING values cast losslessly to the UMF type | 0 uncastable | n/a | Reject at ingested stage |
| Format | dates/datetimes match the UMF strftime format; regex patterns match | 0 violations | best-effort | Reject (format), warn (advisory regex) |
| Uniqueness | no duplicate values on UMF PK / unique columns | 0 duplicates | n/a | Reject |
| Validity (value set / range) | values in the UMF allowed set / numeric range | 0 out-of-set | n/a | Reject; numeric value-sets staged to INGESTED (`1.5 != "1.50"`) |
| Consistency (cross-engine) | every engine reproduces the Spark-direct oracle byte-for-byte | 0 byte divergence | n/a | Conformance matrix blocks merge |
| Consistency (cross-column) | UMF column-pair rules (e.g. `start <= end`) hold | 0 violations | n/a | Reject |
| Timeliness / Freshness | **N/A** — tablespec is a compile-time library: it emits validation artifacts but runs no pipelines, so it cannot own arrival/staleness SLAs. Freshness is the consuming platform's runtime concern. Compiling freshness checks from UMF metadata (e.g. dbt `source freshness:`) would be new product scope requiring a PRD requirement first (decided 2026-06-10). | — | — | — |

### Test Framework and Tooling

- **Framework**: compiled **Great Expectations** suites (the per-table
  `validation/<t>.suite.json` artifact), executed by `GXSuiteExecutor` with native
  Connect-safe evaluators; cross-engine parity by the conformance harness
  (`tests/conformance/`).
- **Execution**: the runtime backbone (`e2e/backbone.py`) on DuckDB / classic Spark /
  Sail (Connect) / Databricks serverless; conformance matrix in CI.
- **Alerting**: structured failure output via `validation/report.py`
  (`unexpected_count`, observed value, partial unexpected list).
- **Remediation**: fail-closed — raw/ingested rejection stops stage advancement; the
  native executor fails closed on any unsupported/erroring expectation rather than
  returning a false pass.

### Testing Philosophy

**Exhaustive, not sampled.** Expectations are batch-evaluated over the whole
DataFrame in one pass (`execute_suite` / `execute_staged`). The native Connect
executor re-implements each type over the full DataFrame API (`native_executor.py`),
returning exact `unexpected_count` — so a "pass" means *all* rows passed, never a
sampled subset. Cross-engine parity is asserted **byte-for-byte** under one
canonicalizer (`canonical.to_json`), not statistically.

---

## Bronze Layer Expectations (RAW landing — all STRING)

Raw expectations validate the all-`STRING` landing table before any cast. They catch
structural/completeness problems early, on the raw string DataFrame.

### Completeness (Null Check) — raw stage

UMF `nullable: false` columns must be non-null even before typing. Emitted as
`expect_column_values_to_not_be_null` with `meta.validation_stage: raw`
(`gx_baseline.py:313-333`).

```text
# Raw stage — for each UMF column with nullable=false (per LOB):
EXPECT expect_column_values_to_not_be_null(column=<umf_col>)  [stage: raw]
```

**Severity**: Blocking (P0). **Threshold**: 0 nulls. **Action on Failure**: reject the
raw batch; do not advance to the cast/ingest transform.

### Length Bounds — raw stage

VARCHAR/CHAR width is enforced on the raw string before truncation could occur,
via `expect_column_value_lengths_to_be_between` (`gx_baseline.py:350`).

```text
EXPECT expect_column_value_lengths_to_be_between(column=<umf_col>, min=..., max=<umf_length>)  [stage: raw]
```

**Severity**: Blocking for declared-width columns. **Action on Failure**: reject;
investigate source truncation/over-width.

### Format (Date/Datetime + Regex) — raw stage

Date/datetime columns must match the UMF strftime format **as strings** (dates are
`yyyyMMdd` strings per ADR-001), via `expect_column_values_to_match_strftime_format`
(`gx_baseline.py:383-436`). Advisory `expect_column_values_to_match_regex` patterns
(`gx_baseline.py:640`) run here too.

```text
EXPECT expect_column_values_to_match_strftime_format(column=<date_col>, format=<umf_format>)  [stage: raw]
EXPECT expect_column_values_to_match_regex(column=<col>, regex=<umf_pattern>)                 [stage: raw, advisory]
```

**Severity**: Blocking (format), Warning (advisory regex). **Action on Failure**:
reject on format mismatch; log/audit on advisory regex.

---

## Silver Layer Expectations (INGESTED — typed)

Ingested expectations run against the **typed** DataFrame after the compiled cast.
They enforce the contract that the raw→typed transform was lossless and that typed
constraints hold.

### Castability — ingested stage

Every raw STRING value must cast losslessly to the UMF type, via
`expect_column_values_to_cast_to_type` (`gx_baseline.py:365-471`). This is the core
"did the cast lose data?" guard.

```text
EXPECT expect_column_values_to_cast_to_type(column=<umf_col>, type=<umf_type>)  [stage: ingested]
```

**Severity**: Blocking (P0). **Threshold**: 0 uncastable. **Action on Failure**: reject
the ingested batch; the cast is the contract — an uncastable value means the source
violated the declared type.

### Uniqueness (PK / unique columns) — ingested stage

UMF primary-key / unique columns must have no duplicates after dedup, via
`expect_column_values_to_be_unique` (`gx_baseline.py:530`).

```text
EXPECT expect_column_values_to_be_unique(column=<pk_col>)  [stage: ingested]
```

**Severity**: Blocking. **Threshold**: 0 duplicates. **Action on Failure**: reject;
review the dedup window (`dedup_window_sql` order_by + tie-break — see the residual
risk in the phase4 eval).

### Validity — value set + numeric range — ingested stage

Allowed-value sets via `expect_column_values_to_be_in_set` and numeric ranges via
`expect_column_values_to_be_between` (`gx_baseline.py:547,602`). **Numeric value-sets
are deliberately staged to INGESTED** (`gx_baseline.py:596-599`) because on the raw
all-string stage `1.5 != "1.50"`.

```text
EXPECT expect_column_values_to_be_in_set(column=<col>, value_set=<umf_values>)  [stage: ingested for numeric, raw for string]
EXPECT expect_column_values_to_be_between(column=<numeric_col>, min=..., max=...) [stage: ingested]
```

**Severity**: Blocking (P0). **Action on Failure**: reject; out-of-set/out-of-range is
a source-data violation of the UMF contract.

### Completeness (post-cast) — ingested stage

`nullable: false` columns are re-checked on the typed DataFrame
(`expect_column_values_to_not_be_null`, ingested stage) to catch nulls introduced by
a failed/silent cast-to-null.

```text
EXPECT expect_column_values_to_not_be_null(column=<umf_col>)  [stage: ingested]
```

**Severity**: Blocking (P0). **Action on Failure**: reject; a non-null raw value that
became null after cast indicates a lossy cast.

---

## Gold Layer Expectations (derived)

Gold expectations cover the derived tables emitted by the gold SQL plan, the gold
dbt DAG, and the LDP gold datasets. These are validated primarily by the conformance
harness (executed cross-engine against the Spark-direct oracle), not only as GX
suites.

### FK Integrity (no orphans)

Derived gold rows must reference existing parents — the orphan-FK relationship is
**executed** (not just generated) on DuckDB + Spark.

```text
-- No gold row references a non-existent parent key.
EXPECT NOT EXISTS (
  SELECT 1 FROM <gold_child> c
  WHERE NOT EXISTS (SELECT 1 FROM <parent> p WHERE p.<key> = c.<key>)
);
```

**Severity**: Blocking (P0). **Evidence**: `tests/conformance/test_fk_orphan_enforcement.py`;
the `gold_fk_integrity` conformance case (executed on duckdb + spark).
**Action on Failure**: reject the gold batch; investigate the join/source set.

### Survivorship / Aggregate Determinism

Survivorship (priority COALESCE, GREATEST-across-sources with default) and window
aggregations must be **deterministic and engine-identical**. Non-deterministic
ORDER BY in first-record/window logic is a defect, fixed and pinned in conformance.

```text
-- The gold survivorship/aggregation result is byte-for-byte identical across engines.
EXPECT canonical(gold_result on duckdb) == canonical(gold_result on spark) == oracle
```

**Severity**: Blocking (P0). **Evidence**: `gold_survivorship_*`, `gold_window_aggregation`,
`gold_first_record`, `gold_join`, `gold_unpivot`, `gold_pivot` conformance cases
(see [gold-conformance-plan](gold-conformance-plan.md)). **Action on Failure**: reject;
fix the generator; regenerate goldens via `--update-golden`.

---

## Cross-Layer Contracts

### Layer-to-Layer Validation

| Contract | Assertion | If Violated | Severity |
|----------|-----------|-------------|----------|
| RAW → INGESTED castability | every raw STRING casts losslessly to its UMF type | reject ingested; source violates declared type | Blocking |
| RAW → INGESTED completeness | non-null raw value stays non-null after cast | reject; lossy cast detected | Blocking |
| Staging correctness | numeric value-sets/ranges evaluate on the TYPED DataFrame, not the raw string | mis-staged check silently passes/fails (`1.5 != "1.50"`) | Blocking |
| INGESTED → GOLD FK integrity | gold rows reference existing parents | reject gold; orphan FK | Blocking |
| Cross-engine determinism | every engine reproduces the oracle byte-for-byte | block merge; conformance matrix red | Blocking |
| Runtime ↔ UMF zero-drift | the suite the runtime executes is the COMMITTED `validation/<t>.suite.json`, never re-derived from UMF | drift between schema truth and what runs | Blocking |

### Connect-Safety Contract (spans every expectation)

```text
-- The same compiled suite must yield IDENTICAL verdicts on classic Spark and on
-- Spark Connect / Databricks serverless. GX add_spark is classic-only; Connect
-- DataFrames route to the native executor (ADR-011).
EXPECT verdict(suite on classic Spark) == verdict(suite on Spark Connect)
EXPECT no expectation silently returns success=False/result={} on Connect
```

**Severity**: Blocking (P0). **Evidence**: `tests/unit/test_validation_connect_sail.py`
runs every supported type against clean (`success=True`) and dirty (`success=False`,
exact `unexpected_count`) data on a real Sail Connect session; the same operations run
on real Databricks serverless. **Action on Failure**: this is the canonical hazard —
a uniform false-negative would mask all dirty data; the native router exists to
prevent it.

---

## Failure Handling and SLA

### Alert and Escalation Policy

| Expectation class | Severity | Detection | Escalation | Action |
|-------------------|----------|-----------|-----------|--------|
| Raw completeness / length / format | Blocking | at raw-stage validation | pipeline halt | Reject raw batch; do not cast |
| Ingested castability | Blocking | at ingested-stage validation | pipeline halt | Reject; source violates the type contract |
| Ingested uniqueness / value-set / range | Blocking | at ingested-stage validation | pipeline halt | Reject; review dedup / source values |
| Gold FK integrity / determinism | Blocking | conformance matrix | block merge | Reject gold; fix generator; regenerate goldens |
| Connect false-negative (any type) | Blocking | Sail lane + serverless | block merge | Routing/native-executor defect — top priority |
| Advisory regex | Warning | at raw-stage validation | log/audit | Continue; flag low-confidence |

### Failure Recovery

**On Blocking Failure**:
1. Stop the stage (no advancement raw→ingested→gold).
2. Surface structured failure context via `validation/report.py` (type, column,
   `unexpected_count`, observed value, partial unexpected list).
3. Do not auto-retry; require a fix to the source data or the UMF, then recompile.
4. Because the runtime executes only the committed suite, the fix is a reviewable
   UMF/artifact diff (zero-drift), not a runtime patch.

**On Warning Failure** (advisory regex): log, flag low-confidence, continue.

### SLA Target

- **Detection**: per-stage, synchronous (validation gates each stage before
  advancement).
- **False Positive Rate**: minimized by staging numeric checks to the typed
  DataFrame and by the native executor returning exact counts (no sampling noise).
- **False Negative Rate**: the explicit target is **zero silent false-negatives on
  Connect** — the entire native-routing design exists to hold this line.

---

## Review Checklist

- [x] **Overview and Scope** maps RAW/INGESTED/GOLD to the medallion layers and the quality dimensions in scope
- [x] **Bronze (RAW) Expectations** validate completeness, length, and format on the all-STRING landing table
- [x] **Silver (INGESTED) Expectations** enforce castability, uniqueness, value-set/range, and post-cast completeness on the typed table
- [x] **Gold Expectations** guarantee FK integrity and cross-engine deterministic derivation
- [x] **Expectations are executable** — concrete GX expectation types + conformance assertions, not prose
- [x] **Each expectation traces back** to UMF metadata and a PRD requirement (FR-4.x/FR-7.x)
- [x] **Failure modes are explicit** — reject (fail-closed), warn (advisory), with stage-by-stage actions
- [x] **SLA per layer** — synchronous per-stage gating; zero-silent-false-negative target on Connect; timeliness/freshness SLAs explicitly N/A for a compile-time library (see Quality Dimensions)
- [x] **Sampling vs exhaustive** — exhaustive batch evaluation with exact counts; byte-for-byte cross-engine parity
- [x] **Cross-layer contracts** — RAW→INGESTED castability/completeness, staging correctness, INGESTED→GOLD FK, cross-engine determinism, runtime↔UMF zero-drift
- [x] **Alert routing and escalation** defined per expectation class
- [x] **No `[TBD]` / `[TODO]` markers remain**
- [x] **At least one expectation per quality dimension**
- [x] **P0 requirements have layered checks** (raw completeness, ingested castability/uniqueness, gold determinism, Connect-safety)
- [x] **Terminology aligns** with the tablespec pipeline (raw/ingested/gold stages, compiled GX suite, native Connect executor, conformance oracle)
