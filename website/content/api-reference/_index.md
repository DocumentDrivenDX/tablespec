---
title: API Reference
weight: 4
next: /demos
---

Python API documentation for tablespec.

API reference is generated from source by [FEAT-015](/). The generated docs
cover all public symbols exported from `tablespec.__init__` and the optional
`tablespec[spark]` surfaces.

## Public API

The top-level `tablespec` package exports the most commonly used symbols:

```python
# Always available (no Spark required)
from tablespec import (
    UMF,
    UMFColumn,
    Nullable,
    ValidationRules,
    load_umf_from_yaml,
    save_umf_to_yaml,
    generate_sql_ddl,
    generate_pyspark_schema,
    generate_json_schema,
)

# Available with tablespec[spark]
from tablespec import (
    SparkToUmfMapper,
    TableValidator,
)
```

## Core models

### `UMF`

The root Pydantic model representing a table schema.

| Field | Type | Description |
|-------|------|-------------|
| `version` | `str` | Schema format version (currently `"1.0"`). |
| `table_name` | `str` | Table name. |
| `description` | `str \| None` | Human-readable description. |
| `columns` | `list[UMFColumn]` | Ordered list of column definitions. |

### `UMFColumn`

A single column definition.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Column name (matches source). |
| `data_type` | `str` | UMF type: `VARCHAR`, `INTEGER`, `DECIMAL`, etc. |
| `length` | `int \| None` | Length for `VARCHAR`/`CHAR`. |
| `precision` | `int \| None` | Precision for `DECIMAL`. |
| `scale` | `int \| None` | Scale for `DECIMAL`. |
| `description` | `str \| None` | Column description. |
| `nullable` | `Nullable \| None` | Per-LOB nullability. |
| `validation_rules` | `ValidationRules \| None` | Optional constraints. |

### `Nullable`

Per-LOB nullability configuration.

| Field | Type | Description |
|-------|------|-------------|
| `MD` | `bool` | Nullable in Medicaid feed. |
| `MP` | `bool` | Nullable in Medicare feed. |
| `ME` | `bool \| None` | Nullable in Medicare Advantage feed. |

## I/O functions

### `load_umf_from_yaml(path)`

Load a UMF schema from a YAML file. Accepts both single-file and split-format
directories.

```python
umf = load_umf_from_yaml("schema.yaml")
umf = load_umf_from_yaml("schemas/medical_claims/")  # split format
```

### `save_umf_to_yaml(umf, path)`

Save a UMF schema to a YAML file.

```python
save_umf_to_yaml(umf, "schema.yaml")
```

## Schema generators

### `generate_sql_ddl(umf, lob="MD")`

Returns a SQL `CREATE TABLE` string.

### `generate_pyspark_schema(umf)`

Returns a PySpark `StructType`.

### `generate_json_schema(umf)`

Returns a JSON Schema dict.

## GX integration

| Symbol | Module | Description |
|--------|--------|-------------|
| `BaselineExpectationGenerator` | `tablespec.gx_baseline` | Generate GX suite from UMF. |
| `GXConstraintExtractor` | `tablespec.gx_constraint_extractor` | Extract UMF from GX suite. |
| `GXSchemaValidator` | `tablespec.gx_schema_validator` | Validate schemas using GX. |

## Spark-dependent surfaces

Available only with `tablespec[spark]`:

| Symbol | Module | Description |
|--------|--------|-------------|
| `SparkToUmfMapper` | `tablespec.profiling.spark_mapper` | Profile a DataFrame and produce UMF. |
| `TableValidator` | `tablespec.validation` | Validate a DataFrame against a UMF schema. |
