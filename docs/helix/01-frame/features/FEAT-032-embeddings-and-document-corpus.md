---
ddx:
  id: FEAT-032
---

# Feature Specification: FEAT-032 — Embeddings and Document Corpus

**Feature ID**: FEAT-032
**Status**: Approved
**Priority**: P1
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: UMF Model and I/O (+ validation touchpoints)
**Covered PRD Requirements**: FR-1.11 (shipped type alphabet + CORP example; DEMO residual on bead `tablespec-abd68023`)
**Cross-Subsystem Rationale**: Primary subsystem is UMF Model and I/O
(the type and its mappings); the GX baseline, profiling, sample-data,
and compatibility touchpoints follow the type wherever the type alphabet
is consumed, per ADR-016.

> **Phase status (honest 2026-07-22).** Specs describe the desired end state.
>
> | Slice | Status | Evidence / residual |
> |-------|--------|---------------------|
> | EMB type alphabet + dimension validation | **Shipped** | `models/umf.py` EMBEDDING pattern + dimension validators |
> | Type mappings (SQL/PySpark/JSON/GX) | **Shipped** | `type_mappings.py`; unit tests |
> | Schema generators + GX baseline + sample data + compatibility | **Shipped** | Tests under `tests/unit/test_*` for generators, gx_baseline, column_value_generator, compatibility |
> | CORP document-corpus pattern example | **Shipped** | Canonical example: [`examples/sec10k_corpus.yaml`](../../../../examples/sec10k_corpus.yaml) (CORP-01 pattern, `EMBEDDING(1024)`) |
> | DEMO SEC 10-K (US-045) | **Partial** | Notebooks + example YAML exist; residual AC evidence on bead `tablespec-abd68023` |
>
> The facts-table half of the SEC demo may use FEAT-031's `json` source kind.

## Overview

This feature adds a dimensioned logical **EMBEDDING** type to UMF
(`data_type: EMBEDDING` + required `dimension: <int>`), per ADR-016:
compiled to `ARRAY<FLOAT>` in Spark SQL/Delta DDL,
`ArrayType(FloatType())` in PySpark, and a JSON Schema array-of-number;
validated by a GX dimensionality expectation plus a non-blocking
`dimension % 16` advisory; excluded from string-shape checks and from
profiling beyond null/dimension facts; generated deterministically in
sample data; and treated as compatible only with same-dimension
EMBEDDING by the compatibility checker.

On top of the type it defines a **document-corpus spec pattern** — the
canonical landed-table shape for chunked-and-embedded document corpora
(doc_id, chunk_id, source_path/page, text, embedding, provenance) — as a
pattern with a shipped example spec, **not** new model fields.
Acquisition (PDF parsing, chunking, embedding-model calls) is consumer
plumbing: tablespec never parses documents or calls models (PRD
Non-Goal preserved — the same boundary the Northwind demo drew around
the SQL Server install).

The acceptance vehicle is the SEC 10-K demo (US-045): a corpus table
with `EMBEDDING(1024)` (databricks-gte-large-en) plus an XBRL
companyfacts table, both specced and validated on Databricks.

## Ideal Future State

An engineer speccing a RAG corpus table declares
`data_type: EMBEDDING` with `dimension: 1024` and gets everything the
rest of UMF gets: DDL that lands `ARRAY<FLOAT>`, a PySpark schema, a
JSON Schema, an expectation suite that fails loudly when any row's
vector has the wrong length or smuggles NULL/NaN elements, deterministic
sample data, and a compatibility check that calls a dimension change
what it is — breaking. Vector Search prerequisites (PK, Change Data
Feed, the storage-optimized `% 16` rule) surface as advisories at spec
time, not as index-creation failures weeks later. The corpus table
itself follows one documented pattern, so every corpus in the org has
the same bones.

## Problem Statement

- **Current situation**: The EMBEDDING type alphabet, mappings, baseline
  expectations, sample-data generation, and compatibility rules are
  shipped in the library. Remaining gaps are the documented document-
  corpus pattern (example UMF) and full SEC 10-K demo acceptance (US-045),
  not re-introduction of the type itself.
- **Pain points**: Corpus tables either go unspecced (abandoning the
  single-source-of-truth contract for their defining column) or
  mis-specced as TEXT, attracting string-shape expectations and string
  profiling that are meaningless against a vector. Dimensionality — the
  one property that breaks Vector Search ingestion and pgvector
  targeting when wrong — is not captured, validated, or
  compatibility-checked anywhere.
- **Desired outcome**: EMBEDDING as a first-class dimensioned logical
  type per ADR-016, plus a canonical corpus-table pattern, proven by the
  SEC 10-K demo on Databricks.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Type declaration | "How do I spec an embedding column?" | `data_type: EMBEDDING` + required `dimension` property with model validation |
| Type mappings & generators | "What lands in the warehouse?" | `ARRAY<FLOAT>` DDL, `ArrayType(FloatType())` PySpark, JSON Schema array-of-number with pinned item count |
| Dimensionality validation | "How do I know every row's vector is right?" | GX dimensionality expectation; non-blocking `% 16` advisory; no string-shape checks on EMBEDDING |
| Sample data | "Can I generate test data for a corpus table?" | Deterministic seeded unit vectors of the declared dimension |
| Profiling passthrough | "What does the profiler say about an embedding?" | Null counts and observed-dimension facts only |
| Compatibility | "What happens when the model upgrade changes the dimension?" | EMBEDDING(n) compatible only with EMBEDDING(n); dimension change is breaking |
| Corpus pattern | "What columns should a corpus table have?" | Canonical landed-table spec pattern + shipped example spec under `examples/` |
| Corpus validation | "Is my landed corpus Vector-Search-ready?" | Staged validation incl. dimensionality; PK/CDF prerequisites surfaced as advisories |
| Demos | "Show me this working end to end" | SEC 10-K notebook pair (US-045); Kaggle flat-file demo precedes it under FEAT-031 (US-044) |

## Requirements

### Functional Requirements by Area

#### EMBEDDING type (EMB family) — FR-1.11

EMB-01. UMF SHALL accept `data_type: EMBEDDING` with a required
`dimension: <int>` column property (≥ 1). EMBEDDING without `dimension`
SHALL fail model validation with an actionable error; `dimension` on any
other data type SHALL likewise be rejected.
EMB-02. Type mappings (`src/tablespec/type_mappings.py`) SHALL map
EMBEDDING to `ARRAY<FLOAT>` (Spark SQL), `ArrayType(FloatType())` /
`"ArrayType(FloatType())"` (PySpark object/string forms), and JSON
Schema `{"type": "array", "items": {"type": "number"}}` with
`minItems`/`maxItems` equal to the declared dimension.
EMB-03. Schema generators (`src/tablespec/schemas/generators.py` —
`generate_sql_ddl`, `generate_pyspark_schema`, `generate_json_schema`)
SHALL emit the EMB-02 mappings for EMBEDDING columns.
EMB-04. The GX baseline SHALL emit a dimensionality expectation for each
EMBEDDING column: every non-NULL value has exactly `dimension` elements,
and contains no NULL/NaN elements unless the spec declares them
permitted.
EMB-05. When `dimension % 16 != 0`, validation SHALL surface a
**non-blocking advisory** naming the storage-optimized Vector Search
constraint; it SHALL never fail a run.
EMB-06. Sample-data generation SHALL produce deterministic
pseudo-embeddings for EMBEDDING columns: seeded unit vectors of the
declared dimension, byte-identical across runs.
EMB-07. Profiling SHALL record only null counts and observed-dimension
facts for EMBEDDING columns — no string or numeric statistics phases.
EMB-08. String-shape checks (`STRING_SHAPE_EXPECTATION_TYPES`,
`src/tablespec/gx_baseline.py:41-58`) SHALL never be emitted for
EMBEDDING columns.
EMB-09. The compatibility checker (`src/tablespec/compatibility.py`,
`src/tablespec/type_lattice.py`) SHALL treat EMBEDDING(n) as compatible
only with EMBEDDING(n): a dimension change is a **breaking** change, and
the widening lattice gains no edges to or from EMBEDDING.

#### Document-corpus pattern (CORP family)

CORP-01. tablespec SHALL document a canonical document-corpus
landed-table spec **pattern** — `doc_id`, `chunk_id`,
`source_path`/`page`, `text`, `embedding EMBEDDING(dim)`, plus
provenance columns (e.g. source system, acquisition timestamp, embedding
model identifier *as data*) — expressed entirely with existing model
fields plus the EMBEDDING type; no new UMF model fields.
CORP-02. A shipped example corpus spec SHALL live under `examples/`,
loadable and passing `tablespec validate` unmodified. **Shipped
example:** [`examples/sec10k_corpus.yaml`](../../../../examples/sec10k_corpus.yaml)
(paired companyfacts: `examples/sec10k_companyfacts.yaml`).
CORP-03. Staged validation of a landed corpus table SHALL include the
EMB-04 dimensionality expectation and standard structural/nullability
checks.
CORP-04. Vector Search ingestion prerequisites — a primary key and
Change Data Feed on the source table (standard endpoints) — SHALL be
surfaced as **non-blocking advisories** when validating a corpus spec
that lacks them, alongside the EMB-05 `% 16` advisory.
CORP-05. Acquisition SHALL remain consumer plumbing: no tablespec code
path parses documents, chunks text, or calls an embedding model or its
endpoint. Specs SHALL carry no endpoint URL, credential, or model
coupling (a model *name* may appear as provenance data values, never as
spec configuration).

#### Demos (DEMO family)

DEMO-01. The SEC 10-K demo (US-045) SHALL ship as a notebook pair under
`notebooks/sec-10k-demo/` following the `notebooks/northwind-demo/`
convention: notebook 01 is consumer plumbing (EDGAR acquisition,
chunking, embedding calls), notebook 02 is the tablespec story (spec,
validate, workbook, artifacts, scorecard).
DEMO-02. Notebook 01 SHALL offer a deterministic fake-embedding fallback
(widget-selected) so notebook 02's tablespec story runs identically with
or without Foundation Model API endpoint access.
DEMO-03. The Kaggle flat-file demo (US-044, FEAT-031 — delimited kind,
shipped code) SHALL precede this feature's demo as the first
notebook-pair demo; this feature reuses its conventions but does not own
it.

### Non-Functional Requirements

- **Back-compat**: UMFs with no EMBEDDING columns SHALL recompile
  byte-identically (zero golden diffs); the type addition is purely
  additive to the alphabet.
- **Determinism**: Sample pseudo-embeddings and all compiled artifacts
  for EMBEDDING columns SHALL be deterministic functions of the UMF
  (ADR-012 committed-artifact model).
- **Honest advisories**: Advisory-class findings (EMB-05, CORP-04) SHALL
  be visually and programmatically distinct from failures — never
  conflated with a failed expectation.
- **No new dependencies**: No embedding-model SDK, HTTP client, or
  document-parsing dependency enters `src/tablespec` (CORP-05 —
  enforceable by import test, same mechanism as FEAT-031's
  no-driver-imports rule).

## User Stories

- [US-044 — Kaggle Flat-File Onboarding](../user-stories/US-044-kaggle-flat-file-onboarding.md)
  — the first notebook-pair demo (FEAT-031's delimited kind, shipped
  code); establishes the demo conventions this feature's story reuses.
- [US-045 — SEC 10-K Corpus and Facts](../user-stories/US-045-sec-10k-corpus-and-facts.md)
  — this feature's acceptance story: corpus table with
  `EMBEDDING(1024)` + XBRL companyfacts table, specced and validated on
  Databricks.

## Edge Cases and Error Handling

- **Dimension-mismatch rows**: a landed row whose vector has ≠
  `dimension` elements SHALL fail the EMB-04 expectation with a real
  per-row result — never a silent pass.
- **NULL embeddings**: column-level NULLs follow the spec's declared
  nullability (standard not-null checks); NULL/NaN *elements inside* a
  vector fail EMB-04 unless declared permitted.
- **Model upgrade changes dimension**: a spec edit changing `dimension`
  is a breaking change per EMB-09 — surfaced by the compatibility
  checker, never silently absorbed.
- **`dimension % 16 != 0`**: advisory only (EMB-05); valid for standard
  Vector Search endpoints, flagged for storage-optimized ones.
- **EMBEDDING in a text-landed (delimited) source**: out of pattern —
  corpus tables land typed (parquet/JSON per ADR-015); the pattern
  documentation SHALL say so rather than defining a string encoding for
  vectors.

## Success Metrics

- **SEC demo green on Databricks (US-045)**: corpus + facts tables
  specced and validated end-to-end — corpus dimensionality expectation
  passing on both real (databricks-gte-large-en) and deterministic fake
  embeddings.
- Deterministic sample embeddings — byte-identical across runs, golden
  diff gate green on an EMBEDDING fixture.
- Zero string-shape checks emitted for EMBEDDING columns (conformance
  fixture assertion).
- Dimension change flagged breaking by `check_compatibility`.
- Zero golden diffs on pre-existing (EMBEDDING-free) UMFs.

## Constraints and Assumptions

- ADR-016 fixes the design: dimensioned EMBEDDING → `ARRAY<FLOAT>`,
  dimensionality validation, `% 16` advisory, deterministic sample
  vectors, same-dimension-only compatibility. This spec does not
  relitigate it (incl. the rejected generic `ARRAY<T>`, native VECTOR,
  and undimensioned `ARRAY<FLOAT>` options).
- The facts table in US-045 lands via FEAT-031's `json` source kind
  (operator-decided 2026-06-12; JSONL/JSON via Spark's reader, typed
  raw, FLAT projection — recorded in FEAT-031). This feature assumes
  that contract; it does not own it.
- Databricks remains the demo target: no native VECTOR type exists
  there; vector functions and Vector Search consume `ARRAY<FLOAT>`
  (ADR-016 References).
- `databricks-gte-large-en` returns 1024-dim floats — the demo's
  declared dimension; the dimension is per-spec data, so other models
  need only a different spec value.

## Dependencies

- **ADRs**: ADR-016 (the governing decision), ADR-015 (typed raw landing
  for parquet/JSON sources; consumer-plumbing boundary precedent),
  ADR-013 (target-agnostic core seam the new mappings live behind),
  ADR-012 (committed-artifact determinism).
- **Other features**: FEAT-031 (`json` source kind for the facts table;
  demo conventions via US-044), FEAT-001 (UMF models the type extends),
  FEAT-021 (spec validation), FEAT-011 (sample data), FEAT-009 (Excel
  workbook), FEAT-007/FEAT-017 (staged validation + report), FEAT-024
  (native profiler — gains the EMB-07 passthrough), FEAT-029 (Databricks
  session acquisition).
- **PRD requirements**: FR-1.11 (type alphabet shipped; CORP/DEMO residual on alignment beads).
- **Code touchpoints (planned)**: `src/tablespec/models/umf.py:511`,
  `src/tablespec/type_mappings.py`, `src/tablespec/schemas/generators.py`,
  `src/tablespec/gx_baseline.py`, `src/tablespec/sample_data/`,
  `src/tablespec/compatibility.py`, `src/tablespec/type_lattice.py`,
  `src/tablespec/profiling/native_profiler.py`.

## Out of Scope

- Parsing documents (PDF/HTML/text extraction) — consumer plumbing,
  always.
- Calling embedding models or Foundation Model API endpoints from
  tablespec code.
- Vector index creation or management (Vector Search endpoints/indexes,
  pgvector indexes) — tablespec surfaces prerequisites as advisories,
  nothing more.
- Generic `ARRAY<T>` container types (rejected in ADR-016).
- Lakebase/pgvector DDL emission — the declared dimension keeps the
  target open; no emitter is built here.
- Chunking strategy, retrieval quality, or any RAG-pipeline concern
  beyond the landed table's spec.

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements are listed; FR-1.11
  honestly marked as a parallel PRD addition
- [x] Functional areas are subordinate parts of this one capability
- [x] Overview connects this feature to ADR-016 and FR-1.11
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is missing
- [x] Every functional requirement is testable
- [ ] Acceptance criteria are defined in user stories — US-045 authored
  (Draft); US-044 belongs to FEAT-031
- [x] Non-functional requirements have specific targets
- [x] Edge cases cover realistic failure scenarios
- [x] Success metrics are specific to this feature
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes things someone might reasonably assume are
  in scope
- [x] Implementation status is honest: Approved; type core shipped; CORP/DEMO residual explicit, no
  phantom completion claims
- [x] Feature is consistent with governing ADR-016, FEAT-031's `json`
  kind decision, and the PRD Non-Goal on parsing/model calls
- [x] No `[NEEDS CLARIFICATION]` markers remain
