---
title: In a workspace
weight: 4
---

Use these steps when you have a Databricks workspace and want to exercise
tablespec beyond local unit tests. Nothing here is required for default CI.
The paths are the same demos and opt-in harnesses already in the repository —
this page is the ordered operator checklist.

## Shared setup

1. Clone or sync the repo into the workspace (Git folder or
   `databricks workspace import-dir`).
2. Build a wheel and upload it where the notebooks can install it:

   ```bash
   uv build
   # example destinations used by the demos:
   # dbfs:/FileStore/tablespec-demo/   or a UC volume path
   ```

3. Prefer a **single-user** cluster on a recent LTS runtime (Python ≥ 3.12 for
   current wheels; DBR 16.4+ is a good default).

## 1. Bootstrap existing tables (Path A)

When tables already live in Unity Catalog / Spark:

```python
from tablespec import bootstrap_from_tables

artifacts = bootstrap_from_tables(
    spark,
    ["catalog.schema.member", "catalog.schema.claims"],
    out_dir="/tmp/tablespec-bootstrap",
    profile=True,
    dialect="databricks",  # Spark-family SQL; accepted public dialect
)
```

`bootstrap_from_tables` reflects schema into UMF, optionally enriches validation
from the native profiler, compiles the committed artifact tree, and returns the
manifest. See also [Getting Started](/getting-started/) for Path B (authored
specs) without Spark.

## 2. Northwind — JDBC discovery end to end

**Goal:** point tablespec at a SQL Server database; get one validated UMF per
table, Excel workbooks, sample data, typed land, staged validation.

Notebooks:
[`notebooks/northwind-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/northwind-demo)

| Order | Notebook | Role |
|-------|----------|------|
| 1 | `01-provision-sqlserver-northwind` | Installs SQL Server on the driver and loads Northwind (plumbing — not a tablespec product path) |
| 2 | `02-northwind-discovery-demo` | Discover → validate → workbooks → sample data → land typed → scorecard |

Requirements: **single-node** cluster so `localhost` JDBC works; single-user
access mode. Credentials in UMF are **secret refs only**.

Local stand-in (no workspace): Docker-gated
`uv run pytest tests/integration/test_northwind_e2e.py`.

## 3. Kaggle-style flat file — delimited onboarding

**Goal:** stage a CSV on a UC volume, land all-STRING raw, profile, author UMF,
export a workbook, compile artifacts, run staged validation.

Notebooks:
[`notebooks/kaggle-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/kaggle-demo)

| Order | Notebook | Role |
|-------|----------|------|
| 1 | `01-stage-csv-kaggle` | Create schema/volume; stage CSV (plumbing) |
| 2 | `02-kaggle-tablespec-demo` | tablespec story end to end |

Default dataset is NYC Airbnb open data; widgets swap URL/path for other CSVs.

## 4. SEC 10-K — embeddings and JSON facts

**Goal:** govern a corpus table with `EMBEDDING(1024)` and an XBRL facts table
via `source: kind: json`, with dimensionality validation on the embedding
column.

Notebooks:
[`notebooks/sec-10k-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/sec-10k-demo)

| Order | Notebook | Role |
|-------|----------|------|
| 1 | `01-edgar-plumbing` | EDGAR fetch, chunk, embed (real FM API or deterministic fake), land JSON |
| 2 | `02-sec10k-tablespec-demo` | Validate specs, compile artifacts, staged validation scorecard |

Use `embedding_mode=fake` when the workspace has no Foundation Model API
access. Specs never embed endpoints or credentials.

Example specs:
[`examples/sec10k_corpus.yaml`](https://github.com/DocumentDrivenDX/tablespec/blob/main/examples/sec10k_corpus.yaml),
[`examples/sec10k_companyfacts.yaml`](https://github.com/DocumentDrivenDX/tablespec/blob/main/examples/sec10k_companyfacts.yaml).

## 5. Opt-in serverless / workspace conformance

**Goal:** when credentials are present, prove dbt/LDP deploy + read-back parity
against the shared Spark oracle corpus.

Default `make test` **never** requires a workspace. The lane is opt-in:

```bash
export DATABRICKS_HOST=https://<workspace>
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<id>
export DATABRICKS_TOKEN=<pat>
# adapters: dbt-databricks, databricks-sdk, databricks-sql-connector

uv run pytest -m databricks_e2e -q
```

Without credentials, those tests **skip with a named reason** — they do not
silently pass. The unit gate for the skip path is
`tests/unit/test_databricks_e2e_gate.py`.

## 6. Deploy the profiling app

Separate checklist: [Deploy the app](/getting-started/deploy-the-app/).

## What “done” looks like for you

| Path | You can stop when… |
|------|--------------------|
| Path A bootstrap | Artifact tree exists under `out_dir` and recompile is a no-diff for unchanged UMF |
| Northwind | Scorecard notebook finishes; every discovered table has a validated UMF |
| Kaggle | Staged validation report for the landed CSV-driven table |
| SEC 10-K | Dimensionality expectation exercises on the corpus embedding column |
| Serverless e2e | `pytest -m databricks_e2e` green with your secrets (or skip with a clear reason without them) |
| App | Guidebook/profile tabs read and write only the declared metadata home |

There is no requirement to file “PASS” tickets or attach screenshots to the
tracker. These steps are the product’s getting-started surface for workspace
use; run them when you care about that environment.

## Next

{{< cards >}}
  {{< card link="/getting-started/deploy-the-app/" title="Deploy the app" subtitle="FR-23 portability: provision, declare inputs, grant, deploy." icon="cog" >}}
  {{< card link="/demos/" title="Demos" subtitle="Narrative detail for Northwind, Synthea, and the local screencast." icon="play" >}}
  {{< card link="/concepts/artifacts/" title="Compiled artifacts" subtitle="What the commit tree contains after compile." icon="document-text" >}}
{{< /cards >}}
