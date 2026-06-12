---
ddx:
  id: ADR-003
---

# ADR-003: PySpark Is an Optional Dependency Isolated to Specific Modules

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | ADR-010 | High |

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

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Make PySpark mandatory | One dependency story; no lazy import branches | Burdens non-Spark users and breaks environments without a JVM | Rejected: the core library is mostly pure Python and should remain importable without Spark |
| Split the Spark features into a separate distribution | Clear packaging boundary | More package/version management, more documentation drift, and a worse user experience for mixed core + Spark usage | Rejected: the current optional-extra boundary is simpler and already works |
| **Keep PySpark optional and isolate it to Spark-touching modules (selected)** | Core stays lightweight; Spark users opt in explicitly; the import boundary is testable | Spark modules need conditional imports and separate test coverage | **Selected: this preserves the broadest usable surface while keeping Spark-specific code honest** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| A non-Spark import path accidentally pulls in PySpark | M | H | Keep the lazy-import boundary in `__init__.py` and extend the import tests when Spark modules are added |
| The `pyrightconfig.json` ignore list drifts as Spark modules move | M | M | Treat the ignore list as part of the Spark boundary and update it whenever Spark-touching modules are introduced |
| Users see `ImportError` instead of a guided install message | M | L | Keep the optional dependency surface narrow and document the `[spark]` extra in the public docs |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `import tablespec` works without the `[spark]` extra in `tests/unit/test_output_formatting.py` and related import-path tests | A new non-Spark import starts requiring PySpark |
| Spark-dependent modules continue to load and execute with the `[spark]` extra installed | A new Spark module is added without the conditional import pattern |
| pyright stays green with Spark modules ignored as intended | The ignore list no longer matches the actual Spark-touching surface |

## Supersession

- **Supersedes**: None
- **Superseded by**: ADR-010 extends the boundary to connect/serverless semantics; this ADR remains the dependency boundary.

## Concern Impact

- **Concern selection**: Optional heavy dependency boundary for the library's Spark surface.
- **Practice override**: None.

## References

- `pyproject.toml`
- `src/tablespec/__init__.py`
- `pyrightconfig.json`
- `tests/unit/test_output_formatting.py`, `tests/unit/test_casting_utils.py`, `tests/unit/test_profiling_mappers.py`

## Review Checklist

- [x] Context names a specific problem — Spark should not be mandatory for the whole library
- [x] Decision statement is actionable — PySpark stays optional and localized
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with ADR-010's runtime boundary
