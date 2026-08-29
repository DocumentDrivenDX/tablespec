---
name: tablespec
description: Working with tablespec and Universal Metadata Format (UMF) table schemas - bootstrapping UMF from Spark/Databricks tables, profiling, validation expectations, sample data, Excel table specs, and Spark/LDP/dbt pipeline artifacts. Use when a task involves UMF YAML/JSON, the tablespec CLI or Python API, or Databricks table-spec workflows.
---

# Tablespec

Use this skill as a routing layer. Prefer the documented public workflow first,
then drop to internals only when the task explicitly requires it. Do not duplicate
the project's requirements or design docs here; read them when changing
requirements. (The tablespec repository keeps HELIX-style specs under
`docs/helix/`; other projects will have their own location.)

## Default Workflow

1. Read the local code and governing spec before changing behavior.
2. Track implementation work in whatever the project uses. If the repository
tracks work with DDx beads (a `.ddx/` directory exists), use the `ddx` skill for
bead create, claim, close, worker, and review commands; otherwise use the
project's normal issue tracker.
3. Keep user-facing examples on public APIs and commands. Internal modules may be
composable, but should not be the first path shown to users or coding agents.
4. When adding or changing behavior, add a command-based acceptance test and cite
the relevant spec or tracked issue in the implementation notes.

## Databricks Bootstrap

Use the one-shot bootstrap facade once it exists. Until then, the current
composition is:

```python
from tablespec.e2e.paths import umfs_from_tables
from tablespec.e2e.compile import compile_umfs

umfs, suites = umfs_from_tables(spark, ["catalog.schema.table"], profile=True)
artifacts = compile_umfs(
    umfs,
    "/dbfs/tmp/tablespec-bootstrap",
    source="tables",
    profile_enriched=True,
    dialect="spark",
    suites=suites,
)
```

Do not describe the native profiler as creating UMF. The correct flow is:

- Spark schema reflection creates UMF.
- `NativeSparkProfiler` creates data profile metrics.
- `ProfileToGxMapper` converts profile metrics into validation expectations.
- Compile persists UMF snapshots, validation suites, and runtime artifacts.
- Sample data is generated downstream from UMF/spec artifacts, not directly from
  native profile output.

## End-to-End Happy Path

Preserve this product story when writing docs, examples, APIs, or tracked work
items. If a step is not yet one-shot, show the current supported composition and
file or cite a tracked issue for the missing facade.

1. Generate UMF from existing Spark/Databricks tables.
   Use schema reflection for the UMF and native profiling for validation
   enrichment.
2. Generate sample data from the resulting UMF/spec artifacts.
   Sample data should honor constraints, domain types, relationships, and
   validation expectations.
3. Validate real data and generated sample data.
   Real data proves the observed source contract; sample data proves the generated
   contract and fixtures are usable.
4. Generate table specification and validation XLSX files.
   Excel is a review/editing surface for domain experts, not the production
   runtime contract.
5. Define a derived table.
   Express derivations in UMF so downstream Spark/LDP/dbt emitters share the same
   source of truth.
6. Generate Spark, LDP, and dbt pipeline artifacts.
   Keep generation deterministic and artifact-based; do not require production to
   re-run authoring logic.
7. Run the pipelines.
   Development may run locally or in Databricks for validation. Production should
   run installed pipeline JSON artifacts and installed wheels.

## UMF Formats

Treat split YAML directories as the editable authoring format:

```text
tables/<table>/
  table.yaml
  columns/<column>.yaml
  expectations.yaml
```

Treat JSON as artifact/interchange format. Inline whole-UMF YAML is legacy or
migration-only; do not create new public examples that use `table.umf.yaml` as the
canonical authoring format. If a task touches inline YAML support, check the
tracked issue or bead covering its quarantine before deciding whether to preserve,
reject, or migrate it.

## Dialects

Databricks uses Spark-family SQL for tablespec cast expressions. Until the
project's Databricks dialect handling is fully canonicalized, prefer
`dialect="spark"` in Databricks examples unless the code path being changed
explicitly accepts `dialect="databricks"`. If changing dialect support, make code,
errors, CLI help, docs, and tests agree on the same accepted values.

## Production Pipeline Contract

Keep development and production boundaries explicit:

- Development/bootstrap may infer UMF, profile data, compile artifacts, and build
  packages.
- Production should run installed pipeline JSON artifacts and installed wheels.
- Do not present notebook-local Python orchestration as the production runtime.
- Dev pipeline work should build wheel artifacts for installation and produce or
  validate the JSON pipeline definitions consumed by production.

## Databricks Testing

On Databricks, run Spark-dependent tests in the notebook kernel process. Use
`ipytest` or `pytest.main([...])`, not subprocess pytest. Do not use `uv run
pytest` for Spark runtime tests on Databricks because the isolated environment
cannot see the runtime PySpark/Spark Connect session.

For local work, use the repo's normal `uv run pytest ...` commands unless a
Databricks-specific instruction says otherwise.

## Public Surface Discipline

When agents or users need a "how do I do this?" answer, point them at the public
facade or CLI. Reserve these lower-level pieces for implementation work:

- `tablespec.e2e.paths.umfs_from_tables`
- `tablespec.e2e.compile.compile_umfs`
- `tablespec.profiling.spark_mapper.SparkToUmfMapper`
- `tablespec.profiling.native_profiler.NativeSparkProfiler`
- `tablespec.profiling.gx_expectation_builder.ProfileToGxMapper`

If no public facade exists for a common workflow, file an issue (or a bead, in
DDx repositories) to add one instead of normalizing hand-written orchestration in
docs.
