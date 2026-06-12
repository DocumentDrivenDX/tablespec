---
title: Getting Started
weight: 1
next: /concepts
---

Install tablespec, author a table spec, and compile your first artifacts.

## Install

tablespec is distributed via GitHub Pages. The `--index-url` flag is required.

```bash
# Using uv (recommended)
uv add tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/

# Using pip
pip install tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/
```

Add the `[spark]` extra only if you need PySpark-based profiling, JDBC
discovery, or DataFrame validation:

```bash
uv add tablespec[spark] --index-url https://documentdrivendx.github.io/tablespec/simple/
```

## Author a table spec

The canonical UMF format is a **split directory**: one `table.yaml` plus one
file per column under `columns/`. Build one from Python:

```python
from pathlib import Path

from tablespec import UMF, UMFLoader
from tablespec.ingestion.constants import PROVENANCE_COLUMNS

umf = UMF.model_validate({
    "version": "1.0",
    "table_name": "medical_claims",
    "canonical_name": "Medical Claims",
    "description": "Healthcare claims - source-faithful ingested bronze",
    "primary_key": ["claim_id"],
    "columns": [
        {"name": "claim_id", "data_type": "VARCHAR", "length": 50,
         "description": "Unique claim identifier", "nullable": {"MD": False, "MP": False}},
        {"name": "member_id", "data_type": "VARCHAR", "length": 20,
         "description": "Member identifier", "nullable": {"MD": False, "MP": False}},
        {"name": "service_date", "data_type": "DATE",
         "description": "Date of service", "nullable": {"MD": False, "MP": True}},
        {"name": "billed_amount", "data_type": "DECIMAL", "precision": 12, "scale": 2,
         "description": "Amount billed by provider", "nullable": {"MD": True, "MP": True}},
        # Provenance columns the ingest pipeline adds to every table.
        # `tablespec validate` requires them; JDBC discovery appends them for you.
        *(dict(col) for col in PROVENANCE_COLUMNS.values()),
    ],
})

UMFLoader().save(umf, Path("tables/medical_claims"))
```

This writes:

```
tables/medical_claims/
├── table.yaml
└── columns/
    ├── billed_amount.yaml
    ├── claim_id.yaml
    ├── member_id.yaml
    ├── service_date.yaml
    └── meta_*.yaml          # 8 provenance columns
```

Each file is small and diffs cleanly in review. `table.yaml`:

```yaml
canonical_name: Medical Claims
description: Healthcare claims - source-faithful ingested bronze
primary_key:
  - claim_id
table_name: medical_claims
version: '1.0'
```

`columns/claim_id.yaml`:

```yaml
column:
  data_type: VARCHAR
  description: Unique claim identifier
  length: 50
  name: claim_id
  nullable:
    MD: false
    MP: false
```

The `MD` / `MP` keys under `nullable` are arbitrary context labels (here,
healthcare lines of business). See
[Universal Metadata Format](/concepts/umf/) for the full model.

## Validate and inspect

```bash
tablespec validate tables/
tablespec info tables/medical_claims/
```

`validate` checks structure, column naming, expectation compatibility with
Great Expectations, relationship integrity, and pipeline completeness
(including the provenance columns above). It accepts split directories and
JSON files; legacy single-file YAML specs are refused with a pointer to the
migration helper.

## Generate artifacts

Each `generate` format writes to stdout so it can be piped:

```bash
tablespec generate tables/medical_claims/ -f sql > medical_claims.ddl.sql
tablespec generate tables/medical_claims/ -f pyspark > medical_claims_schema.py
tablespec generate tables/medical_claims/ -f json > medical_claims.schema.json
tablespec generate tables/medical_claims/ -f ingest > medical_claims.ingest.sql
```

The `ingest` format is the raw-to-ingested plan for Databricks/Delta: a raw
landing table DDL, a typed target DDL, and the `MERGE` transform between them.
See [Compiled artifacts](/concepts/artifacts/) for what each artifact contains.

## Emit a dbt project

```bash
tablespec emit tables/ out/dbt --backend dbt --dialect databricks
```

This materializes a complete dbt project — model SQL with the declared casts,
enforced contracts, sources, and profiles. Pass `--dialect duckdb` (the
default) to run it locally, or add `--run` to execute `dbt build` via
dbt-duckdb against the emitted project.

## Compile from Python

The same generators are available as functions. They take a plain dict (use
`model_dump`) and return the artifact:

```python
from pathlib import Path

from tablespec import (
    BaselineExpectationGenerator,
    UMFLoader,
    generate_json_schema,
    generate_pyspark_schema,
    generate_sql_ddl,
)

umf = UMFLoader().load(Path("tables/medical_claims"))
umf_data = umf.model_dump(mode="json", exclude_none=True)

ddl = generate_sql_ddl(umf_data)                 # Spark SQL CREATE TABLE (str)
schema_src = generate_pyspark_schema(umf_data)   # Python source for a StructType (str)
json_schema = generate_json_schema(umf_data)     # JSON Schema (dict)

expectations = BaselineExpectationGenerator().generate_baseline_expectations(umf_data)
print(f"{umf.table_name}: {len(umf.columns)} columns, {len(expectations)} baseline expectations")
```

Legacy single-file YAML specs can still be loaded in Python with
`load_umf_from_yaml(path)` — file paths only; the CLI does not accept them.

## On Databricks

If the tables already exist in a database, skip hand-authoring: point
tablespec at it over JDBC and it discovers one validated UMF per table —
columns and types from `INFORMATION_SCHEMA` plus the reflected Spark schema,
primary and foreign keys, and provenance columns included. Credentials are
never inlined; the spec carries only a `password_secret_ref` naming a secret
in the runtime's secret store.

The [Northwind demo notebooks](/demos/) run this end to end on a Databricks
cluster: provision SQL Server on the driver node, discover the whole database,
validate every spec, and land typed tables with staged validation reports —
Connect-safe on classic clusters and serverless alike.

## Next steps

{{< cards >}}
  {{< card link="/concepts" title="Core Concepts" subtitle="The UMF model, the raw/ingested/silver boundary, compiled artifacts, and the validation model." icon="academic-cap" >}}
  {{< card link="/cli-reference" title="CLI Reference" subtitle="All 21 commands with their options." icon="terminal" >}}
  {{< card link="/demos" title="Demos" subtitle="Northwind on Databricks, plus the local screencast demo." icon="play" >}}
{{< /cards >}}
