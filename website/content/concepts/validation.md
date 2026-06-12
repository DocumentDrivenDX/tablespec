---
title: Validation model
weight: 4
---

tablespec validates data against the spec with Great Expectations suites that
are generated, staged, and executed with correct verdicts on classic Spark
and on Spark Connect (including Databricks serverless).

## Baseline from the spec

`BaselineExpectationGenerator` deterministically derives expectations from
UMF metadata — structure, types, nullability per context, lengths, keys:

```python
from pathlib import Path
from tablespec import BaselineExpectationGenerator, UMFLoader

umf = UMFLoader().load(Path("tables/medical_claims"))
expectations = BaselineExpectationGenerator().generate_baseline_expectations(
    umf.model_dump(mode="json", exclude_none=True)
)
```

The same UMF always produces the same suite. The CLI counterpart is
`tablespec validation-sync`, which regenerates the baseline and reconciles it
with the committed suite — expectations marked `generated_from: baseline` are
updated, user customizations are preserved (`--dry-run` shows the plan,
`--clean-outdated` removes superseded baseline rules).

## Staged execution: raw vs. ingested

Data is validated at two stages, and each expectation is classified to one:

- **raw** — the landing table, where every column is a string. String-shape
  checks live here: castability (`expect_column_values_to_cast_to_type`),
  lengths, date formats, not-null.
- **ingested** — the typed table after the raw-to-ingested transform.
  Value-range and relationship checks live here.

Classification matters because the source kind changes what is sensible to
check: **typed sources (jdbc, parquet) land natively typed, so suites
composed for them carry no string-shape raw checks at all.** A `CAST` check
against a column that was never a string is noise; tablespec does not emit
it.

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

GX's Spark engine uses classic `pyspark.sql.functions`, which assert a JVM
`SparkContext`. On Spark Connect — Databricks serverless, Sail — there is no
JVM context, the assertion fails internally, and every data-scanning
expectation silently returns `success=False`. Silent wrong verdicts are the
worst failure mode a validator can have.

tablespec's suite executor routes around this: classic DataFrames go through
the GX Spark engine; Connect DataFrames go through a **native executor**
(`tablespec.validation.native_executor`) that re-implements every baseline
expectation type using only the DataFrame API, selecting the engine-correct
functions module from the DataFrame itself. Same suite, same result shape,
correct verdicts on both engines — and the native path fails closed:
an expectation it cannot evaluate is reported as an error, never as a silent
pass or fail.

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

`TableValidator` (requires `tablespec[spark]`) is the one-call wrapper: it
loads the spec, generates the suite, executes it, and returns a DataFrame of
validation errors — empty means clean:

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

The baseline covers what the spec declares. Richer rules enter the suite
from profiling results, or from an LLM review loop: generate a prompt with
`generate_validation_prompt`, then apply the model's JSON response with
`tablespec apply-response tables/medical_claims/ response.json` (use
`--dry-run` to inspect first). Applied expectations are tagged
`generated_from: llm` and survive later `validation-sync` runs.

## Scope

tablespec validates the ingested-bronze contract: presence, types,
nullability, declared constraints, and key integrity. Cross-source business
logic belongs to silver-layer models with their own specs — see
[Raw, ingested, and silver](/concepts/raw-ingested-silver/).
