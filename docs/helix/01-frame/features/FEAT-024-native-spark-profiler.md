---
ddx:
  id: FEAT-024
---

# Feature Specification: FEAT-024 — Native Spark Profiler & Connect-Safe Runtime

**Feature ID**: FEAT-024
**Status**: Specified
**Priority**: P0
**Owner**: Data Platform
**Covered PRD Subsystem(s)**: Profiling Integration
**Covered PRD Requirements**: FR-5.1, FR-5.2, FR-5.3, FR-5.4
**Cross-Subsystem Rationale**: None — single subsystem. The Connect-safe runtime
substrate (engine-correct `functions` dispatch, serverless session acquisition)
is shared infrastructure that this feature establishes for profiling; the
validation subsystem's parallel Connect-safe execution (FR-7.7) is governed by
its own feature and reuses the same substrate without making this feature
cross-subsystem.

## Overview

This feature implements PRD FR-5.1 and FR-5.2: profile a DataFrame using only
standard Spark-SQL aggregations — no JVM, no Py4J, no Deequ — so profiling runs
first-class on Databricks serverless and Spark Connect, and feed those profiles
directly into Great Expectations suite composition. It replaces the PyDeequ
profiling path (see ADR-009), which silently assumes a classic `SparkContext`
that does not exist on Connect.

## Ideal Future State

A data engineer profiles any DataFrame — on classic Spark in CI, on Sail (local
Spark Connect) in the test lane, or on real Databricks serverless in production —
with one code path and identical results. They never install a JVM-bound
profiling extra, never see a silent `'Column' object is not callable` failure,
and the resulting profile drops straight into a GX suite at a chosen strictness.
Profiling "just works" on the platform the team is already migrating to, because
the profiler selects the engine-correct `functions` module from the DataFrame
itself rather than a process-global flag.

## Problem Statement

- **Current situation**: The legacy profiling path used PyDeequ
  (`profiling/deequ_mapper.py`), which is JVM/Py4J-bound and instantiates a Deequ
  analyzer against a classic `SparkContext`.
- **Pain points**: On Databricks serverless / Spark Connect there is no classic
  `SparkContext`, so the Deequ path is unavailable; PyDeequ also adds a heavy JVM
  dependency. When a classic JVM session and a Connect (Sail) session coexist in
  one process, `pyspark.sql.functions` resolves to CLASSIC `Column` objects that
  fail inside a Connect plan (`'Column' object is not callable`)
  (`src/tablespec/profiling/native_profiler.py:55-70`).
- **Desired outcome**: A single, dependency-light profiler that produces complete
  column profiles (completeness, cardinality, numeric stats, quantiles, string
  stats, sampled/low-cardinality values, detected pattern) and runs unchanged on
  classic Spark, Sail, and serverless — verified by the cross-engine matrix.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Native profiling | "Profile this DataFrame on serverless" | Compute all column statistics with standard Spark-SQL aggregations, no JVM/Deequ |
| Engine-correct dispatch | "Will my expressions run on Connect?" | Select the `functions` module from the DataFrame's own engine; degrade gracefully where DataFusion lacks an aggregate |
| Profile → GX | "Turn this profile into expectations" | Build GX expectations directly from a native profile at a configurable strictness, feeding suite composition (FR-4.3) |

## Requirements

### Functional Requirements by Area

#### Native profiling

PROF-01. `NativeSparkProfiler.profile(df)` SHALL compute, using only standard
Spark-SQL aggregations: row count, per-column completeness (non-null count),
approximate distinct cardinality, numeric min/max/mean/stddev/sum/skewness/
kurtosis, configurable approximate quantiles, string length stats, low-cardinality
value-with-counts, sampled values, and a detected value pattern
(`src/tablespec/profiling/native_profiler.py:121-475`).
PROF-02. The profiler SHALL NOT import or require PyDeequ or any JVM/Py4J
analyzer; its only Spark dependency is `pyspark`
(`src/tablespec/profiling/native_profiler.py:1-5`).
PROF-03. The profiler SHALL emit profiling metadata sufficient for downstream
nullable inference and expectation generation (sample size is a constructor
parameter; results carry per-column completeness used for nullable inference) —
satisfying FR-5.3 and FR-5.4.
PROF-04. Caching SHALL be best-effort: when `df.cache()` is unsupported (e.g.
serverless), the profiler SHALL proceed without caching rather than fail
(`src/tablespec/profiling/native_profiler.py:148-156`).

#### Engine-correct dispatch

DISP-01. The profiler SHALL select the `functions` module from the DataFrame's
own engine (classic vs. connect), not from a process-global flag, so column
expressions are session-correct when a classic and a Connect session coexist in
one process (`src/tablespec/profiling/native_profiler.py:55-78`).
DISP-02. Where a Connect backend's aggregate is missing or stricter than classic
Spark, the profiler SHALL degrade to an equivalent that the backend supports:
`percentile_approx` is emitted as one SCALAR percentile per probe (DataFusion/Sail
accepts scalar, not array), and `approx_count_distinct` falls back to exact
`count_distinct` for Float/Double columns
(`src/tablespec/profiling/native_profiler.py:173-182,241-247`).

#### Profile → GX

GX-01. `ProfileToGxMapper` SHALL build GX expectations directly from a
`DataFrameProfile` at a configurable strictness
(`src/tablespec/profiling/gx_expectation_builder.py:84`), and the result SHALL be
consumable by suite composition (FR-4.3).

### Non-Functional Requirements

- **Platform parity**: Identical profiling results across classic Spark, Sail
  (local Connect), and Databricks serverless on the cross-engine conformance
  harness (`tests/conformance/engines.py`).
- **Query efficiency**: Completeness + cardinality for all columns SHALL be
  computed in a single batched `df.select` pass (Phase 1), and per-column numeric
  stats + quantiles in one `df.select` each, not one job per statistic
  (`src/tablespec/profiling/native_profiler.py:175-263`).
- **Runtime/env**: SHALL run on the env-v3 / Python 3.12 model
  (`pyproject.toml:10` `requires-python = ">=3.12"`); no JVM is required on
  serverless/Connect.
- **Dependency weight**: SHALL add no user-facing extra beyond `pyspark`; the
  local Connect test lane (pysail) lives in the dev group only
  (`pyproject.toml:77-81`).
## User Stories

- [US-021 — Profile a DataFrame Natively on Spark Connect](../user-stories/US-021-profile-dataframe-natively-on-connect.md)

## Edge Cases and Error Handling

- **No classic SparkContext (serverless/Connect)**: Profiling proceeds via the
  Connect functions module; no `SparkContext` is assumed.
- **Coexisting classic + Connect sessions in one process**: `functions` module is
  chosen per-DataFrame, preventing cross-engine `Column` errors.
- **Float/Double cardinality on DataFusion**: Falls back to exact `count_distinct`.
- **`cache()` unsupported**: Profiling proceeds uncached.

## Success Metrics

- Native profiler produces a complete `DataFrameProfile` on all three engine
  tiers (classic Spark, Sail, Databricks serverless) with matching results.
- Zero references to PyDeequ remain in the default profiling path (the Deequ
  mapper file was removed; see ADR-009 / commit `ad5a4d9`).

## Constraints and Assumptions

- Assumes `pyspark>=` the version whose `pyspark.sql.connect.functions` exists;
  the profiler imports it lazily and falls back to classic functions when absent
  (`src/tablespec/profiling/native_profiler.py:72-78`).
- Real Databricks serverless (Python 3.12 / Spark Connect) is the production
  target; the Sail lane is a JVM-free local proxy for it (commit `55fc833`).

## Dependencies

- **Other features**: FEAT-004 (GX integration) consumes profiler output via
  `ProfileToGxMapper` for suite composition (FR-4.3); FEAT-005 (legacy
  profiling/UMF mapping) is the compatibility sibling.
- **External services**: `pyspark` (and its Spark Connect client) only; no Deequ.
- **PRD requirements**: FR-5.1 (P0), FR-5.2, FR-5.3, FR-5.4.

## Out of Scope

- Connect-safe GX *validation* execution (per-expectation native routing) — that
  is FR-7.7, governed by the validation feature, not here.
- The legacy `SparkToUmfMapper` / Deequ-style profile→UMF authoring path (FR-5.5)
  — retained under FEAT-005 as a compatibility path.
- Drift/baseline detection over profiles (FEAT-012).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements listed; single-subsystem, no
  cross-subsystem rationale needed
- [x] Functional areas are subordinate parts of one capability
- [x] Overview connects to specific PRD requirements (FR-5.1/FR-5.2)
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is broken
- [x] Every functional requirement is testable
- [x] Acceptance criteria live in US-021, not here (ADR-009)
- [x] Non-functional requirements have specific targets
- [x] Edge cases cover realistic failure scenarios
- [x] Dependencies reference real artifact IDs
- [x] No implementation-prescription beyond citing evidence of WHAT ships
- [x] Consistent with governing PRD requirements
