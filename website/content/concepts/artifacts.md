---
title: Compiled artifacts
weight: 3
---

This page is for readers who need to know what files tablespec generates and
why those files should be reviewed. A compiled artifact is a file generated
from a Universal Metadata Format (UMF) source-table spec: SQL, schema code,
validation suites, dbt project files, Lakeflow project files, Excel review
workbooks, static guidebooks, or a manifest.

tablespec compiles one UMF spec into a reusable catalog of generated files.
Every generated file is derived from the same spec. Recompiling an unchanged
spec produces the same output, so SQL DDL, schemas, validation suites, and
emitted projects do not drift apart.

## Reusable catalog of generated files

A full compile produces these generated files for each table:

| Artifact | Producer | File |
|----------|----------|------|
| UMF snapshot | the spec the compile ran against | `umf/<table>.umf.yaml` |
| Ingest SQL | `generate_ingest_sql` | `ingest/<table>.ingest.sql` |
| SQL DDL | `generate_sql_ddl` | `schemas/<table>.ddl.sql` |
| PySpark schema source | `generate_pyspark_schema` | `schemas/<table>.schema.py` |
| JSON Schema | `generate_json_schema` | `schemas/<table>.schema.json` |
| GX baseline suite | `BaselineExpectationGenerator` | `validation/<table>.suite.json` |
| Key-candidate evidence | profiling (optional) | `validation/<table>.keycandidates.json` |
| dbt ingest project | `generate_dbt_project` | `dbt_ingest/<table>/` |
| Excel review workbook | `UMFToExcelConverter` | `excel/<table>.xlsx` |

A compile for a set of related tables also produces these generated files:

| Artifact | Producer | Location |
|----------|----------|----------|
| dbt gold DAG project | `generate_dbt_dag_project` | `dbt_gold/` |
| Lakeflow Declarative Pipelines project | `tablespec.ldp.generate_ldp_project` | `ldp/` (`raw_<t>.sql`, `ingested_<t>.sql`, `gold_<t>.sql`) |
| Guidebook site | `tablespec.guidebook.generate` | `guidebook/` (`index.html`, one page per table, `search_index.json`) |
| Manifest | compile orchestrator | `manifest.json` — every persisted path, so consumers never re-derive filenames |

`tablespec.e2e.manifest` pins this layout in tests. `bootstrap_from_tables`
writes the layout when compiling from live Spark tables. Each generated file
is also available through `tablespec generate`, `tablespec emit`, or the
corresponding Python function.

## SQL DDL

`generate_sql_ddl(umf_data)` produces a Spark SQL `CREATE TABLE` statement
for the **typed ingested table**: the table after raw source records have
been cast into declared types. `VARCHAR` becomes `STRING`, and column
descriptions become `COMMENT` clauses. Actual output for a four-column
claims spec:

```sql
-- DDL for medical_claims
-- Generated from UMF specification

CREATE TABLE medical_claims (
    billed_amount DECIMAL(12,2) COMMENT 'Amount billed by provider',
    claim_id STRING NOT NULL COMMENT 'Unique claim identifier',
    member_id STRING NOT NULL COMMENT 'Member identifier',
    service_date DATE NOT NULL COMMENT 'Date of service'
)
COMMENT 'Healthcare claims - source-faithful ingested bronze'
;
```

## Ingest SQL

`generate_ingest_sql(umf_data)` (CLI: `tablespec generate -f ingest`) emits
the raw-to-ingested SQL plan for Databricks/Delta. The generated SQL includes
a raw landing table, the typed ingested target table, and the transform
between them. The raw landing table stores source values as `STRING` plus
`_source_file` and `_load_ts` audit columns. With a primary key and
incremental mode, the transform is a `MERGE` with a dedup-latest window:

```sql
-- 3. Raw -> ingested transform
MERGE INTO ingested_medical_claims AS tgt
USING (
    SELECT
        cast(nullif(trim(regexp_replace(billed_amount, '^\\$', '')), '') as DECIMAL(12,2)) AS billed_amount,
        claim_id                                                                           AS claim_id,
        member_id                                                                          AS member_id,
        cast(try_to_timestamp(service_date) as date)                                       AS service_date
    FROM (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY claim_id ORDER BY _load_ts DESC) AS _rn
            FROM raw_medical_claims
        ) WHERE _rn = 1
    ) src_raw
) AS src
ON tgt.claim_id = src.claim_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;
```

## PySpark schema

`generate_pyspark_schema(umf_data)` returns **generated Python source code**
that defines a `StructType` — an artifact you commit and import, not a
runtime object. It targets the raw read, where dates still arrive as source
strings, so `DATE` columns are `StringType()` and are cast during ingest:

```python
medical_claims_schema = StructType([
    StructField("billed_amount", DecimalType(), True),
    StructField("claim_id", StringType(), False),
    StructField("member_id", StringType(), False),
    StructField("service_date", StringType(), False)
])
```

(For an actual `StructType` object at runtime, install the spark extra and
call `map_to_pyspark_type_obj`.)

## JSON Schema

`generate_json_schema(umf_data)` returns a JSON Schema (draft-07) document.
Use it when another service needs to validate JSON payloads against the same
UMF table contract.

## Great Expectations baseline

`BaselineExpectationGenerator().generate_baseline_expectations(umf_data)`
returns a deterministic list of Great Expectations rule dictionaries. The
generator emits these rule types when the UMF spec declares the matching
metadata:

- `expect_table_column_count_to_equal` and
  `expect_table_columns_to_match_ordered_list` (structural)
- `expect_column_values_to_not_be_null` (from nullability, per context)
- `expect_column_values_to_cast_to_type` (typed columns at the raw stage)
- `expect_column_value_lengths_to_be_between` (from `length`)
- `expect_column_values_to_match_strftime_format` (date/datetime formats)
- `expect_column_values_to_be_unique` (from `primary_key`)
- `expect_column_values_to_be_in_set`, `expect_column_values_to_be_between`
  (from declared value constraints)
- `expect_column_pair_values_a_to_be_greater_than_b` (from ordered column
  pairs)

Each expectation carries `meta` with severity, stage, and
`generated_from: baseline`. Later syncs use that metadata to distinguish
baseline rules from user customizations. See the
[validation model](/concepts/validation/) for how suites execute.

## dbt and Lakeflow projects

`tablespec emit --backend dbt` writes a runnable dbt project. The project
contains model SQL with declared casts, enforced contracts (`data_type` per
column), not-null constraints and uniqueness tests from the spec,
`sources.yml`, and `profiles.yml`. `--dialect databricks` emits Spark-family
cast SQL; `--dialect duckdb` (default) runs locally. `--run` executes
`dbt build` through dbt-duckdb.

The Lakeflow emitter writes Databricks Lakeflow Declarative Pipelines files:
a raw streaming table, a typed ingested dataset with expectations, and gold
datasets. Use this artifact when the pipeline should run natively on
Databricks.

## Excel workbooks and guidebooks

`tablespec export-excel` writes a review workbook for a UMF table. The
workbook includes dropdown validations and a machine-readable `Derivations`
sheet, so column derivation candidates, SQL expressions, row filters, order
fields, join-via definitions, survivorship strategy, and defaults can
round-trip back into UMF. Long dropdowns are stored as hidden-sheet ranges
instead of inline Excel formulas, avoiding the 255-character data-validation
limit.

`tablespec guidebook tables/ -o guidebook/` renders a directory of UMFs into a
static HTML guidebook. It discovers split `table.yaml` directories and
`.umf.json` artifacts, writes one self-contained page per table, builds a
search index, and shows cross-table lineage: foreign keys as downstream
consumers and derivations as upstream source columns with SQL and
survivorship detail.
