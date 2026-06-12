---
title: Getting Started
weight: 1
next: /concepts
---

Install tablespec, load a UMF schema, and compile your first set of artifacts
in a few minutes.

## Install

tablespec is distributed via GitHub Pages. The `--index-url` flag is required.

```bash
# Using uv (recommended)
uv add tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/

# Using pip
pip install tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/
```

Add the `[spark]` extra only if you need PySpark-based profiling or validation:

```bash
uv add tablespec[spark] --index-url https://documentdrivendx.github.io/tablespec/simple/
```

## Load a UMF schema

UMF schemas are YAML files. Start with a simple one:

```yaml
# schema.yaml
version: "1.0"
table_name: medical_claims
description: Healthcare claims — source-faithful ingested bronze
columns:
  - name: claim_id
    data_type: VARCHAR
    length: 50
    description: Unique claim identifier
    nullable:
      MD: false
      MP: false
  - name: member_id
    data_type: VARCHAR
    length: 20
    description: Member identifier
    nullable:
      MD: false
      MP: false
  - name: service_date
    data_type: DATE
    description: Date of service
    nullable:
      MD: false
      MP: true
  - name: billed_amount
    data_type: DECIMAL
    precision: 12
    scale: 2
    description: Amount billed by provider
    nullable:
      MD: true
      MP: true
```

Load it in Python:

```python
from tablespec import load_umf_from_yaml

umf = load_umf_from_yaml("schema.yaml")
print(f"Table: {umf.table_name}")
print(f"Columns: {len(umf.columns)}")
```

## Compile artifacts

Generate SQL DDL, PySpark schema, and JSON Schema from the UMF:

```python
from tablespec import load_umf_from_yaml, generate_sql_ddl, generate_pyspark_schema, generate_json_schema

umf = load_umf_from_yaml("schema.yaml")

# SQL DDL
ddl = generate_sql_ddl(umf)
print(ddl)

# PySpark schema
pyspark_schema = generate_pyspark_schema(umf)

# JSON Schema
json_schema = generate_json_schema(umf)
```

## Generate a Great Expectations baseline

```python
from tablespec import load_umf_from_yaml
from tablespec.gx_baseline import BaselineExpectationGenerator

umf = load_umf_from_yaml("schema.yaml")
generator = BaselineExpectationGenerator(umf)
suite = generator.generate()
print(f"Generated {len(suite['expectations'])} expectations")
```

## Use the CLI

tablespec ships a CLI for common operations:

```bash
# Show help
tablespec --help

# Compile a UMF to SQL DDL
tablespec compile schema.yaml --format sql

# Validate a schema file
tablespec validate schema.yaml

# Show column type mappings
tablespec types schema.yaml
```

See [CLI Reference](/cli-reference/) for the full command list.

## Next steps

{{< cards >}}
  {{< card link="/concepts" title="Core Concepts" subtitle="Understand the UMF model, the raw/ingested/silver boundary, and how tablespec governs each layer." icon="academic-cap" >}}
  {{< card link="/cli-reference" title="CLI Reference" subtitle="All commands, flags, and output formats." icon="terminal" >}}
  {{< card link="/api-reference" title="API Reference" subtitle="Python API documentation generated from source." icon="code" >}}
{{< /cards >}}
