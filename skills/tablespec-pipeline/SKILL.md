---
name: tablespec-pipeline
description: Running the UMF-to-pipeline flow - bootstrapping UMF from existing Spark/Databricks tables or authored specs (bootstrap_from_tables, bootstrap_from_specs, tablespec bootstrap), compiling the pinned artifact tree with compile_umfs (ingest SQL, schemas, validation suites, dbt, LDP, gold plans), and executing artifacts with run_backbone. Use when generating pipeline artifacts from UMF or running the raw-to-ingested backbone locally or on Databricks.
---

# Tablespec Pipeline

## Mental model

The flow is spec → compile → pinned artifact tree → backbone run. UMF (from
reflection or authored specs) is compiled once into a persisted artifact tree
with a `manifest.json`; the runtime backbone then consumes those compiled
artifacts — never the UMF directly. Development builds the artifacts;
production installs and runs them (installed pipeline JSON artifacts plus
installed wheels). Do not re-derive UMF or transforms from source at runtime.

## Path A: bootstrap from existing tables (Spark required)

`bootstrap_from_tables` is the one-shot facade: reflect table schemas into
UMF, optionally profile the data, and compile the full artifact tree.

```python
from tablespec import bootstrap_from_tables

artifacts = bootstrap_from_tables(
    spark,
    ["catalog.schema.member"],
    out_dir="/tmp/tablespec-bootstrap",
    profile=True,
    dialect="databricks",
)
print(artifacts.manifest_path)
```

Signature: `bootstrap_from_tables(spark, table_names, out_dir, *, profile=True,
dialect="duckdb", gold_targets=None, infer_keys="none",
key_promotion_min_score=0.9, key_promotion_min_gap=0.05)` returning
`CompiledArtifacts`.

- Path A is Python-only; there is no CLI equivalent (the `tablespec bootstrap`
  command is Path B).
- Do not describe the profiler as creating UMF. Schema reflection creates the
  UMF; the native profiler enriches the compiled validation suites with
  profile-derived expectations.
- Keep `profile=True` (the recommended default). `profile=False` degrades the
  compiled suites to schema-only structural/type checks.
- `infer_keys` accepts `"none"`, `"candidates"`, or `"auto"`. Candidate mode
  writes an advisory `validation/<t>.keycandidates.json` sidecar only. Auto
  mode may promote one clear verified candidate into the compiled UMF
  snapshot's `primary_key` — which changes dbt incremental MERGE `unique_key`,
  LDP APPLY CHANGES KEYS, and sample-data uniqueness downstream, so prefer
  `"candidates"` unless promotion is intended.

## Path B: bootstrap from authored specs (no Spark)

`bootstrap_from_specs(spec_paths, out_dir, *, dialect="duckdb",
gold_targets=None)` loads split table directories, `*.umf.yaml`, or JSON
interchange paths and compiles the same tree. The CLI covers this path:

```bash
tablespec bootstrap tables/member tables/claims -o build/artifacts
tablespec bootstrap tables/ -o out/ --dialect databricks
```

Flags: one or more spec paths as arguments, `--out`/`-o` for the output
directory (required), `--dialect` choosing from `duckdb` (default), `spark`,
or `databricks`.

## compile_umfs is the orchestrator

There is NO single "generate everything" command. `tablespec generate <source>
-f <format>` emits exactly ONE format to stdout — `sql`, `pyspark`, `json`, or
`ingest` — for piping to a file. The composition seam that persists every
runtime artifact is `compile_umfs`:

```python
from tablespec.e2e import compile_umfs, umfs_from_tables

umfs, suites = umfs_from_tables(spark, ["member"], profile=True)
artifacts = compile_umfs(
    umfs,
    "build/tablespec",
    source="tables",
    profile_enriched=True,
    dialect="databricks",
    gold_targets=["Claims_Summary"],
    suites=suites,
)
```

Key parameters: `source` is `"tables"` (Path A) or `"specs"` (Path B) —
manifest provenance only; `profile_enriched` is recorded on the manifest and
does not itself run profiling — the caller supplies enriched `suites`;
`suites` (expectation lists keyed by table name) are persisted verbatim when
present, otherwise the baseline suite is generated from the UMF;
`gold_targets` names tables that additionally get a single-target gold SQL
plan; `infer_keys` / `key_candidates` carry the key-inference sidecar inputs.
The bootstrap facades wrap this call — prefer them unless you need the seam.

## The pinned artifact tree

`compile_umfs` writes a pinned layout under `out_dir` and serializes a
`CompiledArtifacts` manifest enumerating every path:

```text
<out_dir>/
  manifest.json                  # serialized CompiledArtifacts — the production handoff
  umf/<table>.umf.yaml           # UMF snapshot the compile ran against
  ingest/<table>.ingest.sql      # raw DDL + typed DDL + raw->ingested transform
  schemas/<table>.ddl.sql        # SQL DDL
  schemas/<table>.schema.py      # PySpark StructType source
  schemas/<table>.schema.json    # JSON Schema
  validation/<table>.suite.json  # compiled expectation suite (raw + ingested stages)
  validation/<table>.keycandidates.json  # optional advisory key-candidate sidecar
  dbt_ingest/<table>/            # single-table ingest dbt project
  dbt_gold/                      # multi-table gold dbt DAG project (when well-formed)
  ldp/                           # Lakeflow Declarative Pipelines project
  gold_plan/<target>.plan.sql    # single-target gold plan (distinct from dbt_gold/)
```

`manifest.json` stores paths relative to the root, so the tree is relocatable;
`CompiledArtifacts.load(root)` re-absolutizes them. Production jobs locate
artifacts through the manifest, never by re-deriving names.

## Dialects

Accepted cast dialects are `duckdb`, `spark`, and `databricks`. Use `duckdb`
for local compile/run checks and `databricks` (or `spark`) for warehouse legs.
`databricks` is an accepted public spelling that Spark-family emitters
normalize to `spark` internally because the rendered cast SQL is identical;
the manifest preserves the caller's spelling.

## run_backbone

`run_backbone(artifacts, *, spark, raw_batches, run_transforms=True,
backend="spark", engine=None)` executes the compiled artifacts and returns a
`BackboneResult` (a list of per-stage `StageOutcome`s; `result.ok` is True iff
every stage succeeded). `raw_batches` maps table name to ordered raw batch
file paths; `backend` is `"spark"` (classic), `"sail"` (Spark Connect), or
`"duckdb"`.

Stage ordering is strict: raw load (all-STRING columns plus `_source_file` and
`_load_ts` audit columns) → raw validate → cast/MERGE into the typed ingested
table → ingested validate → transforms (dbt parse over every compiled project,
gold-plan check, LDP structure check). Validation runs
`GXSuiteExecutor.execute_staged(raw_df, ingested_df, expectations)` with the
compiled suite JSON — not `TableValidator`, which is the UMF-level row
validator outside the backbone.

The real-Databricks execution leg is opt-in, gated by
`tablespec.e2e.gating.databricks_e2e_availability()`: `DATABRICKS_HOST` is the
opt-in switch, and `DATABRICKS_HTTP_PATH` plus `DATABRICKS_TOKEN` must also be
set (with the dbt-databricks adapter and Databricks SDK/SQL connector
installed). When unset the leg is skipped with a precise reason — local
success never depends on a remote workspace.

## Related

- Expectations lifecycle (baselines, GX suites, staged execution): see the
  `tablespec-validation` skill.
- Derived/gold tables and plan generation: see the `tablespec-sql-plans` skill.
- Authoring and editing UMF specs: see the `tablespec-umf-authoring` skill.

Docs: `docs/guide/happy-path.md`, `docs/guide/bootstrap.md`,
`docs/guide/databricks-e2e.md`, and https://documentdrivendx.github.io/tablespec/
