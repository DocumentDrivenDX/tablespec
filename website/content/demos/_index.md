---
title: Demos
weight: 5
---

This page is for readers who want concrete demo arcs against real inputs. Each
demo names the source data, the generated UMF specs or artifacts, and where to
run it. For the ordered operator checklist (wheel upload, cluster mode, opt-in
serverless), use [In a workspace](/getting-started/in-a-workspace/).

## Northwind on Databricks

The Northwind demo starts with the sample Northwind SQL Server database and
runs on a Databricks cluster. It discovers database tables over JDBC,
generates one Universal Metadata Format (UMF) spec per table, validates those
specs, exports review workbooks, generates sample data, and lands typed tables
with staged validation reports.

The demo lives in two notebooks under
[`notebooks/northwind-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/northwind-demo):

1. **`01-provision-sqlserver-northwind`** — installs SQL Server on the
   driver node, configures it, and loads the Northwind database. Plumbing
   only; tablespec never does this in real use.
2. **`02-northwind-discovery-demo`** — the tablespec flow:
   - **Discover**: `JdbcToUmfMapper().discover(spec, spark)` produces one
     validated UMF spec per table over JDBC. Each spec includes columns,
     types, primary keys, foreign keys, and provenance columns. The credential
     exists only as a `password_secret_ref`; a literal password fails spec
     validation.
   - **Validate**: every discovered UMF spec passes `tablespec validate`
     without manual edits.
   - **Workbooks**: tablespec exports each spec to Excel for human review.
   - **Sample data**: tablespec generates foreign-key-aware rows that respect
     the discovered relationships.
   - **Land typed + staged validation**: tables land natively typed, so JDBC
     values are not round-tripped through string parsing. Generated validation
     suites for typed sources carry no string-shape raw checks. The run ends
     in a per-table validation scorecard.

Cluster notes and wheel upload steps: the
[notebook README](https://github.com/DocumentDrivenDX/tablespec/blob/main/notebooks/northwind-demo/README.md)
and [In a workspace](/getting-started/in-a-workspace/). The same flow runs
locally without Databricks via the Docker-gated test:
`uv run pytest tests/integration/test_northwind_e2e.py`.

## Kaggle flat-file onboarding

The Kaggle demo lands a delimited CSV from a Unity Catalog volume (default:
NYC Airbnb open data), profiles it, produces a validated UMF, exports a
workbook, compiles artifacts, and runs staged validation.

Notebooks under
[`notebooks/kaggle-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/kaggle-demo):

1. **`01-stage-csv-kaggle`** — schema/volume + CSV stage (plumbing).
2. **`02-kaggle-tablespec-demo`** — tablespec story end to end.

Widgets swap the CSV URL or path for other flat files of the same shape.

## SEC 10-K corpus and facts

The SEC demo governs a document corpus with `EMBEDDING(1024)` and an XBRL
companyfacts table via `source: kind: json`. Notebook 01 is consumer plumbing
(EDGAR + embed); notebook 02 is the tablespec path (validate, compile, staged
validation with dimensionality checks).

Notebooks under
[`notebooks/sec-10k-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/sec-10k-demo);
example specs in
[`examples/sec10k_corpus.yaml`](https://github.com/DocumentDrivenDX/tablespec/blob/main/examples/sec10k_corpus.yaml)
and
[`examples/sec10k_companyfacts.yaml`](https://github.com/DocumentDrivenDX/tablespec/blob/main/examples/sec10k_companyfacts.yaml).

Use the deterministic fake embedding mode when the workspace has no Foundation
Model API access.

## Synthea guidebook

The Synthea guidebook demo shows the static guidebook generator against a
small healthcare schema: ten raw Synthea-style source tables plus a computed
`member_quality_summary` report table. The report demonstrates derivation
lineage, including a window-function candidate for latest A1C and
survivorship defaults preserved through Excel review.

The committed demo artifacts live under
[`examples/synthea/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/examples/synthea):

- `umfs/` — split UMF specs for raw tables and the computed report.
- `specs/` — Excel review workbooks generated from those UMFs.
- `guidebook/` — rendered static HTML output, one page per table plus
  `index.html` and `search_index.json`.

Run it locally after installing tablespec:

```bash
tablespec guidebook examples/synthea/umfs -o /tmp/synthea-guidebook
```

Open `/tmp/synthea-guidebook/index.html` in a browser to inspect table
metadata, validation rules, foreign-key consumers, derivation sources, SQL
expressions, and survivorship notes without running a web app.

## Library walkthrough (screencast)

The library walkthrough is a scripted local demo. It loads UMF specs,
generates schemas, maps types, infers domain types, creates a Great
Expectations baseline suite, diffs UMF versions, profiles Spark data, and
validates a DataFrame.

[![Demo](https://github.com/DocumentDrivenDX/tablespec/raw/main/examples/tablespec-demo.gif)](https://github.com/DocumentDrivenDX/tablespec/blob/main/examples/tablespec-demo.cast)

**Play in your terminal:**

```bash
asciinema play examples/tablespec-demo.cast
```

**Run live** (requires `tablespec[spark]`; also serves as an acceptance test
and exits non-zero on any failure):

```bash
uv run python examples/demo.py
```

**Watch with narration:**
[tablespec-demo-narrated.mp4](https://github.com/DocumentDrivenDX/tablespec/raw/main/examples/tablespec-demo-narrated.mp4)
