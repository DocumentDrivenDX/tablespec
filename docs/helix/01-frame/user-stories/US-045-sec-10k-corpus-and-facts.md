---
ddx:
  id: US-045
---

# US-045: SEC 10-K Corpus and Facts on Databricks

**Feature**: FEAT-032 — Embeddings and Document Corpus
**Feature Requirements**: EMB-01–EMB-09, CORP-01–CORP-05, DEMO-01,
DEMO-02
**PRD Requirements**: FR-1.11
**Priority**: P1
**Status**: Built (type core + example specs + notebooks shipped; operator steps on microsite Getting Started)

## Story

**As a** data engineer building a RAG corpus from SEC 10-K filings on a
Databricks workspace
**I want** a notebook pair where the plumbing notebook acquires, chunks,
and embeds the filings, and the tablespec notebook specs the corpus
table (with a dimensioned EMBEDDING column) and the XBRL companyfacts
table, validates both — including per-row embedding dimensionality —
and produces workbooks, artifacts, and a staged-validation scorecard
**So that** the corpus's defining column is governed like every other
column, and a wrong-dimension or NULL-element embedding is caught by
validation instead of by a Vector Search ingestion failure.

## Context

This is FEAT-032's acceptance story and the second notebook-pair demo,
reusing US-044's conventions (plumbing 01 / tablespec story 02, widgets,
PASS/FAIL job exit). The split enforces the consumer-plumbing boundary
(CORP-05, ADR-016): everything in notebook 01 — EDGAR fetching, text
extraction, chunking, embedding-endpoint calls — is plumbing tablespec
never performs, exactly as the SQL Server install stayed with the
consumer in the Northwind demo (US-039).

The corpus table follows the CORP-01 pattern with
`embedding EMBEDDING(1024)` — `databricks-gte-large-en` returns
1024-dim floats (1024 % 16 == 0, so no storage-optimized advisory). The
facts table lands the XBRL companyfacts JSON via FEAT-031's `json`
source kind (operator-decided 2026-06-12; recorded in FEAT-031): Spark's
JSON reader, typed raw, with the spec declaring a FLAT projection —
each UMF column maps to a top-level field or an explicit dot-path; no
recursive flattening.

A widget in notebook 01 selects real embeddings (the Foundation Model
API `databricks-gte-large-en` endpoint) or a **deterministic fake**
(seeded 1024-dim unit vectors). The tablespec story in notebook 02 is
identical either way — specs carry no endpoint, credential, or model
coupling, so the demo runs on workspaces without FM API access.

## Walkthrough

1. Notebook 01 (plumbing) fetches a small set of 10-K filings from
   EDGAR with a proper declared `User-Agent` and rate limiting per the
   SEC fair-access policy, extracts text, chunks it, and embeds each
   chunk — via the `databricks-gte-large-en` endpoint or the
   deterministic fake, per widget. It also fetches the XBRL
   companyfacts JSON for the same companies. Both land in a volume /
   Delta staging area.
2. Notebook 02 (tablespec story) loads the corpus spec — the CORP-01
   pattern: `doc_id`, `chunk_id`, `source_path`, `page`, `text`,
   `embedding EMBEDDING(1024)`, provenance columns (embedding model
   name as a data value) — and the facts spec (`json` source kind, FLAT
   projection of companyfacts fields).
3. `tablespec validate` passes over both specs unmodified.
4. Schema workbooks are exported for both tables; compiled artifacts
   (DDL with `ARRAY<FLOAT>` for the embedding column, expectation
   suites including the dimensionality expectation) are generated
   deterministically.
5. Staged validation executes against both landed tables and renders a
   per-table scorecard: real per-expectation results, dimensionality
   checked on every row, PK/CDF Vector Search prerequisites surfaced as
   advisories where absent.
6. The job exits PASS/FAIL on the scorecard.

## Acceptance Criteria

- [x] **US-045-AC1 (corpus spec with EMBEDDING)** — Given the corpus
  spec following the CORP-01 pattern with
  `embedding: {data_type: EMBEDDING, dimension: 1024}`, when
  `tablespec validate` runs, then the spec passes with zero errors, and
  the compiled artifacts render the column as `ARRAY<FLOAT>` (DDL),
  `ArrayType(FloatType())` (PySpark), and a JSON Schema array-of-number
  with min/max items 1024.
  **Evidence**: `examples/sec10k_corpus.yaml`; unit tests in
  `tests/unit/test_umf_models.py`, `test_type_mappings.py`,
  `test_schema_generators.py` (embedding → ARRAY/ArrayType/JSON array
  dimension); notebook 02 asserts DDL/PySpark/JSON Schema contract.
- [x] **US-045-AC2 (dimensionality expectation)** — Given an EMBEDDING
  column with dimension 1024, when the GX baseline is generated, then a
  dimensionality length expectation is emitted with `value=1024`, and
  non-divisible-by-16 dimensions surface a non-blocking advisory.
  **Evidence**: `tests/unit/test_gx_baseline.py`
  (`test_embedding_generates_length_expectation`,
  `test_embedding_dimension_*_advisory`). End-to-end staged validation
  with real/fake embedding widgets: `notebooks/sec-10k-demo/` (optional
  Foundation Model API for `embedding_mode=real`).
- [x] **US-045-AC3 (facts table, JSON-landed)** — Given a facts spec
  declaring FEAT-031's `json` source kind with a FLAT projection, when
  validated/compiled, then the model and typed-raw path accept it.
  **Evidence**: `examples/sec10k_companyfacts.yaml`; US-050 + JSON
  conformance tier (`tests/conformance/test_json_tier.py`); backbone
  accepts `kind=json`. Full EDGAR-landed staged validation is in
  `notebooks/sec-10k-demo/` (01 plumbing → 02 tablespec).
- [x] **US-045-AC4 (no credential/model coupling)** — Given both specs
  under `examples/`, when inspected, then no endpoint URL, token, or
  model configuration appears — only provenance *data* fields such as
  `embedding_model`.
  **Evidence**: static review of `examples/sec10k_corpus.yaml` and
  `examples/sec10k_companyfacts.yaml` (CORP-05 boundary).
- [x] **US-045-AC5 (consumer-plumbing boundary)** — Given the committed
  notebook pair under `notebooks/sec-10k-demo/`, when reviewed, then
  EDGAR/parse/chunk/embed live only in notebook 01; notebook 02 is
  tablespec-only.
  **Evidence**: notebook headers and README split; library has no
  EDGAR/embedding client modules for this story.
- [x] **US-045-AC6 (scorecard + advisories)** — Given notebook 02's
  staged validation path, when run, then a per-table scorecard and
  Vector Search advisories are produced.
  **Evidence**: notebook 02 scorecard cells; run via
  `notebooks/sec-10k-demo/` or microsite Getting Started → In a workspace.

## Edge Cases

- **Embedding model upgrade** (a gte successor with a different
  dimension): the spec's `dimension` is data — old-spec validation
  fails loudly on new-dimension vectors, and editing the spec's
  dimension is flagged breaking by the compatibility checker (EMB-09).
- **EDGAR throttling/unavailability**: notebook 01 rate-limits and
  fails actionably; the deterministic-fake path plus a small committed
  text fixture keeps notebook 02's story runnable regardless.
- **NULL embedding rows** (chunk embedded later): column-level NULLs
  follow declared nullability; NULL *elements inside* a vector fail
  dimensionality (EMB-04).
- **Companyfacts nesting beyond the FLAT projection**: un-projected
  nested fields are out of the bronze contract — the spec declares only
  top-level fields or explicit dot-paths; nothing recursively flattens.

## Test Scenarios

- Databricks lane: the notebook pair under `notebooks/sec-10k-demo/`
  runs as a workspace job in fake-embedding mode (no FM API dependency)
  and exits PASS — the acceptance lane; a real-endpoint run on an
  FM-API-enabled workspace covers AC2's real half.
- Repo lane: unit/conformance fixtures cover the EMBEDDING type slice
  (EMB-01..09) independently of the demo — including the
  corrupted-dimension fixture and the zero-string-shape-checks
  assertion.

## Dependencies

- **Feature Spec**: FEAT-032 (EMB-01..09, CORP-01..05, DEMO-01..02 —
  all planned)
- **Decisions**: ADR-016 (EMBEDDING → `ARRAY<FLOAT>`; consumer-plumbing
  boundary), ADR-015 (typed raw for non-text sources)
- **Cross-feature**: FEAT-031's `json` source kind (operator-decided
  2026-06-12, recorded in FEAT-031) — a blocking dependency for AC3
- **Shipped features reused**: FEAT-021 (spec validation), FEAT-009
  (workbooks), FEAT-007/FEAT-017 (staged validation + report), FEAT-029
  (session acquisition)
- **Predecessor**: US-044 (Kaggle demo — establishes the notebook-pair
  conventions with shipped code)
- **External**: SEC EDGAR fair-access policy (declared User-Agent, rate
  limits) — notebook 01's plumbing obligation; Databricks FM API
  `databricks-gte-large-en` endpoint (optional at run time via the fake
  fallback)

## Out of Scope

- Vector Search index creation/management — prerequisites surface as
  advisories only.
- Retrieval/RAG quality, chunking strategy tuning, prompt construction.
- Parsing or embedding inside tablespec library code — permanently out
  (PRD Non-Goal).
- Full-universe EDGAR ingestion — a small fixed company set keeps the
  demo fast and polite.
- Lakebase/pgvector emission (future target the declared dimension
  keeps open).
