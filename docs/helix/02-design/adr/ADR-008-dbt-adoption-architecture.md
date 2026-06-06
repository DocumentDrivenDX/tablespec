# ADR-008: dbt Adoption Architecture (Subsystem Candidate Map + Encapsulation)

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Platform / Compile Team | FEAT-027, ADR-007, FR-19.1, FR-19.2 | High |

## Status

Accepted — implemented as the dbt backend on the Multi-Target Emission core seam
(PRD FR-19.1/FR-19.2, FEAT-027); extends ADR-007 (raw->ingest SQL artifact) to the
rest of tablespec. This record was reconciled against the shipped `tablespec.dbt`
emitter on 2026-06-06: the roadmap items below (§4) have all SHIPPED — see the
"Implementation status (shipped)" note after §4 for the per-item evidence.

## Context

ADR-007 made the raw->ingest transform a generated SQL artifact and Phase 1-8 of
`feat/dbt-runner` added a fully isolated dbt path: a framework-agnostic CORE
(`tablespec.core` — the `TableRenderer` Protocol + the logical-plan IR) and a
dbt implementation package (`tablespec.dbt`) that both the direct-artifact path
and the dbt path depend on, *never on each other*. Generating a dbt project is
pure-Python text emission with **no `import dbt`** (enforced by
`tests/test_core_encapsulation.py::test_src_never_imports_dbt`), so importing core
never requires dbt. dbt-core/dbt-duckdb (plus dbt-spark[session]/dbt-databricks)
are needed only to *execute* generated projects in the conformance/parity tests;
they therefore live in the `[dependency-groups] dev` group, **not** as a
user-facing `[dbt]` extra — see §3 and `pyproject.toml:51`,`:63`. (This is the
dependency-model reconciliation: the original draft assumed a `[dbt]` extra; the
shipped decision is dev-group / test-only, matching the PRD Non-Goal "Shipping dbt
… as user-facing runtime dependencies".)

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
| `validation/` + `gx_*` (Great Expectations) | **partial** | The four deterministic baseline expectations that have first-class dbt generic tests: `expect_column_values_to_not_be_null` -> `not_null`; `expect_column_values_to_be_unique` -> `unique`; `expect_column_values_to_be_in_set` -> `accepted_values`; FK `references` -> `relationships`. These become `schema.yml` `data_tests:` on the `ingested_`/`gold_` model. **Status (shipped):** `not_null` is emitted as the model's enforced-contract `constraints:` entry (not a duplicate generic test); `unique`, `relationships`, and `accepted_values` are all emitted on BOTH the single-table path (`single_table._model_schema_block`, `src/tablespec/dbt/single_table.py:168`) and the multi-table DAG path (`project._staging_schema_yml`/`_gold_schema_yml`, `src/tablespec/dbt/project.py:229`,`:278`), all derived from the shared `core.schema_facts` (`relationship_tests`, `accepted_values_tests`). Cross-pipeline / unresolvable FKs are skipped (never a dangling `ref()`). | Everything stage-classified or rich: `expect_column_values_to_cast_to_type`, `expect_column_values_to_match_strftime_format`, `expect_column_value_lengths_to_be_between`, regex/regex_list, pair/compound/cross-column, `expect_table_*`, conditional (`row_condition`), and the `raw` vs `ingested` two-stage routing (`gx_executor.execute_staged`) — these run in GX on Spark/duckdb. dbt-utils/dbt-expectations could absorb a few (`accepted_range`, `expression_is_true`) but that adds a dbt-package dependency for marginal value; keep them in GX. | M | H |
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

The seam is unchanged from Phases 0-8; the work below slots into the SAME two
packages. **Hard rule (enforced by `tests/test_core_encapsulation.py`): nothing
under `tablespec.core` imports `tablespec.dbt`, and the two backend paths never
import each other.** Each candidate is a single-responsibility module under
`tablespec.dbt`, fed by a CORE interface. (Reconciliation note: the modules marked
"NEW" in the listings below have all SHIPPED — `core/schema_facts.py`,
`core/selection.py`, `dbt/schema_tests.py`, `dbt/contracts.py`, `dbt/seeds.py`,
`dbt/selection.py` — except `dbt/runner.py`, which remains deferred per §4 item 6.
The "NEW" markers are retained as the original design narrative.)

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

### 3. Dependency model (dbt is dev-group / test-only, not a user extra)

The dependency decision REVERSED the original `[dbt]` extra draft. dbt is needed
only to EXECUTE a generated project (conformance/parity tests); the library's
runtime never imports it. So:

1. **Generation is import-safe.** Everything under `tablespec.dbt` is pure Python
   with **no `import dbt`** — `project.py`, `single_table.py`, `schema_tests.py`,
   `contracts.py`, `seeds.py`, `selection.py` (`src/tablespec/dbt/__init__.py:11`).
   `from tablespec.dbt import generate_dbt_project` works with no dbt installed —
   you can generate a project anywhere `tablespec` is. The compile orchestrator
   (FR-18.1) emits both dbt projects as committed artifacts on this import-safe
   path.

2. **dbt is a dev-group, test-only dependency — NOT a `[dbt]` extra.** The dbt
   stack (`dbt-core>=1.9`, `dbt-duckdb>=1.9`, `dbt-spark[session]>=1.10`,
   `dbt-databricks>=1.9`) lives in `[dependency-groups] dev`, so `uv sync --group
   dev` always yields a working test stack with no `--extra` to remember
   (`pyproject.toml:63`). There is intentionally NO user-facing `[dbt]` extra
   (`pyproject.toml:51`), matching the PRD Non-Goal "Shipping dbt … as user-facing
   runtime dependencies" and the vision's compile-once/run-from-artifacts model:
   the runtime consumes the committed dbt project as an artifact and never invokes
   dbt through tablespec.

3. **Execution lives in the test/CI lanes.** The conformance/parity tests run
   `dbt build` against the DuckDB, local Spark session, and compile-only Databricks
   targets to prove cast parity (`tests/conformance/*`,
   `docs/helix/03-test/dbt-roadmap-acceptance.md`). A future opt-in execution
   entry point (`DbtRunner` + an `Emitter`/`get_emitter` backend selector + a CLI
   `--backend dbt`) is the only deferred piece — see §4 item 6; it is NOT yet
   shipped and remains explicitly future work.

### 4. Adoption roadmap (value-to-effort ordered) — items 1-5 SHIPPED

Implementation status (reconciled 2026-06-06): items **1-5 have shipped**; only the
opt-in execution wiring (item 6) is deferred.

| # | Roadmap item | Status | Evidence |
|---|---|---|---|
| 1 | `core/schema_facts.py` shared by GX baseline + dbt | **Shipped** | `src/tablespec/core/schema_facts.py` (`column_contracts`, `relationship_tests`, `accepted_values_tests`, `column_tests`); consumed by `dbt/single_table.py:33` and `dbt/project.py:29` |
| 2 | `accepted_values` + single-table `relationships` | **Shipped** | `src/tablespec/dbt/schema_tests.py:93`; emitted on both paths (`single_table.py:168`, `project.py:278`) |
| 3 | model contracts from schema facts | **Shipped** | `src/tablespec/dbt/contracts.py:120`; enforced-contract config on every model (`project.py:229`) |
| 4 | `state:modified` CI selection from `umf_diff` | **Shipped** | `src/tablespec/core/selection.py` (`ChangeSet`) + `src/tablespec/dbt/selection.py:69` (`select_expression`, `EMPTY_SELECTION`) |
| 5 | `sample_data` -> dbt seeds | **Shipped** | `src/tablespec/dbt/seeds.py:190` (`emit_seeds`, `render_seeds_config`, `seed_column_types`) |
| 6 | `DbtRunner` + `Emitter`/`get_emitter` opt-in + CLI `--backend` | **Deferred** | not implemented; the dbt path is exercised through the conformance/parity test lanes, not a product runner |

The original roadmap text is retained below for the rationale/effort record:

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

- **Positive:** one constraint truth (`schema_facts`) feeds GX and dbt; dbt is a
  dev-group/test-only tool never imported by core or the runtime; each candidate is
  a small isolated module; the highest-value items (schema tests, contracts,
  `state:modified`) are cheap because the IR/registry already exist.
- **Negative / risks:** schema.yml generic tests and GX must not silently diverge
  — sharing `schema_facts` mitigates this but adds a refactor of `gx_baseline`.
  Contracts duplicate type info already in DDL; we accept DDL being subsumed on
  the dbt path. dbt-utils/dbt-expectations are deliberately *not* adopted to avoid
  a dbt-package dependency for marginal expectation coverage.
- **Enforcement:** `tests/test_core_encapsulation.py` continues to assert no
  `core -> dbt` import and no cross-backend import; every new dbt module lands
  under `tablespec.dbt` and every new shared interface under `tablespec.core`.

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| schema.yml generic tests and the GX suite silently diverge | M | H | Both backends derive from one `core.schema_facts`; encapsulation test pins no cross-backend import |
| dbt-spark merge silently skips (parquet default) so FK tests never run | M | H | Pin `file_format='delta'` for the spark/databricks dialects (`single_table._model_config`) |
| dbt accidentally creeps into the user runtime dependency set | L | H | dbt confined to `[dependency-groups] dev`; `test_src_never_imports_dbt` asserts no `import dbt` under `src/` |
| Contract type info drifts from the DDL/type-mapping source | L | M | Contracts reuse `type_mappings`; DDL is accepted as subsumed on the dbt path |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| dbt `schema.yml` constraint set == GX baseline set for the same UMF | A new baseline expectation type gains a first-class dbt generic test |
| Generated projects build green on DuckDB / Spark / Databricks conformance tiers | A conformance tier turns red or a new emit target is added |
| No `import dbt` anywhere under `src/` | The encapsulation test fails, or a runtime feature wants dbt |
| Recompiled dbt project diffs clean for an unchanged UMF | UMF→artifact drift is detected in CI |

## Supersession

- **Supersedes**: None (extends ADR-007).
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: Selects dbt as a dev-group/test-only tool and pins the
  dbt-adapter version floors (dbt-core/duckdb 1.9+, dbt-spark 1.10+, dbt-databricks
  1.9+).
- **Practice override**: Overrides the implicit "optional feature => user extra"
  default — dbt is a `[dependency-groups] dev` tool, not a `[project.optional-dependencies]`
  extra. No `docs/helix/01-frame/concerns.md` Project Overrides entry is required
  beyond this ADR reference (no `concerns.md` exists in this repo).
- **No concern impact**: N/A.

## References

- PRD: `docs/helix/01-frame/prd.md` — Subsystem: Multi-Target Emission (FR-19.1, FR-19.2);
  Non-Goal "Shipping dbt … as user-facing runtime dependencies".
- Product Vision: `docs/helix/00-discover/product-vision.md` — compile-to-committed-artifacts;
  compile-once / run-from-artifacts.
- FEAT-027 — dbt Project Emitter (`docs/helix/01-frame/features/FEAT-027-dbt-emitter.md`).
- ADR-007 — Raw-to-Ingest Transforms as Committed SQL Artifacts.
- Test acceptance: `docs/helix/03-test/dbt-roadmap-acceptance.md`.
- Implementation: `src/tablespec/dbt/` (`single_table.py`, `project.py`, `schema_tests.py`,
  `contracts.py`, `seeds.py`, `selection.py`), `src/tablespec/core/schema_facts.py`,
  `src/tablespec/core/selection.py`, `pyproject.toml:51`,`:63`.
