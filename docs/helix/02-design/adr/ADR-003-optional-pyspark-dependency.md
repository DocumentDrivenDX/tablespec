# ADR-003: PySpark Is an Optional Dependency Isolated to Specific Modules

## Status

Accepted — extended by ADR-010 (Spark Connect / serverless runtime model). The optional-dependency boundary still holds; ADR-010 adds that, *when* PySpark is present, no Spark-touching path may assume a classic JVM `SparkContext` (Connect / serverless are first-class).

## Context

PySpark is a large dependency (~300 MB) with its own JVM runtime requirement. The tablespec library provides a range of functionality -- UMF model validation, schema generation, type mappings, Great Expectations baseline generation, LLM prompt generation -- most of which is pure Python and does not require Spark. Only two specific features need PySpark: profiling Spark DataFrames and validating DataFrames against UMF specs.

Requiring PySpark as a mandatory dependency would significantly increase install size and complexity for users who only need the core schema tooling, and would make the library unusable in environments where a JVM is unavailable (e.g., lightweight CI containers, serverless functions, or developer laptops without Java).

## Decision

PySpark is an optional dependency, installable via `pip install tablespec[spark]`. Spark-dependent code is isolated to specific modules, and the rest of the library functions without PySpark installed.

The isolation is implemented at multiple levels:

1. **Dependency declaration** (`pyproject.toml`): PySpark is declared under `[project.optional-dependencies]` as `spark = ["pyspark>=3.5.0"]`, not in the base `dependencies` list.

2. **Conditional imports** (`__init__.py`): `SparkToUmfMapper` and `TableValidator` are imported inside a `try/except ImportError` block. They are added to `__all__` only when PySpark is available. All other exports (UMF models, schema generators, type mappings, GX baseline, prompt generators) are unconditional.

3. **Type checking exclusion** (`pyrightconfig.json`): The two Spark-dependent modules are listed in the `ignore` array:
   - `src/tablespec/profiling/spark_mapper.py`
   - `src/tablespec/validation/table_validator.py`

   This prevents pyright from reporting missing PySpark type stubs in CI environments where PySpark is not installed.

4. **Module boundaries**: Spark-dependent code lives exclusively in `profiling/spark_mapper.py` (Spark DataFrame profiling) and `validation/table_validator.py` (DataFrame validation). No other module imports PySpark directly.

## Consequences

### Positive

- The core library installs quickly with minimal dependencies (pydantic, pyyaml, great-expectations), making it suitable for lightweight environments.
- Users who only need schema generation, UMF validation, or GX baseline expectations are not burdened with PySpark and JVM setup.
- CI pipelines for non-Spark features run faster without needing to install PySpark.
- The isolation boundary is clear and enforced by both the import pattern and the type checker configuration.

### Negative

- Users who attempt to use `SparkToUmfMapper` or `TableValidator` without installing the `[spark]` extra receive an `ImportError` (or simply find the classes absent from the module namespace) rather than a descriptive installation prompt.
- The pyright `ignore` list must be manually maintained; adding new Spark-dependent modules requires updating `pyrightconfig.json`.
- Test coverage for Spark-dependent modules requires a separate test environment with PySpark installed (the `[spark]` extra), adding complexity to the CI matrix.
- Developers must be disciplined about not importing PySpark in non-Spark modules, as there is no automated enforcement beyond pyright's ignore list and the conditional import pattern.

## Evolution

Two changes since this ADR was accepted refine, but do not overturn, the optional-dependency boundary:

1. **Connect / serverless is first-class (ADR-010).** Spark-dependent modules grew beyond `spark_mapper.py` and `table_validator.py` to include `session.py`, `casting_utils.py`, the native profiler, and the Connect-safe GX executor (`validation/gx_executor.py` + `validation/native_executor.py`). All remain gated behind the `[spark]` extra and lazy imports, but they may NOT assume a JVM `SparkContext` — engine-correct behavior is keyed off the DataFrame/session in hand and per-session capability probes (PRD FR-20.x). The native profiler and native GX executor exist precisely so the `[spark]` features work on serverless / Spark Connect where the classic `SparkContext`-bound paths (PyDeequ, GX `add_spark`) fail silently.

2. **dbt and pysail are dev-group, not user extras.** `dbt` and `pysail` live in the dev / test group — not `[project.optional-dependencies]` — because user runtimes consume *committed* dbt/SQL/LDP artifacts and never import tablespec, dbt, or pysail at run time. `pysail` backs the local Sail (Spark Connect) test lane. This keeps the user-facing optional surface to the single `[spark]` extra (principle 5).
