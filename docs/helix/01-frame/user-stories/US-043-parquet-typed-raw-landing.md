---
ddx:
  id: US-043
---

# US-043: Parquet Typed-Raw Landing (Story Floor)

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: PARQ-01, PARQ-02, PARQ-03
**PRD Requirements**: FR-21.3
**Priority**: P1
**Status**: Built (implementation shipped; this story backfills AC floor)

## Story

**As a** data engineer landing parquet files
**I want** native-typed raw and identity/safe-narrowing casts
**So that** typed DATE/TIMESTAMP columns are never routed through string
format parsers that silently NULL values.

## Context

PARQ typed-raw path is **shipped** (`casting_utils` typed_raw + ingest
generator). Implement child `tablespec-502c6126` is closed. This story only
records AC evidence.

## Walkthrough

1. UMF declares `source: {kind: parquet}`.
2. Raw lands with native parquet types (not all-STRING).
3. `cast_column_sql(..., source_kind="parquet")` emits identity/safe-narrowing
   casts for DATE/TIMESTAMP.

## Acceptance Criteria

- [x] **US-043-AC1 (PARQ-01 native typed raw)** — Given a parquet source,
  when ingest SQL is generated, then the path is native-typed (not forced
  all-STRING raw).
  **Evidence**: ingest generator coverage for parquet native typed;
  `tests/unit/test_casting_utils.py` typed_raw matrix.
- [x] **US-043-AC2 (PARQ-02 identity/safe-narrowing DATE)** — Given a
  DATE column from parquet, when `cast_column_sql` runs with
  `source_kind="parquet"`, then the cast is safe identity-style
  (`cast(... as date)` / `try_cast`) rather than string format parse.
  **Evidence**: `tests/unit/test_casting_utils.py`
  (`test_typed_raw_date_uses_safe_cast`).
- [x] **US-043-AC3 (PARQ-02 TIMESTAMP)** — Given a TIMESTAMP column from
  parquet, when cast SQL is built with typed_raw, then timestamp safe cast is
  emitted.
  **Evidence**: `tests/unit/test_casting_utils.py`
  (`test_typed_raw_timestamp_uses_safe_cast`).
- [x] **US-043-AC4 (negative: string formats not applied on typed raw)** —
  Given typed raw, when building casts, then registered string date formats
  are not the selected path for parquet/json/jdbc kinds.
  **Evidence**: same typed_raw matrix parametrizes `parquet` (and peers)
  away from string `try_to_timestamp` / strptime paths.

## Edge Cases

- ADR-001 yyyymmdd-string convention applies only to all-STRING (delimited)
  raw, not parquet (PARQ-03) — covered by format registration tests for
  delimited path separately.

## Dependencies

- **Feature Spec**: FEAT-031
- **Work**: bead `tablespec-e9c21567` (story floor only)
