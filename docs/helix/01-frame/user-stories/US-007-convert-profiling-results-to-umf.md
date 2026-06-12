---
ddx:
  id: US-007
---

# US-007: Convert Profiling Results to UMF

**Feature**: FEAT-005 — Profiling Integration
**PRD Requirements**: FR-5.3, FR-5.4, FR-5.5
**Priority**: P1
**Status**: Approved

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

## Context

This story preserves the native, Connect-safe Spark-SQL profiling path that replaced the legacy Deequ mapper. It feeds the derived profile into downstream UMF enrichment without assuming a classic SparkContext.

## Walkthrough

1. User creates a Spark session and loads a small DataFrame with numeric and string columns.
2. System profiles the DataFrame using the engine-correct functions module for that session.
3. User passes the resulting profile into the UMF mapper or GX expectation builder.
4. System returns the enriched profile and the derived expectations without PyDeequ or classic-session assumptions.

## Acceptance Criteria

- [ ] **US-007-AC1** — Given a Spark DataFrame with `member_id=1`, `age=34`, and `state="CA"`, when the native profiling flow runs, then `SparkToUmfMapper` converts a Spark DataFrame schema to a UMF object, mapping Spark types to UMF types and preserving nullable and DecimalType precision/scale (requires `tablespec[spark]`)
- [ ] **US-007-AC2** — Given a Spark DataFrame with `member_id=1`, `age=34`, and `state="CA"`, when the native profiling flow runs, then The native Spark-SQL profiler enriches an existing UMF schema with profiling results — completeness, distinct counts, min/max/mean/stddev statistics, and profiling metadata (tool, version, timestamp) — without importing PyDeequ and without assuming a classic `SparkContext` (FEAT-024 / US-021)
- [ ] **US-007-AC3** — Given a Spark DataFrame with `member_id=1`, `age=34`, and `state="CA"`, when the native profiling flow runs, then Nullable fields are updated based on completeness metrics (columns with 100% completeness become non-nullable)
- [ ] **US-007-AC4** — Given a Spark DataFrame with `member_id=1`, `age=34`, and `state="CA"`, when the native profiling flow runs, then `ColumnProfile` and `DataFrameProfile` types provide a consistent structure for profiling data regardless of the source tool

## Edge Cases

- **classic Spark may coexist with Connect in one process**: classic Spark may coexist with Connect in one process
- **cache() may be unsupported on serverless**: cache() may be unsupported on serverless
- **Float/Double cardinality must stay exact on Sail**: Float/Double cardinality must stay exact on Sail

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Convert schema into UMF | US-007-AC1 | Spark DataFrame with member_id=1, age=34, state="CA" | the native profiling flow runs | `SparkToUmfMapper` converts a Spark DataFrame schema to a UMF object, mapping Spark types to UMF types and preserving nullable and DecimalType precision/scale (requires `tablespec[spark]`) |
| Profile with Connect-safe functions | US-007-AC2 | Connect DataFrame with member_id=1, age=34, state="CA" | the native profiling flow runs | The native Spark-SQL profiler enriches an existing UMF schema with profiling results — completeness, distinct counts, min/max/mean/stddev statistics, and profiling metadata (tool, version, timestamp) — without importing PyDeequ and without assuming a classic `SparkContext` (FEAT-024 / US-021) |
| Update nullability from completeness | US-007-AC3 | DataFrame with member_id=1, age=34, state="CA" and age completeness 100% | the native profiling flow runs | Nullable fields are updated based on completeness metrics (columns with 100% completeness become non-nullable) |
| Return stable profile types | US-007-AC4 | DataFrameProfile for member_id=1, age=34, state="CA" | the native profiling flow runs | `ColumnProfile` and `DataFrameProfile` types provide a consistent structure for profiling data regardless of the source tool |

## Dependencies

- **Stories**: See the parent feature-slice stories already listed in the feature spec.
- **Feature Spec**: FEAT-005 — Profiling Integration
- **Feature Requirements**: PROF-01, PROF-02, PROF-04
- **PRD Requirements**: FR-5.3, FR-5.4, FR-5.5
- **External**: Spark / Connect / docs tooling / fixture data as implied by the story slice and feature spec.

## Out of Scope

- legacy PyDeequ profiling
- Connect validation routing beyond the profiler slice

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
