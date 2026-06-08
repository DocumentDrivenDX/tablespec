---
ddx:
  id: US-021
---

# US-021: Profile a DataFrame Natively on Spark Connect

**Feature**: FEAT-024 — Native Spark Profiler & Connect-Safe Runtime
**Feature Requirements**: PROF-01, PROF-02, PROF-04, DISP-01, DISP-02, GX-01
**PRD Requirements**: FR-5.1, FR-5.2
**Priority**: P0
**Status**: Implemented

## Story

**As a** data engineer on a Databricks serverless / Spark Connect platform
**I want** to profile a DataFrame using only standard Spark-SQL aggregations,
selecting the engine-correct functions for whatever session I have
**So that** I get complete, identical column profiles on classic Spark, Sail, and
serverless without installing a JVM/Deequ stack or hitting silent Connect failures

## Context

On Databricks serverless there is no classic `SparkContext`, so the old PyDeequ
profiler is simply unavailable, and `pyspark.sql.functions` can resolve to classic
`Column` objects that fail inside a Connect plan when a classic and a Connect
session coexist in one process (`src/tablespec/profiling/native_profiler.py:55-70`).
This story exercises the native profiler's core path (PROF-01/02) and its
engine-correct dispatch (DISP-01/02) so the engineer's profile feeds straight into
GX expectation generation (GX-01).

## Walkthrough

1. The engineer constructs `NativeSparkProfiler(spark)` with a serverless/Connect
   session.
2. They call `profiler.profile(df)`.
3. The profiler selects the `functions` module from the DataFrame's own engine
   (connect vs. classic), attempts a best-effort `cache()`, and proceeds without
   caching if the engine rejects it.
4. The profiler runs one batched completeness+cardinality pass, then per-column
   numeric/string passes — using scalar `percentile_approx` and Float/Double-safe
   distinct counts so DataFusion (Sail) accepts every expression.
5. The system returns a `DataFrameProfile` whose per-column profiles carry
   completeness, cardinality, numeric stats, quantiles, string stats, sampled
   values, and a detected pattern.
6. The engineer passes the profile to `ProfileToGxMapper(...).` and receives GX
   expectations at the chosen strictness — the outcome.

## Acceptance Criteria

- [ ] **US-021-AC1** — Given a Spark Connect (or serverless) DataFrame, when
  `NativeSparkProfiler.profile(df)` is called, then it returns a complete
  `DataFrameProfile` without importing PyDeequ and without assuming a classic
  `SparkContext`.
- [ ] **US-021-AC2** — Given a classic JVM session and a Connect (Sail) session
  coexisting in one process, when the same profiler profiles a Connect DataFrame,
  then column expressions execute against the Connect engine (no
  `'Column' object is not callable`) because the functions module is chosen from
  the DataFrame's own engine.
- [ ] **US-021-AC3** — Given a Float/Double column on DataFusion (Sail), when
  cardinality is computed, then the profiler uses exact `count_distinct` (not
  `approx_count_distinct`) and succeeds.
- [ ] **US-021-AC4** — Given a backend whose `cache()` is unsupported
  (serverless), when profiling runs, then it completes without caching rather than
  raising.
- [ ] **US-021-AC5** — Given a returned `DataFrameProfile`, when it is passed to
  `ProfileToGxMapper`, then GX expectations are produced at the configured
  strictness, consumable by suite composition (FR-4.3).

## Edge Cases

- **No `pyspark.sql.connect.functions` available**: profiler falls back to classic
  functions (`native_profiler.py:72-78`).
- **`percentile_approx` with an array of probes on DataFusion**: avoided — one
  scalar percentile is emitted per probe inside the same `df.select`.
- **Empty DataFrame**: row count is 0; per-column stats degrade to null/empty
  rather than erroring.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Connect profile | US-021-AC1 | Sail/serverless `df`, no classic SparkContext | `profile(df)` | Complete `DataFrameProfile`, no Deequ import |
| Coexisting sessions | US-021-AC2 | classic + Sail sessions in one process; Connect `df` | `profile(df)` | Runs on Connect engine, no `Column` error |
| Float cardinality | US-021-AC3 | DataFusion `df` with a Double column | profile cardinality | exact `count_distinct` used, succeeds |
| Uncacheable engine | US-021-AC4 | serverless `df`, `cache()` unsupported | `profile(df)` | completes uncached |
| Profile → GX | US-021-AC5 | a `DataFrameProfile` | `ProfileToGxMapper(...).` build | GX expectations at chosen strictness |

## Dependencies

- **Stories**: US-005 (generate GX baseline from UMF) — downstream suite composition consumes these expectations.
- **Feature Spec**: FEAT-024
- **Feature Requirements**: PROF-01, PROF-02, PROF-04, DISP-01, DISP-02, GX-01
- **PRD Requirements**: FR-5.1, FR-5.2
- **External**: `pyspark` (+ its Spark Connect client); pysail for the local Connect test lane (dev group).

## Out of Scope

- Connect-safe GX *validation* execution / per-expectation routing (FR-7.7).
- Legacy `SparkToUmfMapper` schema-mapping and the removed Deequ path (FEAT-005).
