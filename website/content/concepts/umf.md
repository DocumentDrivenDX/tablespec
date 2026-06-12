---
title: Universal Metadata Format
weight: 2
---

Universal Metadata Format (UMF) is the schema format at the heart of
tablespec. Every tablespec operation begins with a UMF spec, validated by
Pydantic models.

## Formats

**Split directory (canonical).** One `table.yaml` for table-level metadata
plus one file per column under `columns/`. This is the git-friendly editing
format — a column change is a one-file diff:

```
tables/medical_claims/
├── table.yaml            # name, description, keys, relationships
├── expectations.yaml     # table-level expectations
└── columns/
    ├── claim_id.yaml     # one file per column
    ├── member_id.yaml
    └── ...
```

```yaml
# table.yaml
canonical_name: Medical Claims
description: Healthcare claims - source-faithful ingested bronze
primary_key:
  - claim_id
table_name: medical_claims
version: '1.0'
```

```yaml
# columns/claim_id.yaml
column:
  data_type: VARCHAR
  description: Unique claim identifier
  length: 50
  name: claim_id
  nullable:
    MD: false
    MP: false
```

**JSON (artifact standard).** The whole UMF as a single `.json` file — what
compiled pipelines consume. `tablespec convert` translates between the two,
and `UMFLoader` auto-detects them.

**Single-file YAML (legacy).** Whole-UMF YAML documents are loadable from
Python via `load_umf_from_yaml`, but the CLI refuses them and points at the
explicit migration helper.

## Column types

`data_type` is one of: `VARCHAR`, `CHAR`, `TEXT`, `INTEGER`, `DECIMAL`,
`FLOAT`, `DATE`, `DATETIME`, `TIMESTAMP`, `BOOLEAN`. Sized types use
`length` (VARCHAR/CHAR), and `precision`/`scale` (DECIMAL).

| UMF type | Spark SQL DDL | PySpark raw schema |
|----------|---------------|--------------------|
| `VARCHAR`, `CHAR`, `TEXT` | `STRING` | `StringType()` |
| `INTEGER` | `INTEGER` | `IntegerType()` |
| `DECIMAL` | `DECIMAL(p,s)` | `DecimalType()` |
| `FLOAT` | `FLOAT` | `FloatType()` |
| `DATE` | `DATE` | `StringType()` — see below |
| `DATETIME`, `TIMESTAMP` | `DATETIME` / `TIMESTAMP` | `TimestampType()` |
| `BOOLEAN` | `BOOLEAN` | `BooleanType()` |

The PySpark schema generator targets the **raw** stage, where everything —
including dates — lands as strings and is cast during ingest. That is why
`DATE` maps to `StringType()` there but to `DATE` in the typed DDL. The
[validation model](/concepts/validation/) follows the same raw/typed split.

## Nullability per context

`nullable` maps **arbitrary context keys** to booleans (the model is
`extra="allow"` — any domain works). In healthcare specs the common keys are
`MD` (Medicaid), `MP` (Medicare Part D), and `ME` (Medicare):

```yaml
nullable:
  MD: false   # required in the Medicaid feed
  MP: true    # sometimes omitted in the Medicare Part D feed
```

A spec can name the column that determines which context applies to each
row via `context_column` on the table. Context-dependent nullability
compiles to conditional not-null expectations instead of blanket constraints.

## Keys and relationships

```yaml
# table.yaml
primary_key:
  - claim_id
unique_constraints:
  - [member_id, service_date]
relationships:
  foreign_keys:
    - column: member_id
      references_table: members
      references_column: member_id
```

`tablespec validate` checks relationship integrity automatically when
multiple tables are present, and the dbt/Lakeflow emitters turn declared
keys into tests and expectations.

## Expectations

Quality rules live in a unified expectation suite — Great Expectations
types with structured metadata (`stage`, `severity`, `blocking`,
`generated_from`). In split format, column-scoped expectations are stored in
the column's file under `validations:`; table-level ones in
`expectations.yaml`:

```yaml
# columns/claim_id.yaml (continued)
validations:
  - type: expect_column_values_to_match_regex
    kwargs:
      column: claim_id
      regex: ^C[0-9]+$
    meta:
      severity: warning
      stage: raw
      generated_from: llm
```

Note there is no per-column `validation_rules` or `allowed_values` field on
the column model itself — constraints are expectations, generated from the
spec (baseline), from profiling, from an LLM (via `tablespec
apply-response`), or by hand.

## Source declaration

A UMF may declare where its rows come from via a discriminated `source:`
block (`kind: delimited | parquet | jdbc`). When absent, the table is treated
as a delimited flat file described by `file_format`.

```yaml
source:
  kind: jdbc
  url: jdbc:sqlserver://localhost:1433;databaseName=northwind
  dbtable: dbo.Orders
  driver: com.microsoft.sqlserver.jdbc.SQLServerDriver
  user: reader
  password_secret_ref: NORTHWIND_PASSWORD   # a *reference*, never the secret
```

Two properties matter here:

- **Credentials are never inlined.** `JdbcSource` rejects a literal
  `password` field (`extra="forbid"`); `password_secret_ref` names a secret
  in the runtime's secret store (an env var, a Databricks secret scope).
- **The source kind drives validation.** Typed sources (jdbc, parquet) land
  natively typed, so suites composed for them carry no string-shape raw
  checks. See [staged validation](/concepts/validation/).

## Ingestion

The optional `ingestion` block controls how the raw-to-ingested transform is
generated: `mode` (e.g. incremental), `order_by` for dedup-latest
windows, pre-upsert exclusions, and post-upsert rules. It feeds
`tablespec generate -f ingest` and the dbt emitter.

## Provenance columns

Every pipeline-complete spec carries eight `meta_*` provenance columns
(`meta_source_name`, `meta_load_dt`, `meta_checksum`, ...) that the ingest
pipeline populates on every row. `tablespec validate` requires them;
spec-producing flows such as JDBC discovery append them automatically. The
canonical list is `tablespec.ingestion.constants.PROVENANCE_COLUMNS`.
