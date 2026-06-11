---
ddx:
  id: FEAT-005
---

# FEAT-005: Profiling Integration (Schema Mapping + Legacy Path)

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-005
**Owner**: Data Platform
**Cross-Subsystem Rationale**: None — single subsystem. Native Connect-safe profiling is governed by FEAT-024.
**Covered PRD Subsystem(s)**: Profiling Integration
**Covered PRD Requirements**: FR-5.3, FR-5.4, FR-5.5

## Description

Map a Spark DataFrame's *schema* into UMF, and retain the legacy Deequ-style
profile→UMF authoring path as a compatibility-only mechanism. The **default**
profiling mechanism — the native, JVM-free, Connect-safe Spark-SQL profiler that
replaced PyDeequ — is governed by **[FEAT-024](FEAT-024-native-spark-profiler.md)**
(PRD FR-5.1/FR-5.2). This feature now owns only the schema-mapping and
legacy-compatibility surfaces of the Profiling Integration subsystem.

## Components

### Types (`profiling/types.py`)
- `ColumnProfile` - Per-column profiling data (completeness, distinct count, statistics, quantiles, sampled values, pattern)
- `DataFrameProfile` - Aggregate profiling result (produced by the native profiler; see FEAT-024)

### Spark Schema Mapper (`profiling/spark_mapper.py`) [requires PySpark]
- `SparkToUmfMapper` - Convert a Spark DataFrame *schema* to UMF
- Maps Spark types to UMF types (`SPARK_TO_UMF_TYPE`); `SQL_TO_UMF_TYPE` maps warehouse type names (used by dbt-facing code)
- Preserves nullable and DecimalType precision/scale
- Produces UMF — the upstream source of truth that feeds GX/dbt/LDP generation (FR-5.4)

### Deequ Mapper — REMOVED (legacy)
- The PyDeequ-based `DeequToUmfMapper` (`profiling/deequ_mapper.py`) was **removed**
  in commit `ad5a4d9` ("Implement native profiler to replace pydeequ"). It assumed
  a classic `SparkContext` and is unavailable on Databricks serverless / Spark
  Connect (FR-5.5). Code that needs profile-derived expectations now uses the native
  profiler + `ProfileToGxMapper` (FEAT-024). Per FR-5.5, no Deequ path may be
  assumed available on Connect/serverless.
## User Stories

- [US-007 — Convert Profiling Results to UMF](../user-stories/US-007-convert-profiling-results-to-umf.md)

## Related

- **[FEAT-024](FEAT-024-native-spark-profiler.md)** — the native (no-JVM,
  Connect-safe) Spark-SQL profiler that is the **default** profiling mechanism
  (PRD FR-5.1/FR-5.2). The Deequ replacement is recorded in
  [ADR-009](../../02-design/adr/ADR-009-native-spark-profiler-over-pydeequ.md).
- Domain type inference (FEAT-013) can enrich profiling results with semantic types
- Quality baselines (FEAT-012) extend profiling with drift detection

## Source

- `src/tablespec/profiling/types.py`
- `src/tablespec/profiling/spark_mapper.py`
- (default profiler: `src/tablespec/profiling/native_profiler.py` — see FEAT-024)
