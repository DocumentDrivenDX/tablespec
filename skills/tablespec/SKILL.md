---
name: tablespec
description: Working with tablespec and Universal Metadata Format (UMF) table schemas - bootstrapping UMF from Spark/Databricks tables, profiling, validation expectations, sample data, Excel table specs, and Spark/LDP/dbt pipeline artifacts. Use when a task involves UMF YAML/JSON, the tablespec CLI or Python API, or Databricks table-spec workflows.
---

# Tablespec

Use this skill as a routing layer. Prefer the documented public workflow first,
then drop to internals only when the task explicitly requires it. Do not duplicate
the project's requirements or design docs here; read them when changing
requirements.

## Task Routing

Focused sibling skills carry the mechanics. Route by task:

| Task | Skill |
| --- | --- |
| Author or edit UMF split YAML, columns, relationships, domain types | `tablespec-umf-authoring` |
| Bootstrap UMF, compile the artifact tree, run the raw-to-ingested backbone | `tablespec-pipeline` |
| Great Expectations suites: baseline, sync, preview, apply, staged execution | `tablespec-validation` |
| Derived/gold tables and SQL plans (derivations, base table strategies) | `tablespec-sql-plans` |
| The data-profiling Databricks App (deploy, provision, operate) | `tablespec-profiling-app` |

## Getting tablespec

tablespec is published to a GitHub Pages index, so the `--index-url` flag is
required: `pip install tablespec --index-url
https://documentdrivendx.github.io/tablespec/simple/` (use `tablespec[spark]` for
the Spark-backed bootstrap, profiling, and validation features). Installing
provides a `tablespec` CLI. Full documentation:
https://documentdrivendx.github.io/tablespec/

## Default Workflow

1. Read the local code and governing spec before changing behavior.
2. Keep user-facing examples on public APIs and commands. Internal modules may be
composable, but should not be the first path shown to users or coding agents.

## The End-to-End Story

UMF specs are the single source of truth. The happy path: bootstrap UMF from
existing tables (`bootstrap_from_tables`) or author specs by hand, compile them
into a pinned artifact tree (`bootstrap_from_specs` / `compile_umfs`), review via
Excel and sample data, then run the compiled artifacts — locally or on
Databricks. Development builds artifacts; production runs installed pipeline
artifacts and wheels, never re-derives them. Mechanics live in
`tablespec-pipeline`.

Split YAML directories (`tables/<table>/table.yaml` + `columns/<column>.yaml` +
`expectations.yaml`) are the editable authoring format; JSON is
artifact/interchange; inline whole-UMF YAML (`table.umf.yaml`) is
legacy/migration-only. Layout rules live in `tablespec-umf-authoring`.

## CLI Index

One line per command; the named skill has flags and gotchas.

| Command | Purpose | Skill |
| --- | --- | --- |
| `validate` | Validate UMF specs (schema, naming, relationships) | `tablespec-umf-authoring` |
| `info` | Rich summary of a UMF spec | `tablespec-umf-authoring` |
| `convert` / `batch-convert` | Split-dir ↔ JSON format conversion | `tablespec-umf-authoring` |
| `column-add` / `column-remove` / `column-modify` / `column-rename` | Column mutations | `tablespec-umf-authoring` |
| `domains-list` / `domains-show` / `domains-infer` / `domains-set` | Domain-type registry and assignment | `tablespec-umf-authoring` |
| `explore` | Textual TUI browser/editor (`[tui]` extra) | `tablespec-umf-authoring` |
| `bootstrap` | Authored specs → full compiled artifact tree | `tablespec-pipeline` |
| `generate` | Emit ONE artifact format (sql/pyspark/json/ingest) to stdout | `tablespec-pipeline` |
| `emit` | Materialize a runnable dbt project | `tablespec-pipeline` |
| `validation-sync` | Regenerate baseline expectations, preserving customizations | `tablespec-validation` |
| `validation-remove` | Delete expectations from the suite | `tablespec-validation` |
| `preview` | Classify expectations by stage (merged view) | `tablespec-validation` |
| `apply-response` | Apply reviewed expectation JSON | `tablespec-validation` |
| `export-excel` / `import-excel` | Excel round trip for domain-expert review | (docs: guide/excel) |
| `guidebook` | Static HTML data-catalog site from a UMF directory | (docs: guide/guidebook) |

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

For local work, use your project's normal pytest invocation (in the tablespec repo
that is `uv run pytest ...`) unless a Databricks-specific instruction says
otherwise.

## Public Surface Discipline

When agents or users need a "how do I do this?" answer, point them at the public
facade or CLI. The public facade includes `bootstrap_from_tables`,
`bootstrap_from_specs`, `compile_umfs`, `run_backbone`, `generate_sql_plan`, and
`umf_from_information_schema`. Reserve these lower-level pieces for
implementation work:

- `tablespec.e2e.paths.umfs_from_tables`
- `tablespec.profiling.spark_mapper.SparkToUmfMapper`
- `tablespec.profiling.native_profiler.NativeSparkProfiler`
- `tablespec.profiling.gx_expectation_builder.ProfileToGxMapper`

If no public facade covers a workflow, compose the documented public pieces
rather than reaching into internals.

## When contributing to tablespec itself

Everything above applies to using tablespec. When the change is to tablespec's own
code, docs, or specs, these also apply:

- Read the governing requirements and design docs before changing behavior. The
  tablespec repository keeps HELIX-style specs under `docs/helix/`.
- Track implementation work in whatever the project uses. If the repository tracks
  work with DDx beads (a `.ddx/` directory exists), use the `ddx` skill for bead
  create, claim, close, worker, and review commands; otherwise use the project's
  normal issue tracker.
- When adding or changing behavior, add a command-based acceptance test and cite
  the relevant spec or tracked issue in the implementation notes.
- Preserve the end-to-end happy path as the product story when writing docs,
  examples, APIs, or tracked work items. If a step is not yet one-shot, show the
  current supported composition and file or cite a tracked issue for the missing
  facade.
- Do not create new public examples that use `table.umf.yaml` as the canonical
  authoring format. If a task touches inline whole-UMF YAML support, check the
  tracked issue or bead covering its quarantine before deciding whether to
  preserve, reject, or migrate it.
- If no public facade exists for a common workflow, file an issue (or a bead, in
  DDx repositories) to add one instead of normalizing hand-written orchestration
  in docs.
