---
ddx:
  id: US-040
---

# US-040: Source Model and Ingestion Seam (Story Floor)

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: SRC-01, SRC-02, SRC-03, SRC-04, SRC-05
**PRD Requirements**: FR-21.1
**Priority**: P1
**Status**: Built (implementation shipped; this story backfills AC floor)

## Story

**As a** data engineer declaring how a table is acquired
**I want** a discriminated `source:` block on UMF and a single ingestion reader seam
**So that** delimited, parquet, JDBC, and JSON sources share one contract and
reader dispatch without embedding connectivity or reader options in callers.

## Context

SRC-01..05 are **shipped**. This story is frame-only backfill: stable
`US-040-ACn` IDs map to existing unit tests. Do not re-implement the seam.

Governing code:

- `src/tablespec/models/umf.py` — `DelimitedSource`, `ParquetSource`,
  `JsonSource`, `JdbcSource`, `file_format` alias
- `src/tablespec/ingestion/` — `get_reader`, kind-specific readers

## Walkthrough

1. Author declares `source: {kind: …}` (or legacy `file_format:` for delimited).
2. UMF model validates the discriminated union and rejects unknown kinds.
3. `get_reader(spec)` returns the reader for that kind.
4. Callers never open JDBC connections or hardcode Spark reader options outside
   the seam.

## Acceptance Criteria

- [x] **US-040-AC1 (discriminated source kinds)** — Given a UMF with
  `source.kind` of `delimited`, `parquet`, `json`, or `jdbc`, when the model
  validates, then the matching source type is accepted and an unknown kind is
  rejected.
  **Evidence**: `tests/unit/test_source_spec.py`
  (`TestDiscriminator`, `TestJdbcSource`, `TestFileFormatAlias`).
- [x] **US-040-AC2 (file_format alias)** — Given a UMF with only
  `file_format:` and no `source:`, when resolved, then a delimited source with
  the declared options is produced and a declared `source:` wins over
  `file_format`.
  **Evidence**: `tests/unit/test_source_spec.py` (`TestFileFormatAlias`).
- [x] **US-040-AC3 (reader seam dispatch)** — Given a valid source of each
  shipped kind, when `get_reader` is called, then the correct reader class is
  returned and an unknown kind raises `ValueError`.
  **Evidence**: `tests/unit/test_ingestion_package.py` (dispatch tests for
  delimited/parquet/json/jdbc/unknown).
- [x] **US-040-AC4 (round-trip stability)** — Given a UMF with a declared
  source, when serialized to YAML and reloaded, then the source block is
  preserved without loss for delimited, jdbc, and json shapes.
  **Evidence**: `tests/unit/test_source_spec.py` (`test_source_round_trips_*`,
  `test_legacy_umf_round_trip_is_byte_identical`).

## Edge Cases

- **plaintext JDBC password**: rejected by model (`extra=forbid` /
  secret-ref only) — see `TestJdbcSource.test_plaintext_password_raises`.
- **json projection must cover UMF columns**: validated in
  `test_json_source_projection_*`.

## Dependencies

- **Feature Spec**: FEAT-031
- **Decisions**: ADR-015
- **Work**: bead `tablespec-20513f4f` (story floor only)
