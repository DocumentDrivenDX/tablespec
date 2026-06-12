---
ddx:
  id: ADR-006
---

# ADR-006: GX DuckDB Test Backend

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | ADR-003 | High |

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

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep GX tests on Spark only | Maximum semantic fidelity to production | Heavy JVM dependency and slow iteration make lightweight CI harder | Rejected: the point of this backend is to make validation cheaper to run |
| Use DuckDB through GX SqlAlchemy | One database-backed path | GX 1.15.1's DuckDB SqlAlchemy path fails in metric-bundle resolution | Rejected: the upstream GX/DuckDB gap makes this unreliable |
| **DuckDB load + pandas GX engine (selected)** | Fast iteration; lightweight; works today with the supported GX expectations | Semantic differences from Spark and a two-step evaluation flow | **Selected: this is the working lightweight validation path until GX grows a better DuckDB integration** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Pandas semantics drift from Spark semantics | M | M | Keep Spark integration tests as the production oracle and treat this backend as a lightweight test lane |
| A future GX upgrade changes pandas execution behavior | M | M | Pin the tested GX release range and keep the spike tests pinned to the documented expectations |
| The DuckDB dependency surface grows beyond the intended lightweight lane | L | L | Keep it as an optional extra and limit the backend to test code paths |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `tests/unit/test_gx_duckdb_spike.py` continues to pass for the documented expectation types | A GX or DuckDB upgrade changes the spike result shape or breaks the working fallback |
| DuckDB-backed validation remains available without pulling Spark into the test lane | The backend starts depending on Spark-specific behavior |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **No concern impact**: This ADR selects a test backend; it does not override a library concern practice.

## References

- `tests/unit/test_gx_duckdb_spike.py`
- `tests/unit/test_gx_processor.py`
- `tests/unit/test_expectation_suite.py`

## Review Checklist

- [x] Context names a specific problem — GX validation is too heavy for lightweight CI
- [x] Decision statement is actionable — use DuckDB plus the pandas engine
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with the lightweight GX test lane
