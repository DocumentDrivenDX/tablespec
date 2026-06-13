# SEC 10-K Corpus + XBRL Facts Demo (US-045)

Demonstrates FEAT-032 end-to-end on Databricks: an EDGAR-sourced 10-K corpus
table with a dimensioned `EMBEDDING(1024)` column, and an XBRL companyfacts
table loaded via FEAT-031's `json` source kind — both specced, validated, and
artifact-compiled with tablespec.

The demo follows the same **plumbing 01 / tablespec story 02** convention as
the Northwind demo (US-039): everything that touches external services lives in
notebook 01; notebook 02 invokes no document parsing and no model endpoint.

## Notebooks

| Notebook | Purpose |
|----------|---------|
| `01-edgar-plumbing.py` | Consumer plumbing: EDGAR fetch (declared `User-Agent`, rate-limited), text extraction, chunking, embedding (real or deterministic fake), XBRL companyfacts JSON landing |
| `02-sec10k-tablespec-demo.py` | tablespec story: load specs, validate, inspect DDL/PySpark/JSON artifacts, export workbooks, staged validation with dimensionality check, US-045 scorecard |

## Spec files (in `examples/`)

| File | Table | Key feature |
|------|-------|-------------|
| `sec10k_corpus.yaml` | `sec_10k_corpus` | `embedding EMBEDDING(1024)` — compiles to `ARRAY<FLOAT>`, per-row dimensionality validation |
| `sec10k_companyfacts.yaml` | `sec_xbrl_facts` | `source: kind: json` FLAT projection — `cik` and `entity_name` from EDGAR companyfacts JSONL |

## Cluster requirements

- **Single-user access mode** (standard Databricks runtime, LTS recommended)
- **Unity Catalog** with a volume to write outputs (default: `main.sec_10k_demo.raw`)
- **Foundation Model API access** only needed for `embedding_mode=real`
  (notebook 01 widget) — the default `fake` mode runs without it

## Running the demo

### Step 1 — Run notebook 01 (plumbing)

Set widgets:

| Widget | Default | Notes |
|--------|---------|-------|
| `embedding_mode` | `fake` | `fake` = deterministic seeded unit vectors; `real` = `databricks-gte-large-en` |
| `output_catalog` | `main` | Unity Catalog catalog |
| `output_schema` | `sec_10k_demo` | UC schema |
| `output_volume` | `raw` | UC volume — created if absent |
| `wheel_path` | *(empty)* | Path/glob to tablespec wheel; empty = preinstalled |

The notebook fetches a small fixed set of 10-K filings from SEC EDGAR
(Microsoft, Apple, Tesla), extracts plain text, chunks it into ~300-word
windows, embeds each chunk, and writes:

- `sec_10k_corpus` — Delta table under the volume
- `sec_xbrl_facts/companyfacts.jsonl` — one-JSON-per-line EDGAR companyfacts

### Step 2 — Run notebook 02 (tablespec story) on the same cluster

Pass the same catalog/schema/volume widgets so notebook 02 reads the paths
notebook 01 wrote.

Notebook 02 runs identically regardless of which embedding mode was used in
notebook 01 — specs carry no endpoint URL, credential, or model configuration
(US-045 AC4).

### Running as a Databricks job

Create a multi-task job:

1. Task 1: `01-edgar-plumbing` — widget `embedding_mode=fake`
2. Task 2: `02-sec10k-tablespec-demo` — depends on task 1; same catalog/schema/volume

The job exits PASS (via `dbutils.notebook.exit`) when all US-045 ACs are satisfied.

## What notebook 02 verifies (US-045 ACs)

| AC | Verified by |
|----|------------|
| AC1 — corpus spec validates, DDL=`ARRAY<FLOAT>`, PySpark=`ArrayType(FloatType())`, JSON `minItems`/`maxItems`=1024 | `UMFValidator`, `generate_sql_ddl`, `generate_pyspark_schema`, `generate_json_schema` |
| AC2 — dimensionality check: corrupted row FAILS, clean corpus PASSES | `GXSuiteExecutor.execute_staged` with a deliberately wrong-dimension fixture row |
| AC3 — facts spec validates, json-kind typed landing passes, no string-shape checks | `JsonReader`, `BaselineExpectationGenerator`, `STRING_SHAPE_EXPECTATION_TYPES` |
| AC4 — no credential/endpoint in either spec | Text scan of both spec files |
| AC5 — plumbing boundary: nb02 has no EDGAR calls, no model endpoint calls | Text scan of this notebook |
| AC6 — scorecard produced, advisories distinct from failures, corpus suite PASSES | `ValidationReport.success` + advisory separation |

## SEC EDGAR fair-access policy

Notebook 01 complies with the SEC's automated-access requirements:

- Declared `User-Agent` header on every request: `Telepath Data sec-10k-demo@example.com`
- Rate limiting: ≤ 10 requests per second
- Small fixed company set (3 companies): keeps the demo polite and fast

See <https://www.sec.gov/os/accessing-edgar-data> for the full policy.

## Design notes

- **1024 % 16 == 0** → the storage-optimized Vector Search `% 16` advisory does
  not fire (EMB-05); the corpus is ready for standard Vector Search endpoints.
- The embedding column is **nullable** in the corpus spec (some chunks may be
  embedded asynchronously); NULL/NaN *elements inside* a non-NULL vector still
  fail EMB-04.
- The facts spec projects only `cik` and `entityName` from the companyfacts JSON —
  the deeply-nested `facts.dei` / `facts.us-gaap` structure is outside this
  bronze contract (no recursive flattening, FLAT projection only).
- Embedding model name (`databricks-gte-large-en` or `fake-deterministic-1024`)
  appears only as a **data value** in the `embedding_model` column — not as spec
  configuration. Switching models requires a new ingestion run, not a spec edit.
