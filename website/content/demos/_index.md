---
title: Demos
weight: 5
---

Reproducible demos of tablespec workflows.

## Full compile path

The main demo walks through the complete tablespec workflow: loading a UMF
schema, generating SQL DDL, PySpark schema, and JSON Schema, inspecting type
mappings, generating a Great Expectations baseline, and running validation with
sample data.

[![Demo](https://github.com/easel/tablespec/raw/main/examples/tablespec-demo.gif)](https://github.com/easel/tablespec/blob/main/examples/tablespec-demo.cast)

**Play in your terminal:**

```bash
asciinema play examples/tablespec-demo.cast
```

**Run live** (requires `tablespec[spark]`):

```bash
uv run python examples/demo.py
```

**Watch with narration:**
[tablespec-demo-narrated.mp4](https://github.com/easel/tablespec/raw/main/examples/tablespec-demo-narrated.mp4)

## Happy path: ingested bronze from scratch

This demo shows the shortest path from a new source table to a governed
ingested bronze layer:

1. Inspect the source table schema with `SparkToUmfMapper`.
2. Review and adjust the generated UMF for source fidelity.
3. Compile SQL DDL and register the table.
4. Generate a Great Expectations baseline and run initial validation.

```bash
# Profile source table and produce UMF
uv run python -c "
from tablespec.profiling.spark_mapper import SparkToUmfMapper
from tablespec import save_umf_to_yaml

mapper = SparkToUmfMapper(spark)
umf = mapper.map_dataframe(source_df, table_name='claims_raw')
save_umf_to_yaml(umf, 'claims_ingested.yaml')
"

# Compile to SQL DDL
tablespec compile claims_ingested.yaml --format sql

# Generate GX baseline
tablespec gx baseline claims_ingested.yaml --output suites/claims_ingested.json
```

## Databricks bootstrap

For Databricks-hosted tables, use the native profiler to avoid Deequ
dependencies:

```python
from tablespec.profiling.native_profiler import NativeProfiler

profiler = NativeProfiler(spark)
profile = profiler.profile_table("catalog.schema.medical_claims")
umf = profiler.to_umf(profile, table_name="medical_claims")
```

The native profiler uses Spark SQL to collect statistics without requiring
Deequ or any additional dependencies beyond `tablespec[spark]`.
