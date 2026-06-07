---
ddx:
  id: US-007
---

# US-007: Convert Profiling Results to UMF

**Feature**: FEAT-005 — Profiling Integration
**PRD Requirements**: FR-5.3, FR-5.4, FR-5.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer running Spark profiling jobs,
**I want** convert profiling results into UMF format,
**So that** column statistics, completeness metrics, and inferred types enrich the UMF schema and feed into downstream validation and documentation workflows.

> **Profiling source (reconciled 2026-06-06):** Profiles are now produced by the
> native, Connect-safe Spark-SQL profiler (FEAT-024 / ADR-009), which is the
> default profiling mechanism (FR-5.1/FR-5.2). The legacy PyDeequ `DeequToUmfMapper`
> was **removed** in commit `ad5a4d9` and is no longer part of this story; see
> FEAT-005 ("Deequ Mapper — REMOVED") and FR-5.5. The native-profiler path is
> covered end-to-end by US-021.

## Acceptance Criteria

- [x] `SparkToUmfMapper` converts a Spark DataFrame schema to a UMF object, mapping Spark types to UMF types and preserving nullable and DecimalType precision/scale (requires `tablespec[spark]`)
- [x] The native Spark-SQL profiler enriches an existing UMF schema with profiling results — completeness, distinct counts, min/max/mean/stddev statistics, and profiling metadata (tool, version, timestamp) — without importing PyDeequ and without assuming a classic `SparkContext` (FEAT-024 / US-021)
- [x] Nullable fields are updated based on completeness metrics (columns with 100% completeness become non-nullable)
- [x] `ColumnProfile` and `DataFrameProfile` types provide a consistent structure for profiling data regardless of the source tool
