---
title: Universal Metadata Format
weight: 2
---

Universal Metadata Format (UMF) is tablespec's source-table contract. A UMF
spec records the table name, column names, source data types, nullability,
keys, relationships, source declaration, and validation expectations.

This page is for readers who need to author or review UMF files. Every
tablespec operation starts by loading a UMF spec and validating it with
Pydantic models.

## Formats

**Split directory (canonical).** One `table.yaml` file stores table-level
metadata. One file per column lives under `columns/`. This is the
review-friendly editing format because a column change is a one-file diff:

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

**JSON (artifact standard).** A JSON UMF file stores the whole table contract
in one `.json` document. Compiled pipelines can consume this single-file
artifact. `tablespec convert` translates between split directories and JSON,
and `UMFLoader` auto-detects both formats.

**Single-file YAML (legacy).** Older whole-UMF YAML documents are loadable
from Python via `load_umf_from_yaml`, but the CLI refuses them and points at
the explicit migration helper.

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

The PySpark schema generator targets the **raw** stage: the landing table that
captures source records before tablespec casts them. In that raw stage, dates
land as strings and are cast during ingest. That is why `DATE` maps to
`StringType()` in the raw PySpark schema but to `DATE` in the typed SQL DDL.
The [validation model](/concepts/validation/) follows the same raw/typed split.

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
multiple UMF specs are present. The dbt and Lakeflow emitters turn declared
keys into generated tests and expectations.

## Expectations

Quality rules live in an expectation suite. In tablespec, an expectation is a
Great Expectations rule plus metadata that says where it runs (`stage`), how
serious failure is (`severity`), whether it blocks a load (`blocking`), and
where it came from (`generated_from`). In split format, column-scoped
expectations are stored in the column's file under `validations:`; table-level
expectations live in `expectations.yaml`:

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

The column model does not have a separate `validation_rules` or
`allowed_values` field. Constraints are expectations. They can be generated
from the UMF metadata as the baseline suite, inferred from profiling, added
from an LLM response through `tablespec apply-response`, or written by hand.

## Source declaration

A UMF spec may declare where its rows come from with a `source:` block. The
`kind` field says whether the source is `delimited`, `parquet`, or `jdbc`.
When `source:` is absent, tablespec treats the table as a delimited flat file
described by `file_format`.

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
- **The source kind drives validation.** Typed sources such as JDBC and
  Parquet land natively typed, so their generated suites do not include
  string-shape raw checks. See [staged validation](/concepts/validation/).

## Ingestion

The optional `ingestion` block controls how tablespec generates the
raw-to-ingested transform. It can declare `mode` (for example,
`incremental`), `order_by` for dedup-latest windows, pre-upsert exclusions,
and post-upsert rules. `tablespec generate -f ingest` and the dbt emitter use
this block.

## Provenance columns

Every pipeline-complete UMF spec carries eight `meta_*` provenance columns
such as `meta_source_name`, `meta_load_dt`, and `meta_checksum`. The ingest
pipeline populates these columns on every row so a downstream reader can trace
where the row came from and when it was loaded. `tablespec validate` requires
the provenance columns; spec-producing flows such as JDBC discovery append
them automatically. The canonical list is
`tablespec.ingestion.constants.PROVENANCE_COLUMNS`.
