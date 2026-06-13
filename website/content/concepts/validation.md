---
title: Validation model
weight: 4
---

This page is for readers who need to know what tablespec checks before data
moves beyond ingested bronze. tablespec validates source data against a UMF
source-table spec by generating Great Expectations suites. Those suites run in
stages: raw source records first, then the typed ingested table.

tablespec executes generated suites on classic Spark and on Spark Connect,
including Databricks serverless.

## Baseline from the spec

`BaselineExpectationGenerator` derives Great Expectations rules from UMF
metadata: table structure, column types, nullability per context, lengths, and
keys:

```python
from pathlib import Path
from tablespec import BaselineExpectationGenerator, UMFLoader

umf = UMFLoader().load(Path("tables/medical_claims"))
expectations = BaselineExpectationGenerator().generate_baseline_expectations(
    umf.model_dump(mode="json", exclude_none=True)
)
```

The same UMF always produces the same baseline suite. The CLI counterpart is
`tablespec validation-sync`, which regenerates baseline expectations and
reconciles them with the committed suite. Expectations marked
`generated_from: baseline` are updated. User customizations are preserved.
`--dry-run` shows the proposed changes, and `--clean-outdated` removes
superseded baseline rules.

## Staged execution: raw vs. ingested

tablespec validates data at two stages. Each expectation is assigned to one
stage:

- **raw** — the landing table, where every column is a string. String-shape
  checks live here: castability (`expect_column_values_to_cast_to_type`),
  lengths, date formats, not-null.
- **ingested** — the typed table after the raw-to-ingested transform. Value
  range and relationship checks live here.

Classification matters because the source kind changes what is sensible to
check. Typed sources such as JDBC and Parquet land natively typed, so
tablespec does not emit string-shape raw checks for them. A `CAST` check
against a column that was never a string is noise.

Preview the classification without executing anything:

```bash
tablespec preview tables/medical_claims/
```

```
Total: 13 (11 raw, 0 ingested, 0 redundant, 2 unknown)
```

Each expectation's `meta` carries `severity` (`critical`, `error`,
`warning`, `info`) and a `blocking` flag, so a failed warning can be recorded
while a failed critical check blocks the load.

## Connect-safe execution on Databricks serverless

Great Expectations (GX) has a Spark engine that uses classic
`pyspark.sql.functions`, which assert a JVM `SparkContext`. Spark Connect
runtimes such as Databricks serverless and Sail do not expose that JVM
context. In that environment, the assertion fails internally and data-scanning
expectations can silently return `success=False`.

tablespec routes around that engine mismatch. Classic DataFrames go through
the GX Spark engine. Spark Connect DataFrames go through a native executor
(`tablespec.validation.native_executor`) that implements every baseline
expectation type with the DataFrame API and selects the functions module from
the DataFrame itself. The same suite keeps the same result shape on both
engines. The native path fails closed: an expectation it cannot evaluate is
reported as an error, never as a silent pass or fail.

Staged execution routes raw expectations to the raw DataFrame and ingested
expectations to the typed one (from the Northwind demo notebook):

```python
from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.validation.gx_executor import GXSuiteExecutor

composer = BaselineExpectationGenerator()
executor = GXSuiteExecutor(spark)

expectations = composer.generate_baseline_expectations(
    umf.model_dump(mode="json", exclude_none=True)
)
staged = executor.execute_staged(raw_df, typed_df, expectations)
# staged.raw / staged.ingested -> per-expectation results with
# observed values and unexpected counts
```

## Validating a DataFrame against a spec

`TableValidator` requires `tablespec[spark]`. It is the one-call wrapper for
application code: it loads the UMF spec, generates the baseline suite,
executes it, and returns a DataFrame of validation errors. An empty error
DataFrame means the input passed validation:

```python
from tablespec import TableValidator

validator = TableValidator(spark)
# umf_path points at a single-file YAML spec (e.g. written with save_umf_to_yaml)
error_df = validator.validate_table(claims_df, umf_path, table_name="Medical_Claims")

if error_df.count() > 0:
    error_df.select("error_type", "severity", "column_name", "error_message").show()
```

The error rows follow `VALIDATION_ERROR_SCHEMA`, so results can be persisted
and reported like any other table.

## Adding rules beyond the baseline

The baseline suite covers what the UMF spec declares. Additional rules can
come from profiling results or from an LLM review loop. Generate a prompt
with `generate_validation_prompt`, then apply the model's JSON response with
`tablespec apply-response tables/medical_claims/ response.json`. Use
`--dry-run` before writing. Applied expectations are tagged
`generated_from: llm` and survive later `validation-sync` runs.

## Scope

tablespec validates the ingested-bronze contract: presence, types,
nullability, declared constraints, and key integrity. Cross-source business
logic belongs to silver-layer models with their own specs — see
[Raw, ingested, and silver](/concepts/raw-ingested-silver/).
