---
ddx:
  id: US-044
---

# US-044: Kaggle Flat-File Onboarding on Databricks

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: SRC-01, SRC-04, SRC-05, DUMP-05
**PRD Requirements**: FR-21.1
**Priority**: P1
**Status**: Built (notebooks under `notebooks/kaggle-demo/`; workspace job residual)

## Story

**As a** data engineer on a Databricks workspace with a public flat-file
dataset (a Kaggle CSV) staged in a Unity Catalog volume
**I want** a notebook pair that lands the delimited files, profiles
them, derives validated UMF specs, exports a reviewable schema workbook,
generates compiled artifacts, and runs staged validation
**So that** onboarding any flat-file drop is spec-driven from the first
minute — and the whole flow is a copy-paste-able demo that uses only
shipped tablespec code (FEAT-031's delimited kind), no planned features.

## Context

This is the first notebook-pair demo after `notebooks/northwind-demo/`,
and the cheapest one: every step it composes shipped 2026-06-10/11 or
earlier — the `source:` block and ingestion reader seam (FEAT-031
SRC-01..05), `NativeSparkProfiler` (FEAT-024,
`src/tablespec/profiling/native_profiler.py:87`), `SparkToUmfMapper`
(FEAT-005, `src/tablespec/profiling/spark_mapper.py`), spec validation
(FEAT-021), the Excel workbook (FEAT-009), and staged validation +
reporting (FEAT-007/FEAT-017). It establishes the demo conventions
(plumbing notebook 01 / tablespec-story notebook 02, dataset selection
via widgets, PASS/FAIL job exit) that the SEC 10-K demo (US-045,
FEAT-032) reuses for planned features.

Candidate dataset: the Kaggle **New York City Airbnb Open Data** CSV
(`AB_NYC_2019.csv`) — a single flat file with a useful type mix (ids,
names with commas/quotes, lat/long decimals, dates, counts, nulls). The
dataset is a demo *parameter*, not a contract: notebook widgets carry
the volume path and table name, and notebook 02 contains no
dataset-specific code, so any similarly-shaped CSV drops in.

## Walkthrough

1. The engineer stages the CSV in a Unity Catalog volume (notebook 01 —
   consumer plumbing: download/upload, nothing tablespec-specific) and
   sets the dataset widgets.
2. Notebook 02 lands the file as all-STRING raw through the ingestion
   reader seam, with reader options derived from a `source:
   {kind: delimited}` declaration (header, delimiter, quoting).
3. `NativeSparkProfiler` profiles the landed DataFrame;
   `SparkToUmfMapper` turns the profile into one UMF spec.
4. `tablespec validate` passes over the derived spec unmodified; the
   engineer reviews and optionally enriches it.
5. `tablespec export-excel` produces the schema workbook for domain
   review.
6. Compiled artifacts (raw DDL, ingest SQL, expectation suites) are
   generated from the spec, deterministically.
7. Staged validation executes against the landed table and produces a
   per-expectation report; the notebook job exits PASS/FAIL on the
   result.

## Acceptance Criteria

- [x] **US-044-AC1 (land + profile + spec)** — Given the Kaggle CSV
  staged in a volume and a `source: {kind: delimited}` declaration, when
  notebook 02 lands the file through the ingestion reader seam and runs
  `NativeSparkProfiler` + `SparkToUmfMapper`, then the file lands
  all-STRING raw with reader options derived from the declaration (no
  hardcoded reader), and one UMF spec is emitted that passes
  `tablespec validate` with zero errors and zero manual edits.
  **Evidence**: `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py`
  (land → profile → map → validate cells; AC1 scorecard row).
- [x] **US-044-AC2 (schema workbook)** — Given the derived UMF, when
  `tablespec export-excel` runs, then a workbook is produced whose rows
  match the UMF columns/types and a re-import round-trips without loss
  (FEAT-009 contract).
  **Evidence**: notebook 02 Excel export + round-trip assert (AC2).
- [x] **US-044-AC3 (artifacts + staged validation)** — Given the derived
  UMF, when artifact generation and staged validation run, then compiled
  artifacts (raw DDL, ingest SQL, expectation suites) are produced
  deterministically from the spec, and staged validation against the
  landed table yields a report with real per-expectation results (no
  silent `success=False` stubs).
  **Evidence**: notebook 02 compile + staged validation cells (AC3).
- [x] **US-044-AC4 (demo lane + swappability)** — Given the notebook
  pair committed under `notebooks/kaggle-demo/`, when it runs as a
  Databricks workspace job with the default dataset widgets, then the
  job exits PASS; and when the widgets point at a different
  similarly-shaped CSV, notebook 02 runs unmodified (dataset-specific
  values appear only in widgets and notebook 01).
  **Evidence**: notebook pair + README “Swapping datasets”; scorecard
  asserts no dataset-specific code in notebook 02.
  **Limitation**: workspace job PASS/FAIL is not CI-gated (Databricks
  residual, same posture as US-039/US-045).

## Edge Cases

- Quoted fields containing the delimiter (Airbnb listing names contain
  commas): the `source:` declaration carries quoting options; landed
  column counts must match the header, never silently shift.
- Empty-string vs NULL in the raw landing: profiled null counts reflect
  the declared `null_value` token semantics.
- A column the profiler types narrowly (e.g. an all-numeric id): the
  derived UMF is a reviewable spec — the engineer can widen it before
  compiling, same posture as US-039's discovery output.

## Test Scenarios

- Databricks lane: the notebook pair under `notebooks/kaggle-demo/` runs
  as a workspace job and exits PASS — the acceptance lane for this
  story (mirroring `notebooks/northwind-demo/`'s job-run evidence
  convention).
- Repo lane: notebook sources are committed and lint-clean; the staged
  CSV itself is not committed (acquired by notebook 01).

## Dependencies

- **Feature Spec**: FEAT-031 (SRC-01..05 shipped 2026-06-10; this story
  adds no new library code — notebooks only)
- **Decisions**: ADR-015 (source-shape contract; all-STRING raw for
  text-landed sources), ADR-007 (all-STRING raw landing)
- **Shipped features reused**: FEAT-024 (`NativeSparkProfiler`),
  FEAT-005 (`SparkToUmfMapper`), FEAT-021 (spec validation), FEAT-009
  (Excel workbook), FEAT-007/FEAT-017 (staged validation + report),
  FEAT-029 (session acquisition on Databricks)
- **Successor**: US-045 (SEC 10-K demo, FEAT-032) reuses this story's
  notebook-pair conventions for planned features

## Out of Scope

- Kaggle API authentication/automation — staging the file is consumer
  plumbing in notebook 01 (manual upload is acceptable).
- Any new tablespec library code — this story composes shipped features
  only; gaps it surfaces are filed, not patched inline.
- Multi-file or partitioned datasets (single flat file for the first
  demo).
- Embeddings, JSON sources, or anything from FEAT-032/US-045.
