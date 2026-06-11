---
ddx:
  id: ADR-006
---

# ADR-006: GX DuckDB Test Backend

## Status

Accepted (spike completed 2026-03-17)

## Context

Testing GX expectations currently requires PySpark, which brings JVM startup cost, cluster configuration, and heavyweight dependencies. This makes test iteration slow and prevents running GX-based tests in lightweight CI environments.

Great Expectations supports three execution engines:

- **Pandas**: Pure Python, lightweight.
- **Spark**: Production-accurate but heavyweight.
- **SqlAlchemy**: SQL semantics, but DuckDB dialect has compatibility gaps with GX's metric bundling.

GX does NOT support Polars as an execution engine.

## Decision

Use a **hybrid DuckDB + GX Pandas** approach for lightweight test and non-Spark validation:

1. **DuckDB** for fast data loading and SQL-based transformations (raw/ingested stage simulation).
2. **GX Pandas execution engine** for expectation evaluation against the resulting DataFrames.

### Spike Results

The proof-of-concept spike (2026-03-17) found:

- **GX SqlAlchemy + DuckDB: DOES NOT WORK.** GX 1.15.1's `SqlAlchemyExecutionEngine.resolve_metric_bundle` hits `IndexError: list index out of range` when executing bundled metric queries against DuckDB. The DuckDB SqlAlchemy dialect works for basic SQL, but GX's internal metric batching is incompatible.

- **DuckDB → Pandas DataFrame → GX Pandas engine: WORKS PERFECTLY.** The pattern:
  1. Load data with `duckdb.connect()` and `con.execute(...).df()` to get a Pandas DataFrame.
  2. Hand the DataFrame to GX via `context.data_sources.add_pandas()` + `add_dataframe_asset()`.
  3. Run expectations against the Pandas batch.

All tested expectation types (`expect_column_values_to_not_be_null`, `expect_column_values_to_be_in_set`, `expect_column_value_lengths_to_be_between`) work correctly with proper pass/fail behavior.

### Raw vs Ingested Stage Handling

- **Raw stage**: `duckdb.execute("SELECT * FROM read_csv('data.csv', all_varchar=true)").df()` — all columns as VARCHAR strings, matching Bronze.Raw semantics.
- **Ingested stage**: `duckdb.execute("SELECT TRY_CAST(col AS INTEGER) ... FROM ...")` — cast failures become NULL, detectable as validation errors matching Bronze.Ingested semantics.

### Dependency

`duckdb` and `duckdb-engine` packaged under `tablespec[duckdb]` optional extra. Not a core dependency, consistent with ADR-003's approach to optional heavyweight dependencies.

## Consequences

### Positive

- Sub-second GX test execution without JVM startup.
- DuckDB handles data loading/transformation efficiently (Parquet, CSV, SQL).
- Enables FEAT-016 test harness and FEAT-023 `tablespec preview --against` command.
- pip-installable with no system dependencies beyond Python.

### Negative

- Pandas execution engine has different null handling and type coercion from Spark — not semantically identical.
- Two-step pattern (DuckDB load → Pandas GX) is more complex than direct SqlAlchemy would have been.
- Tests passing on Pandas do not guarantee identical behavior on Spark — integration tests with Spark remain necessary for production confidence.
- Adds another optional dependency group to manage.
