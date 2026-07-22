---
ddx:
  id: US-050
---

# US-050: JSON/JSONL Source Kind (FR-21.7)

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: JSON-01, JSON-02, JSON-03
**PRD Requirements**: FR-21.7
**Priority**: P1
**Status**: Built (model/reader + backbone load path shipped)

## Story

**As a** data engineer landing JSON or JSONL files
**I want** a `json` source kind with flat projection and typed-raw landing
**So that** nested payloads can be projected to UMF columns without recursive
flattening and without the backbone failing closed on `kind=json`.

## Context

### Shipped before this residual

- **Model**: `JsonSource` + `JsonProjection` in `models/umf.py`
- **Reader**: `JsonReader` in `tablespec.ingestion` (Spark `read.json` +
  select/alias projection)
- **Typed-raw casts**: `source_kind` includes `json` in
  `casting_utils` (same identity/safe-narrowing as parquet)
- **Conformance**: `tests/conformance/test_json_tier.py` + engine JSON loaders

### Residual closed by implement bead

- **Backbone**: `tablespec.e2e.backbone._declared_source` and Spark/DuckDB
  `_load_raw` accept `kind=json` (previously raised
  `NotImplementedError` for non-delimited/parquet)

## Walkthrough

1. Author declares `source: {kind: json, projection: [...], multi_line: …}`.
2. Model validates projection covers columns exactly once.
3. Compile produces typed-raw ingest artifacts.
4. Backbone / conformance engines load JSONL/JSON via projection and run
   staged validation.

## Acceptance Criteria

- [x] **US-050-AC1 (model + projection)** — Given a UMF with
  `source.kind: json` and a flat projection, when validated, then the model
  accepts top-level and dotted paths and rejects incomplete or unknown
  projection columns.
  **Evidence**: `tests/unit/test_source_spec.py` (`test_json_source_*`).
- [x] **US-050-AC2 (reader)** — Given a `JsonSource`, when `get_reader`
  dispatches, then `JsonReader` is selected and reads with projection.
  **Evidence**: `tests/unit/test_ingestion_package.py`
  (`test_json_dispatches_to_json_reader`); conformance JSON tier.
- [x] **US-050-AC3 (backbone accepts json)** — Given a UMF snapshot with
  `source.kind: json`, when the backbone resolves the declared source, then a
  `JsonSource` is returned and raw loading does not fail closed for that kind.
  **Evidence**: `tests/unit/test_ingestion_package.py`
  (`test_declared_json_source_is_accepted`); Spark/DuckDB paths in
  `src/tablespec/e2e/backbone.py`.
- [x] **US-050-AC4 (typed-raw parity with parquet)** — Given json source
  kind, when cast SQL is built, then DATE/TIMESTAMP use the typed_raw safe
  cast path (not string format parse).
  **Evidence**: `tests/unit/test_casting_utils.py` typed_raw matrix includes
  `json` alongside `parquet`.

## Edge Cases

- **Absent projection path in data**: reader/engine fails closed naming the
  path (JSON-03) — see projection path validation in `JsonReader`.
- **Demo residual**: SEC 10-K facts table (US-045-AC3) may still depend on
  workspace notebooks for end-to-end demo evidence.

## Dependencies

- **Feature Spec**: FEAT-031
- **PRD**: FR-21.7
- **Work**: story bead `tablespec-557f8a24`; implement bead
  `tablespec-9f98cf03`
