---
title: Demos
weight: 5
---

Reproducible demos of tablespec workflows.

## Northwind on Databricks

The flagship demo runs the full discovery story on a Databricks cluster, in
two notebooks under
[`notebooks/northwind-demo/`](https://github.com/DocumentDrivenDX/tablespec/tree/main/notebooks/northwind-demo):

1. **`01-provision-sqlserver-northwind`** — installs SQL Server on the
   driver node, configures it, and loads the Northwind database. Plumbing
   only; tablespec never does this in real use.
2. **`02-northwind-discovery-demo`** — the tablespec story:
   - **Discover**: `JdbcToUmfMapper().discover(spec, spark)` produces one
     validated UMF per table over JDBC — columns and types, primary and
     foreign keys, provenance columns. The credential exists only as a
     `password_secret_ref`; a literal password fails spec validation.
   - **Validate**: every discovered spec passes `tablespec validate`
     unmodified.
   - **Workbooks**: Excel exports of each spec for human review.
   - **Sample data**: FK-aware generated rows that respect the discovered
     relationships.
   - **Land typed + staged validation**: tables land natively typed through
     the reader seam (never round-tripped through string parsing), suites
     composed for typed sources carry no string-shape raw checks, and the
     run ends in a per-table validation scorecard.

Proven on DBR 17.3 LTS (Spark 4, SQL Server 2025) and DBR 16.4 LTS
(SQL Server 2022), single-node, single-user access mode. The
[notebook README](https://github.com/DocumentDrivenDX/tablespec/blob/main/notebooks/northwind-demo/README.md)
covers cluster setup, wheel upload, and running against an external SQL
Server instead. The same flow runs locally without Databricks via the
Docker-gated test: `uv run pytest tests/integration/test_northwind_e2e.py`.

## Library walkthrough (screencast)

A scripted demo of the local library surface: loading specs, schema
generation, type mappings, domain inference, the Great Expectations
baseline, UMF diffing, Spark profiling, and DataFrame validation.

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
