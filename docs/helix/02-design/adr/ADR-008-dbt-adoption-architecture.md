# ADR-008: dbt Adoption Architecture (Subsystem Candidate Map + Encapsulation)

## Status

Proposed — extends ADR-007 (raw->ingest SQL artifact) to the rest of tablespec.

## Context

ADR-007 made the raw->ingest transform a generated SQL artifact and Phase 1-8 of
`feat/dbt-runner` added a fully isolated dbt path: a framework-agnostic CORE
(`tablespec.core` — the `TableRenderer` Protocol + the logical-plan IR) and a
dbt implementation package (`tablespec.dbt`) that both the direct-artifact path
and the dbt path depend on, *never on each other*. `dbt-core`/`dbt-duckdb` are an
optional `[dbt]` extra (lazy import; importing core never requires dbt), enforced
by `tests/test_core_encapsulation.py`.

That covers ingest + gold model emission. The question this ADR answers: **once a
user opts into dbt, what ELSE in tablespec should the dbt path own**, and how do
we keep every new piece inside the same encapsulation seam (no duplication, no
core->dbt import, dbt optional)?

The guiding intent: when dbt is selected, use it for everything we reasonably
can — schema tests, contracts, source/ref edges, seeds, state-based CI selection
— while the genuinely-rich, stage-classified, statistical, or Spark-bound logic
**stays native** (Great Expectations on Spark, profiling, baselines).

## Decision

### 1. Per-subsystem dbt-candidate map

Legend — **maps**: what becomes a dbt artifact; **stays native**: what does not;
**E** effort (S/M/L); **V** value (L/M/H).

| Subsystem | Candidate | Maps to dbt | Stays native | E | V |
|---|---|---|---|---|---|
| `validation/` + `gx_*` (Great Expectations) | **partial** | The four deterministic baseline expectations that have first-class dbt generic tests: `expect_column_values_to_not_be_null` -> `not_null`; `expect_column_values_to_be_unique` -> `unique`; `expect_column_values_to_be_in_set` -> `accepted_values`; FK `references` -> `relationships`. These become `schema.yml` `data_tests:` on the `ingested_`/`gold_` model. **Status:** `not_null` + `unique` already emit on both dbt paths; `relationships` already emits on the multi-table DAG path (`project._gold_schema_yml`, FK-driven, cross-pipeline FKs skipped); `accepted_values` and single-table-path `relationships` are the remaining gap. | Everything stage-classified or rich: `expect_column_values_to_cast_to_type`, `expect_column_values_to_match_strftime_format`, `expect_column_value_lengths_to_be_between`, regex/regex_list, pair/compound/cross-column, `expect_table_*`, conditional (`row_condition`), and the `raw` vs `ingested` two-stage routing (`gx_executor.execute_staged`) — these run in GX on Spark/duckdb. dbt-utils/dbt-expectations could absorb a few (`accepted_range`, `expression_is_true`) but that adds a dbt-package dependency for marginal value; keep them in GX. | M | H |
| `quality/` baselines | **no** | — | Run-over-run drift detection (row-count deltas, distribution comparison, KL-style change) is **stateful, statistical, and Spark-bound** (`baseline_service` reads a DataFrame with `pyspark.sql.functions`). dbt tests are stateless pass/fail; this is a metric store. Out of scope. | L | L |
| `profiling/` (profile->umf) | **no** (UMF authoring) / **partial** (separate angle) | Nothing in the profile->UMF direction. A *separate* "dbt-profiler" angle (emit `dbt-profiler`-style column profiles from a built warehouse) is a net-new feature, not a port. | `SparkToUmfMapper` / Deequ mapping stays native — it produces UMF, the upstream source of truth that *feeds* dbt generation. | L | L |
| `sample_data/` | **yes** | Generated per-table CSVs map directly to **dbt seeds** (`seeds/<table>.csv` + a `seeds:` config in `dbt_project.yml` with column `column_types` from UMF). Useful for `dbt build` smoke tests / CI fixtures and for the duckdb parity harness. | The *generation* logic (constraint handlers, FK graph, domain types) stays native — it produces the CSV; dbt only consumes it. | S | M |
| `changelog_*` / `umf_diff` | **yes** | `umf_diff` already computes per-table added/removed/modified. Mapping the changed-table set to dbt's **`state:modified` selection** lets CI build/test only impacted models (`dbt build --select state:modified+ --defer`). The diff drives a selection manifest / `--select` arg; pairs naturally with contracts (a breaking column change shows up as a contract violation). | Changelog narrative generation (git-history -> human changelog) stays native. | M | H |
| `schemas/generators` (DDL/json/pyspark) | **partial** | The UMF column set -> **dbt model contracts** (`config(contract={enforced: true})` + per-column `data_type` + `constraints:` in `schema.yml`). This is the same column/type information `generate_sql_ddl` emits, re-targeted at dbt's contract enforcement so a schema drift fails `dbt parse`/build. | JSON Schema and PySpark `StructType` generators stay native (consumed by non-dbt callers: GX, Spark readers, docs). DDL is *subsumed* by contracts on the dbt path but kept for the direct artifact. | M | H |
| `relationships` / `dependency_resolver` | **yes (already core)** | The `NodeRegistry` (Phase-built IR) already turns cross-table refs into static `{{ ref() }}`/`{{ source() }}` edges and cross-pipeline FKs into `source('external', ...)`. The remaining map: emit `relationships` generic tests from `ForeignKey` entries. `dependency_resolver`'s pipeline version constraints stay native (a pre-generation gate). | Version-constraint validation + cycle detection across *pipelines* stays native (it gates whether we generate at all); intra-project cycles are already caught by `LogicalPlan.detect_cycle`. | S | H |
| `prompts/` | **no** | — | LLM prompt generators (documentation, validation-rule authoring, relationship inference) are an authoring-time concern that *produces* UMF/expectations. No dbt artifact. | — | — |

**Summary of "yes"/"partial" candidates, highest value-to-effort first:**
relationships/dependency_resolver (already core, S/H), accepted_values+relationships
schema tests (S-M/H), model contracts from schemas (M/H), `state:modified` CI
selection from `umf_diff` (M/H), sample_data->seeds (S/M).

### 2. Encapsulation architecture (concrete)

The seam is unchanged from Phases 0-8; new work slots into the SAME two packages.
**Hard rule (enforced by `tests/test_core_encapsulation.py`): nothing under
`tablespec.core` imports `tablespec.dbt`, and the two backend paths never import
each other.** Each new candidate is a single-responsibility module under
`tablespec.dbt`, fed by a CORE interface.

#### Shared CORE (`src/tablespec/core/`) — no dbt, no Spark, no SQL dialect

```
core/
  ir.py            # LogicalPlan / PlanNode / NodeRole / LogicalEdge  (exists)
  relations.py     # TableRenderer Protocol, RelationRef, LiteralRenderer (exists)
  schema_facts.py  # NEW: dialect-free column-test facts extracted from UMF:
                   #   ColumnTest(not_null|unique|accepted_values(values)|
                   #              relationship(to_table,to_column)) and
                   #   ColumnContract(name, data_type, nullable, constraints).
                   #   Pure derivation from UMF — both GX baseline and the dbt
                   #   schema.yml emitter consume it, so the not_null/unique/
                   #   accepted_values/relationships truth lives in ONE place.
  selection.py     # NEW: ChangeSet (set[table_name]) — the engine-agnostic
                   #   result of umf_diff, with no knowledge of `state:modified`.
```

`schema_facts.py` is the key anti-duplication move. `not_null` is derived in
*three* places with non-identical logic today — `gx_baseline.py` (dict-style
per-LOB nullable contexts) and `dbt/single_table`/`schemas.generators`
(`_resolve_nullable`, which also handles a plain boolean `nullable: false`). And
`unique` is derived from DIFFERENT sources: `gx_baseline.py` emits
`expect_column_values_to_be_unique` from *profiling cardinality*, while the dbt
path emits `unique` from *single-column primary keys / `unique_constraints`*. So
this is not pure de-dup of identical code — it is a reconciliation: lift one
`core.schema_facts.column_tests(umf)` that fixes the nullable-resolution rule AND
the unique-source policy in one place, then have GX baseline and the dbt
`schema.yml` emitter both consume it, so the two backends are provably the same
set of UMF-derived constraints (profiling-only expectations stay in GX).

#### dbt implementation (`src/tablespec/dbt/`) — all dbt-specific text

```
dbt/
  __init__.py          # public dbt API (lazy-importable)
  registry.py          # NodeRegistry: UMF set -> LogicalPlan + name index (exists)
  renderer.py          # DbtRefRenderer: name -> {{ ref() }}/{{ source() }} (exists)
  routing.py           # RoutingPolicy: source/ref literals, dev/prod knobs (exists)
  materialization.py   # MaterializationPolicy: graph -> Materialization (exists)
  project.py           # generate_dbt_dag_project (multi-table DAG)  (exists)
  single_table.py      # generate_dbt_project (one table)           (exists)
  schema_tests.py      # NEW: core.schema_facts.ColumnTest[] -> schema.yml
                       #   data_tests: blocks (not_null/unique/accepted_values/
                       #   relationships). Replaces the inline logic in
                       #   single_table/project, fed by the shared facts.
  contracts.py         # NEW: core.schema_facts.ColumnContract[] ->
                       #   config(contract=...) + columns: data_type/constraints.
  seeds.py             # NEW: sample_data CSV -> seeds/ + dbt_project seeds: config.
  selection.py         # NEW: core.selection.ChangeSet -> `state:modified`
                       #   --select expression / selection manifest for CI.
  runner.py            # NEW: the OPT-IN entry point (see §3) — lazy-imports
                       #   dbt-core only here, when the user actually runs.
```

Dependency direction (acyclic): `tablespec.dbt.*` -> `tablespec.core.*` -> stdlib
+ `tablespec.models`. The direct-artifact path (`schemas/ingest_generator`,
`SQLPlanGenerator`) -> `tablespec.core.*` only. No edge between the two backends.

### 3. Opt-in mechanism (dbt strictly optional)

Three layers, so that *importing* tablespec core never touches dbt and *running*
dbt only happens behind an explicit user choice:

1. **Generation is import-safe.** Everything under `tablespec.dbt` that only
   *emits text* (project.py, single_table.py, schema_tests.py, contracts.py,
   seeds.py, selection.py) is pure Python with **no `import dbt`**. So
   `from tablespec.dbt import generate_dbt_project` works without the extra
   installed — you can generate a project anywhere.

2. **Execution is lazy + extra-gated.** Only `tablespec.dbt.runner.DbtRunner`
   touches `dbt-core`, and it imports it **inside the method**, raising a clear
   "install `tablespec[dbt]`" error if absent:

   ```python
   class DbtRunner:
       def run(self, project_dir: Path, select: str | None = None) -> RunResult:
           try:
               from dbt.cli.main import dbtRunner as _DbtRunner  # lazy
           except ModuleNotFoundError as e:
               raise MissingDbtExtra("pip install 'tablespec[dbt]'") from e
           ...
   ```

3. **Backend selection is an explicit interface, never auto-magic.** Define a
   CORE `Emitter` Protocol (`emit(umfs, out_dir) -> None`); the CLI/API picks the
   backend by name:

   ```python
   # tablespec generate <umf> --backend dbt   (vs the default direct artifact)
   def get_emitter(backend: str) -> Emitter:        # in tablespec.cli / a registry
       if backend == "dbt":
           from tablespec.dbt import DbtEmitter     # lazy: dbt path only loaded on demand
           return DbtEmitter()
       return DirectArtifactEmitter()               # ADR-007 path, no dbt
   ```

   The default backend is the ADR-007 direct artifact; `--backend dbt` (or a
   `[tool.tablespec] backend = "dbt"` config / a `tablespec.emitters` entry point
   for third parties) opts in. Core's `Emitter` Protocol is the only shared type;
   neither backend imports the other.

### 4. Adoption roadmap (value-to-effort ordered)

1. **Extract `core/schema_facts.py`** and make BOTH `gx_baseline` and
   `dbt/single_table`/`project` consume it — reconciling the three nullable
   resolutions and the divergent `unique` source (PK/constraint vs profiling
   cardinality) into one policy. *S, H.*
2. **`dbt/schema_tests.py`: add `accepted_values`** (UMF value sets) and bring
   `relationships` to the single-table path (the multi-table DAG path already
   emits it). *S, H.*
3. **`dbt/contracts.py`: model contracts** from the UMF column/type set (reuse
   `type_mappings`); fail build on schema drift. *M, H.*
4. **`core/selection.py` + `dbt/selection.py`: `state:modified` CI** driven by
   `umf_diff`. *M, H.*
5. **`dbt/seeds.py`: sample_data -> seeds** for `dbt build` smoke tests + the
   duckdb parity harness. *S, M.*
6. **`dbt/runner.py` + `Emitter`/`get_emitter` opt-in** wiring + CLI `--backend`.
   *M, H — unlocks "run everything through dbt".*

Explicitly **out of scope** (stays native): `quality/` baselines, `profiling`
mappers, `prompts/`, and all rich/stage-classified/statistical GX expectations.

## Consequences

- **Positive:** one constraint truth (`schema_facts`) feeds GX and dbt; dbt stays
  an optional extra never imported by core; each candidate is a small isolated
  module; the highest-value items (schema tests, contracts, `state:modified`) are
  cheap because the IR/registry already exist.
- **Negative / risks:** schema.yml generic tests and GX must not silently diverge
  — sharing `schema_facts` mitigates this but adds a refactor of `gx_baseline`.
  Contracts duplicate type info already in DDL; we accept DDL being subsumed on
  the dbt path. dbt-utils/dbt-expectations are deliberately *not* adopted to avoid
  a dbt-package dependency for marginal expectation coverage.
- **Enforcement:** `tests/test_core_encapsulation.py` continues to assert no
  `core -> dbt` import and no cross-backend import; every new dbt module lands
  under `tablespec.dbt` and every new shared interface under `tablespec.core`.
```
