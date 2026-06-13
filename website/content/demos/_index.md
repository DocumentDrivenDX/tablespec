---
title: Demos
weight: 5
---

This page is for readers who want evidence that tablespec can run against real
inputs. Each demo names the source data, the generated UMF specs or artifacts,
the validation result, and the environment used to run it.

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

The demo has run on DBR 17.3 LTS (Spark 4, SQL Server 2025) and DBR 16.4 LTS
(SQL Server 2022), single-node, single-user access mode. The
[notebook README](https://github.com/DocumentDrivenDX/tablespec/blob/main/notebooks/northwind-demo/README.md)
covers cluster setup, wheel upload, and running against an external SQL
Server instead. The same flow runs locally without Databricks via the
Docker-gated test: `uv run pytest tests/integration/test_northwind_e2e.py`.

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
