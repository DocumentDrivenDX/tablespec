---
ddx:
  id: ADR-009
---

# ADR-009: Native Spark-SQL Profiler over PyDeequ (Connect-Safe Runtime)

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Data Platform | FEAT-024, FEAT-005, US-021, FR-5.1, FR-5.5 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The PyDeequ profiling path (`profiling/deequ_mapper.py`) is JVM/Py4J-bound and instantiates analyzers against a classic `SparkContext`, which does not exist on Databricks serverless / Spark Connect, so profiling is unavailable on the platforms teams are migrating to. |
| Current State | Native profiler shipped and Deequ mapper removed in commit `ad5a4d9` ("Implement native profiler to replace pydeequ"); Sail (local Spark Connect) test lane and Connect-compat fixes added in commit `55fc833`. |
| Requirements | FR-5.1 (native profiler is the default, Connect-safe), FR-5.5 (Deequ may not be assumed on Connect/serverless), multi-engine parity (classic Spark / Sail / serverless), env-v3 / Python 3.12. |
| Decision Drivers | Databricks serverless + Spark Connect have made the JVM-coupled runtime untenable; a process-global engine flag is unsafe when a classic and a Connect session coexist; profiling must feed GX suite composition directly. |

## Decision

We will **replace PyDeequ with a native Spark-SQL profiler** (`NativeSparkProfiler`)
that computes all column statistics using only standard Spark-SQL aggregations
(min, max, avg, stddev, sum, skewness, kurtosis, `approx_count_distinct`,
`percentile_approx`), requires only `pyspark` (no JVM/Py4J/Deequ), and selects the
engine-correct `functions` module **from each DataFrame's own engine** rather than
a process-global flag. We will **remove** `DeequToUmfMapper`, retaining
`SparkToUmfMapper` only as a legacy schema-mapping path (FEAT-005). The native
profile feeds GX expectations via `ProfileToGxMapper`.

**Key Points**: No JVM / no Deequ — runs on serverless & Connect | Per-DataFrame
`functions` dispatch (`native_profiler.py:55-78`) | DataFusion-safe degradations
(scalar `percentile_approx`; exact `count_distinct` for Float/Double) | Verified on
the classic-Spark / Sail / Databricks-serverless matrix.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep PyDeequ | Mature analyzers; existing code | JVM/Py4J-bound; unavailable on serverless/Connect; heavy dependency | Rejected: structurally incompatible with the serverless/Connect runtime (FR-5.1/FR-5.5). |
| Native profiler with a process-global classic/connect flag | Simpler dispatch | Wrong when a classic and a Connect (Sail) session coexist in one process → `'Column' object is not callable` | Rejected: proven incorrect in the local Connect lane (`native_profiler.py:55-70`). |
| **Native Spark-SQL profiler, per-DataFrame dispatch** | No JVM/Deequ; Connect & serverless safe; one code path; feeds GX directly; DataFusion-safe degradations | Must hand-roll stats and handle backend aggregate gaps | **Selected: only option that runs identically on classic Spark, Sail, and serverless while staying dependency-light.** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Profiling runs on Databricks serverless / Spark Connect; no JVM dependency; single profiling code path; native profiles feed GX suite composition (FR-4.3); cross-engine parity is testable on the conformance matrix. |
| Negative | Statistics are hand-rolled; backend-specific aggregate gaps (e.g. DataFusion) require explicit degradations; some Deequ analyzers have no native equivalent yet. |
| Neutral | `SparkToUmfMapper` remains as a legacy schema-mapping path; the Deequ extra is dropped from the dependency surface. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| A backend rejects an aggregate (e.g. DataFusion `approx_distinct` on Float64) | M | M | Type-aware fallback to exact `count_distinct`; scalar-per-probe `percentile_approx` (`native_profiler.py:173-182,241-247`). |
| Hand-rolled stats drift from Deequ semantics | L | M | Cross-engine conformance harness asserts parity across classic Spark / Sail / serverless. |
| `pyspark.sql.connect.functions` absent on an older pyspark | L | L | Lazy import with classic fallback (`native_profiler.py:72-78`). |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Native profiler returns a complete `DataFrameProfile` with matching results across classic Spark, Sail, and Databricks serverless | A new engine tier is added, or a backend changes an aggregate's behavior |
| Zero PyDeequ references in the default profiling path | Any proposal to reintroduce a JVM-bound profiler |

## Supersession

- **Supersedes**: None (PyDeequ path was never a formal ADR; this records its removal).
- **Superseded by**: None

## Concern Impact

- **Concern selection**: None.
- **Practice override**: None — this ADR does not override a library concern practice.

## References

- PRD Subsystem: Profiling Integration — FR-5.1, FR-5.5
- FEAT-024 (Native Spark Profiler & Connect-Safe Runtime); FEAT-005 (legacy schema-mapping path)
- US-021 (Profile a DataFrame natively on Spark Connect)
- Evidence: `src/tablespec/profiling/native_profiler.py:1-78,121-263`; commit `ad5a4d9` (Deequ removal), commit `55fc833` (Sail lane + Connect-compat); `src/tablespec/session.py`, `src/tablespec/spark_factory.py:203-225` (serverless/Connect session acquisition); `pyproject.toml:10,77-81`.
- Related: ADR-003 (optional PySpark dependency).
