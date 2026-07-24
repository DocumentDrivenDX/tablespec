---
title: First 15 minutes (no Spark)
weight: 2
---

Install tablespec, author one split UMF, validate it, compile artifacts, and
open a guidebook — **without Spark or a Databricks workspace**.

## 1. Install

```bash
uv add tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/
# or: pip install tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/
```

## 2. Author a minimal split UMF

Use the [Getting Started](/getting-started/) authoring example, or any split
directory with `table.yaml` + `columns/*.yaml` (and provenance columns if you
will run full pipeline validate).

For a quick try from the repo fixtures after cloning tablespec:

```bash
# from a tablespec checkout
ls tests/e2e/fixtures/member.umf.yaml
```

## 3. Validate

```bash
tablespec validate tables/medical_claims/
# or a fixture:
tablespec validate tests/e2e/fixtures/member.umf.yaml
```

## 4. Compile artifacts (Path B one-shot)

```bash
tablespec bootstrap tables/medical_claims/ -o build/artifacts --dialect duckdb
# Databricks-facing cast SQL spelling (normalizes to Spark-family SQL):
# tablespec bootstrap tables/medical_claims/ -o build/artifacts --dialect databricks
```

This is the public CLI for `bootstrap_from_specs`: load UMF → write the committed
artifact tree (ingest SQL, schemas, suites, dbt/LDP projects as applicable).

Inspect `build/artifacts/` for generated files.

## 5. Generate single-format outputs (optional)

```bash
tablespec generate tables/medical_claims/ -f sql
tablespec generate tables/medical_claims/ -f ingest
tablespec emit tables/medical_claims/ out/dbt --backend dbt --dialect duckdb
```

## 6. Guidebook

```bash
tablespec guidebook tables/ -o out/guidebook
# open out/guidebook/index.html in a browser
```

Empty directories fail with an actionable error (exit 1).

## What you proved

| Step | Result |
|------|--------|
| Install | Package from the Pages index |
| Validate | UMF structure accepted |
| Bootstrap | Deterministic artifact tree under `-o` |
| Guidebook | Browsable HTML for the same UMF set |

**Next:** [In a workspace](/getting-started/in-a-workspace/) when you have
Databricks; [Deploy the app](/getting-started/deploy-the-app/) for the profiling UI.
