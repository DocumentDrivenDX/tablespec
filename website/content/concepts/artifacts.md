---
title: Compiled artifacts
weight: 3
---

tablespec compiles a UMF spec into the artifacts a pipeline actually runs.
Every artifact is derived deterministically from the same spec: recompiling
an unchanged spec produces the same output, so the DDL, the schemas, the
validation suite, and the emitted projects cannot drift apart.

## The compiled set

A full compile produces, per table:

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

plus, per table set:

| Artifact | Producer | Location |
|----------|----------|----------|
| dbt gold DAG project | `generate_dbt_dag_project` | `dbt_gold/` |
| Lakeflow Declarative Pipelines project | `tablespec.ldp.generate_ldp_project` | `ldp/` (`raw_<t>.sql`, `ingested_<t>.sql`, `gold_<t>.sql`) |
| Manifest | compile orchestrator | `manifest.json` — every persisted path, so consumers never re-derive filenames |

This layout is pinned by `tablespec.e2e.manifest`; `bootstrap_from_tables`
writes it when compiling from live Spark tables. Individually, each artifact
is also available via `tablespec generate` / `tablespec emit` or the
corresponding Python function.

## SQL DDL

`generate_sql_ddl(umf_data)` produces a Spark SQL `CREATE TABLE` for the
**typed** (ingested) table — `VARCHAR` becomes `STRING`, descriptions become
`COMMENT` clauses. Actual output for a four-column claims spec (the header
also carries a source-file timestamp for provenance):

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
the full raw-to-ingested plan for Databricks/Delta: a raw landing table
(all `STRING` plus `_source_file` / `_load_ts` audit columns), the typed
target table, and the transform between them. With a primary key and
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
runtime object. It targets the raw read, so `DATE` columns are
`StringType()` (dates are cast during ingest):

```python
medical_claims_schema = StructType([
    StructField("billed_amount", DecimalType(), True),
    StructField("claim_id", StringType(), False),
    StructField("member_id", StringType(), False),
    StructField("service_date", StringType(), False)
])
```

(For an actual `StructType` object at runtime, the spark extra provides
`map_to_pyspark_type_obj`.)

## JSON Schema

`generate_json_schema(umf_data)` returns a JSON Schema (draft-07) document —
useful for validating JSON payloads against the contract.

## Great Expectations baseline

`BaselineExpectationGenerator().generate_baseline_expectations(umf_data)`
returns a deterministic list of expectation dicts. The types it emits,
depending on what the spec declares:

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
`generated_from: baseline` so later syncs can tell baseline rules from user
customizations. See the [validation model](/concepts/validation/) for how
suites execute.

## dbt and Lakeflow projects

`tablespec emit --backend dbt` materializes a runnable dbt project: model SQL
applying the declared casts, enforced contracts (`data_type` per column),
not-null constraints and uniqueness tests from the spec, `sources.yml`, and
`profiles.yml`. `--dialect databricks` emits Spark-family cast SQL;
`--dialect duckdb` (default) runs locally — `--run` executes `dbt build` via
dbt-duckdb.

The Lakeflow (LDP) emitter generates the same pipeline as Lakeflow
Declarative Pipelines datasets — a raw streaming table, the typed ingested
dataset with expectations, and gold datasets — for running natively on
Databricks.
