---
title: Compiled artifacts
weight: 3
---

tablespec compiles a UMF schema into multiple output formats. Each artifact
is derived deterministically from the same UMF source.

## SQL DDL

`generate_sql_ddl(umf)` produces a `CREATE TABLE` statement with typed columns,
nullable constraints, and comments from UMF descriptions.

```sql
CREATE TABLE medical_claims (
    claim_id    VARCHAR(50)     NOT NULL,
    member_id   VARCHAR(20)     NOT NULL,
    service_date DATE           NOT NULL,
    billed_amount DECIMAL(12,2)
);
```

## PySpark schema

`generate_pyspark_schema(umf)` returns a PySpark `StructType` that can be
passed directly to `spark.read.schema()` or used in DataFrame creation.

```python
from pyspark.sql.types import StructType
schema: StructType = generate_pyspark_schema(umf)
df = spark.read.schema(schema).parquet("s3://bucket/claims/")
```

## JSON Schema

`generate_json_schema(umf)` returns a JSON Schema document for validating
JSON payloads or API responses against the UMF contract.

## Great Expectations baseline

`BaselineExpectationGenerator(umf).generate()` returns a Great Expectations
expectation suite with deterministic expectations for every column:

- `expect_column_to_exist`
- `expect_column_values_to_not_be_null` (based on nullability per LOB)
- `expect_column_values_to_be_of_type` (type-specific)
- `expect_column_value_lengths_to_be_between` (for VARCHAR/CHAR)
- `expect_column_values_to_be_in_set` (for allowed_values rules)

## Artifact determinism

All artifacts are derived from the same UMF. If the UMF changes, the artifacts
regenerate to match. This makes UMF the single source of truth: the DDL,
the PySpark schema, and the validation suite are always consistent with the
declared contract.
