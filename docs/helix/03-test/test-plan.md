---
ddx:
  id: TP-001
---

# Test Plan

**Version**: 3.1
**Status**: Updated for compiler/runtime, multi-source, guidebook, microsite, and app deployability
**Last Updated**: 2026-07-22

**Requirements**: [../01-frame/prd.md](../01-frame/prd.md)
**Architecture**: [../02-design/architecture.md](../02-design/architecture.md)
**Companion plans**: [conformance-acceptance.md](conformance-acceptance.md),
[gold-conformance-plan.md](gold-conformance-plan.md),
[dbt-roadmap-acceptance.md](dbt-roadmap-acceptance.md),
[data-quality-expectations.md](data-quality-expectations.md)

## Testing Strategy

**Goals**: Prove (1) every emitter is deterministic and on the shared core seam,
(2) every execution engine reproduces the Spark-direct oracle byte-for-byte,
(3) profiling + validation are *correct* (not just non-crashing) on Spark Connect /
Databricks serverless, (4) multi-source kinds land and suite correctly per FR-21,
(5) guidebook generation is deterministic for valid UMF sets (FR-22), (6) the product
microsite builds and Playwright-checks navigation (FEAT-030), and (7) the Databricks
App is portable and fail-fast under FR-23 (desired; whole-stack app e2e is an open
gate tracked in alignment beads). | Quality gate: `make check` (lint + pyright + tests)
plus the cross-engine conformance matrix and the Connect (Sail) lanes.

**Out of Scope**: Live production data processing owned by consumer runtimes;
load/stress testing of warehouse capacity.

(GX *custom*-expectation parity on Connect is now **covered** — all four customs are
verdict- and value-equal across classic and Connect, asserted by
`tests/unit/test_custom_gx_parity.py`. See
[serverless-compatibility](../02-design/spikes/SPIKE-002-serverless-compatibility.md).)

**Traceability Source**: PRD FR-5.x (profiling), FR-7.7/7.8 (Connect-safe
validation), FR-18.x (compile/bootstrap), FR-19.x (multi-target emission),
FR-20.x (runtime platform), FR-21.x (source acquisition), FR-22.x (guidebook),
FR-23.x (app deployment); FEAT-024–034; US-021–026, US-038–039, US-044–049.

### Test Levels

| Level | Coverage Target | Priority |
|-------|-----------------|----------|
| Contract | Emitter→artifact byte-for-byte goldens; `CompiledArtifacts` manifest layout; `src` never imports the test tree or dbt | P0 |
| Integration | Per-emitter project builds (dbt parse/run, LDP structure), staged validation routing, profiler→GX expectations, ingestion readers by kind | P0 |
| Unit | UMF models (incl. EMBEDDING + source kinds), type mappings, schema generators, baseline GX, native expectation evaluators, capability probing, guidebook pure helpers | P0 |
| E2E (library) | Bootstrap → compile → backbone across the DuckDB/Spark/Sail matrix; opt-in real-Databricks deploy/execute | P0 (local), P1 (opt-in workspace) |
| E2E (microsite) | Hugo build + Playwright navigation/responsive checks (`website/e2e/`) | P1 |
| E2E (Databricks App) | Config resolve + provision + startup against a declared metadata home | P1 **desired** (open gap; concerns `e2e-framework` slot) |

### Frameworks

| Type | Framework | Reason |
|------|-----------|--------|
| Contract | pytest + golden files (`tests/golden/`, `tests/conformance/corpus`) + `canonical.to_json` | Byte-for-byte, human-diffable artifact verification |
| Integration | pytest; dbt-core (duckdb/spark-session/databricks adapters); pysail (Spark Connect server) | Execute generated projects + Connect lanes with no JVM |
| Unit | pytest, pytest-mock, hypothesis | Pure-Python logic; property tests for generators/diff |
| E2E (library) | pytest conformance engine matrix; `e2e/backbone.py` runner | One harness, many engines, one canonicalizer |
| E2E (microsite) | Playwright | Browser navigation and responsive rendering for FEAT-030 |
| E2E (app) | TBD (alignment bead) | Whole-stack exercise for FR-23; not yet selected |

## Test Data

| Type | Strategy |
|------|----------|
| Fixtures | Shared conformance corpus (`tests/conformance/corpus`) — one fixture set canonicalized across every engine; golden artifact trees (`tests/golden/ingest_sql/`, `tests/golden/dbt_project/`) |
| Factories | UMF models built programmatically in unit tests; clean vs dirty datasets for validation lanes (exact `unexpected_count` asserted) |
| Mocks | MagicMock for Spark objects in pure-unit tests; real Sail/Spark sessions where engine behavior is under test (never mocked) |

## Coverage Requirements

| Metric | Target | Minimum | Enforcement |
|--------|--------|---------|-------------|
| Line | 80% on new code | 70% | `make coverage` |
| Critical | 100% | 100% | Required on P0 paths below |

### Critical Paths (P0)

1. **UMF model validation** — Pydantic constraints, YAML I/O, round-trip.
2. **Compile orchestration** — `compile_umfs` persists every artifact under the
   pinned layout; the `CompiledArtifacts` manifest resolves deterministically.
3. **Runtime independence** — the backbone executes only committed artifacts; `src`
   never imports the `tests/` tree or dbt (`test_core_encapsulation.py`,
   `test_src_never_imports_dbt`).
4. **Connect-safe validation** — Connect DataFrames route to the native executor and
   return the *correct* verdict (clean→pass, dirty→fail), never the swallowed
   `add_spark` false-negative.
5. **Cross-engine parity** — every row-tier engine reproduces the Spark-direct
   oracle byte-for-byte under one canonicalizer.
6. **Native profiling** — `NativeSparkProfiler` runs JVM-free on Connect and feeds
   GX expectations.
7. **EMBEDDING type** — dimension required; mappings and baseline expectations
   exercise FR-1.11 on the type alphabet path.
8. **Source-kind readers** — delimited/parquet/json/jdbc model + reader contracts
   (FR-21); residual dump/parquet cast paths tracked as open gaps.

### Secondary Paths (P1-P2)

- P1: dbt `state:modified` CI selection from UMF diff; LDP structure golden;
  opt-in real-Databricks deploy/execute leg; guidebook generation (FR-22);
  microsite Playwright; app config/provision/startup (FR-23, desired).
- P2: GX custom-expectation Connect parity (**covered** — `test_custom_gx_parity.py`,
  all four customs verdict+value equal classic vs Connect); CLI mutation commands;
  property-based generator fuzzing; SEC 10-K demo residual (US-045).

## Acceptance Criteria Layer Allocation

This project plan **aggregates** strategy; per-criterion AC↔test matrices live in
the companion acceptance docs (conformance, gold-conformance, dbt-roadmap) and per-
story test plans. Here, criterion *classes* are allocated to a primary layer:

| AC class / source | Story / plan | Primary Layer | Why this layer |
|-------------------|--------------|---------------|----------------|
| Compile produces every artifact under the pinned layout (FR-18.1/18.2) | US-023 / FEAT-026 | Contract | Artifact existence + manifest shape are static facts |
| Runtime consumes only committed artifacts (FR-18.3) | US-024 / FEAT-026 | Contract + Integration | Import-isolation contract + executed backbone |
| Bootstrap path-agnostic across engines (FR-18.4/18.5) | US-023 / FEAT-026 | E2E | User-observable across DuckDB/Spark/Sail |
| Native profile on Connect feeds GX (FR-5.1/5.2) | US-021 / FEAT-024 | Integration | Real Connect session + GX expectation output |
| Connect-safe suite execution, no silent false-negative (FR-7.7/7.8) | US-022 / FEAT-025 | Integration | Real Connect session; correctness asserted |
| dbt project emitted + builds green (FR-19.2) | US-025 / FEAT-027 | Integration | dbt parse/run on duckdb/spark |
| LDP project emitted + conformance tier (FR-19.3) | US-026 / FEAT-028 | Integration | Structure golden + Databricks-execute (opt-in) |
| Cross-engine byte-for-byte parity (FR-18.5/19.x) | conformance-acceptance | E2E | Engine matrix vs the oracle |
| Guidebook pages + lineage (FR-22) | US-046 / FEAT-033 | Integration | Deterministic HTML + search index |
| Microsite Pages coexistence (FEAT-030) | US-038 | E2E (microsite) | Hugo + Playwright + Pages artifact paths |
| App portable deploy (FR-23) | US-047–049 / FEAT-034 | E2E (app) | Desired gate; open bead until harness exists |

**Allocation rule**: every P0 acceptance criterion maps to exactly one primary
layer here and to concrete tests in its companion plan / STP.

## The Cross-Engine Conformance Matrix

The conformance harness (`tests/conformance/`) proves every supported backend
reproduces the Spark-direct oracle byte-for-byte under one shared canonicalizer
(`canonical.to_json`). Engines that cannot run a tier in this environment are
**skipped with an explicit, visible reason** — never silently passed — and a
"skipped-but-green" guard fails the suite if a required engine produced only skips.

| Engine | Tier | JVM / `JAVA_HOME` | Role |
|--------|------|-------------------|------|
| `SparkDirect` | row (oracle) | yes / JDK 17 | The oracle: `generate_ingest_sql` on Delta-Spark |
| `DbtDuckDB` | row | no | dbt(duckdb) raw→ingest parity; fast inner loop |
| `DbtSparkSession` | row | yes / JDK 17 | dbt-spark `method: session` parity |
| `SQLPlanGeneratorGold[duckdb]` | row (gold) | no | Direct gold SQL plan on DuckDB |
| `SQLPlanGeneratorGold[spark]` | row (gold) | yes / JDK 17 | Direct gold SQL plan on Spark |
| `DbtDatabricksCompile` | compile | no (offline parse) | dbt-databricks `dbt parse` registers; no cluster |
| `LdpStructure` | structure | no | LDP project structure golden |
| `DbtDatabricksE2E` / `LdpDatabricksE2E` | e2e | n/a | Opt-in real-workspace deploy/execute (`DATABRICKS_HOST`) |

`REQUIRED_LOCAL_ROW_ENGINES` (`tests/conformance/engines.py:1658`) lists the engines
that MUST actually execute locally (Spark JDK + dbt adapters present): `SparkDirect`,
`DbtDuckDB`, `DbtSparkSession`, `SQLPlanGeneratorGold[duckdb]`,
`SQLPlanGeneratorGold[spark]`. See [conformance-acceptance](conformance-acceptance.md)
and [gold-conformance-plan](gold-conformance-plan.md) for the criteria-first matrix.

## Connect / Serverless Validation Lanes

GX 1.x `add_spark` silently returns `success=False`/`result={}` on Spark Connect
(no JVM `SparkContext`). The router (`gx_executor.py`) sends Connect DataFrames to a
native DataFrame-API executor; classic Spark keeps `add_spark`. These lanes prove the
native path is *correct*, not just non-crashing, with **no JVM / no `JAVA_HOME`**:

| Lane | What it proves | Evidence |
|------|----------------|----------|
| Native profiler on Sail (Connect) | `NativeSparkProfiler` runs Connect-safe; pins scalar `percentile_approx` + exact float `count_distinct` (DataFusion) | `tests/unit/test_profiler_connect_sail.py` |
| Native GX executor + `TableValidator` on Sail | Every supported expectation type: clean→`success=True`, dirty→`success=False` with exact `unexpected_count` | `tests/unit/test_validation_connect_sail.py` |
| GX *custom*-expectation parity (classic vs Connect) | All four customs (`cast_to_type`, `match_domain_type`, `pair a>b`, `date_in_current_year`) driven through `GXSuiteExecutor` on both engines: identical `success`, `unexpected_count`, and `partial_unexpected_list` (incl. the pair custom's `[A, B]` rendering) | `tests/unit/test_custom_gx_parity.py` |
| Real Databricks serverless | The same native operations run on env-v3 / Python 3.12 serverless | ADR-010/011; test docstrings; opt-in e2e tier |

**Custom-expectation Connect parity (was P2 gap — now COVERED):** the four GX
*custom* expectations are routed through GX's classic `add_spark` engine on classic
Spark and through the Connect-safe native path (`gx_executor._evaluate_custom_native`
→ `custom_gx_expectations` validators) on Connect. Both engines now agree on
`success`, `unexpected_count`, *and* the `partial_unexpected_list` sample (the native
column-pair validator renders `[column_A, column_B]` string pairs to match
`add_spark` byte-for-byte). Asserted on both lanes by
`tests/unit/test_custom_gx_parity.py` (classic JVM + Sail/Connect, clean and dirty).

## The e2e Bootstrap → Compile → Backbone Matrix

`tests/e2e` / `e2e/backbone.py` exercise the full spine: bootstrap (Path A inferred /
Path B loaded) → `compile_umfs` → backbone runner, parametrized across DuckDB,
classic local Spark, and Sail (Connect). The backbone executes only committed
artifacts, ships its deps from `src/` (never imports `tests/`), and gates the real-
serverless leg behind `DATABRICKS_HOST`. Stage coverage per the runner
(`e2e/backbone.py`): ingest raw→ROW → validate RAW (staged) → ingest ROW→INGESTED →
validate INGESTED (staged) → transforms (dbt parse always; dbt run + gold plan on
duckdb/local-spark; LDP structure local, APPLY CHANGES only on real Databricks).

## Implementation Order

1. UMF models, type mappings, schema generators, baseline GX (the emit foundation).
2. Native profiler + native expectation evaluators + capability probing (the
   Connect-safe substrate every higher lane depends on).
3. Per-emitter goldens (direct SQL, dbt, LDP) on the shared core seam.
4. Compile orchestrator + manifest contract; backbone import-isolation.
5. Cross-engine conformance matrix + Connect (Sail) lanes.
6. e2e bootstrap matrix; opt-in real-Databricks leg last.

## Infrastructure

| Requirement | Specification |
|-------------|---------------|
| CI Tool | GitHub Actions on push/PR; local `make check` |
| Run prefix | `UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=.../openjdk@17 SPARK_LOCAL_IP=127.0.0.1 uv run <cmd>` |
| Test DB / engines | DuckDB (in-proc); classic Spark 4.0 + Delta 4.0 (JDK 17 — default JDK 26 crashes in `getSubject`); Sail Spark-Connect (pysail, no JVM); opt-in Databricks (`DATABRICKS_HOST`) |
| Services | None required locally; isolated `spark.sql.warehouse.dir` + metastore per dbt-spark case for parallel safety |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Silent green on skipped engines | High | `REQUIRED_LOCAL_ROW_ENGINES` guard fails if a required engine only skips |
| GX `add_spark` silent false-negative on Connect | High | Per-expectation routing to the native executor; correctness lanes assert exact counts |
| JDK-version fragility (Spark) | Med | Explicit `JAVA_HOME=openjdk@17` prefix; Sail lane needs no JVM at all |
| Connect DataFrame mis-classification | Med | `_is_connect_dataframe` is a correctness-critical seam; module-prefix based, covered by Sail lanes |
| dbt-CLI startup dominates duckdb suite wall-clock | Low | Acknowledged harness cost (see phase4 eval); not an engine limitation |

**Known Gaps**: (1) ~~GX custom-expectation Connect parity (P2)~~ — **CLOSED**,
covered by `tests/unit/test_custom_gx_parity.py` (all four customs, verdict + value
equal on classic and Connect). (2) No load/stress testing. (3) Pre-existing:
`test_gx_schema_validation.py` skipped (GX numpy/pandas compatibility); thin unit
coverage on some authoring/change-mgmt utilities (see the inventory below). (4)
Residual no-format TIMESTAMP offset divergence and dedup tie-break determinism
(documented in the phase4 eval, fixtures pending). Note: the EPOCH_MS/Excel-serial
ingest casts (cast-edge-formats) are now byte-equal for clean ISO, all detected-epoch,
and all Excel-serial values; only engine-lenient *dirty* fall-through strings (e.g.
time-only `"15:06:40"`) can differ in the default-parse ELSE branch — documented on
`casting_utils._epoch_ms_cast_sql`.

## Build Handoff

**Commands**: `make check` (lint + pyright + test) | `make coverage` |
`UV_PROJECT_ENVIRONMENT=/tmp/tsvenv ... uv run pytest tests/conformance` |
`... uv run pytest tests/unit/test_profiler_connect_sail.py tests/unit/test_validation_connect_sail.py`

**Priority**: emit foundation → Connect-safe substrate → goldens → compile/backbone →
conformance + Connect lanes → e2e matrix.

**Blocking Gate**: `make check` green; the cross-engine conformance matrix green with
all `REQUIRED_LOCAL_ROW_ENGINES` actually executing (not skipped); both Connect (Sail)
lanes green; the backbone import-isolation contract intact.

## Appendix: Module Test Inventory

The unit/integration inventory below remains authoritative for the non-spine library
surface and tracks pre-existing coverage gaps.

### Unit Tests (`tests/unit/`)

| Test File | Module Under Test | Coverage |
|-----------|-------------------|----------|
| `test_umf_models.py` | `models/umf.py` | Pydantic validation, YAML I/O, all model types |
| `test_type_mappings.py` | `type_mappings.py` | All type conversions, case insensitivity, defaults |
| `test_schema_generators.py` | `schemas/generators.py` | SQL DDL, PySpark, JSON Schema generation |
| `test_gx_baseline.py` | `gx_baseline.py` | Baseline generation, suite composition, strictness |
| `test_expectation_consistency.py` | `prompts/expectation_guide.py` | Cross-schema consistency |
| `test_profiling_mappers.py` | `profiling/` | Spark/legacy mappers, statistics, nullable inference |
| `test_profiler_connect_sail.py` | `profiling/native_profiler.py` | Connect-safe profiling on a real Sail session |
| `test_validation_connect_sail.py` | `validation/{gx_executor,native_executor,table_validator}.py` | Connect-safe validation correctness (clean/dirty, exact counts) |

### Integration / E2E (`tests/integration/`, `tests/conformance/`, `tests/e2e/`)

| Test Area | Scope | Coverage |
|-----------|-------|----------|
| `test_umf_workflow.py` | End-to-end library | Create/save/load UMF, generate all schemas, round-trip |
| `tests/conformance/` | Cross-engine matrix | Byte-for-byte parity vs the Spark-direct oracle; LDP/dbt tiers |
| `tests/e2e/` + `e2e/backbone.py` | Compile→backbone spine | Bootstrap matrix; runtime consumes only artifacts |
| `tests/test_core_encapsulation.py` | Import isolation | `src` never imports dbt / the test tree |
| `tests/test_golden.py` | Emitter goldens | Byte-for-byte ingest SQL + dbt project trees |

### Pre-Existing Coverage Gaps

- `test_gx_schema_validation.py` fully skipped (GX numpy/pandas compatibility).
- No dedicated unit tests for `gx_constraint_extractor.py`, `umf_validator.py`, the
  `prompts/` generators, or several change-mgmt / authoring utilities (`cli.py`,
  `excel_converter.py`, `umf_loader.py`, `umf_diff.py`, `umf_change_applier.py`,
  `changelog_*`, `sample_data/`, `quality/`, `inference/`, `naming.py`,
  `date_formats.py`, `formatting/`, `merge.py`, `sync_baseline.py`,
  `dependency_resolver.py`). These remain the standing backfill list.

## Review Checklist

- [x] Test levels cover contract, integration, unit, and E2E with coverage targets
- [x] Framework choices are justified (dbt adapters, pysail Connect lane)
- [x] Critical paths (P0) identified with 100% coverage requirement
- [x] Test data strategy covers fixtures, factories, and mocks
- [x] Coverage requirements have targets, minimums, and enforcement
- [x] Implementation order is justified (substrate before higher lanes)
- [x] Infrastructure is specific (engine versions, JDK pin, run prefix)
- [x] Risks include silent-green, Connect false-negative, JDK fragility
- [x] Known gaps documented (GX custom on Connect; no load testing)
- [x] Build handoff commands are concrete and runnable
- [x] Plan traces to PRD FR-5/7/18/19/20 and the governing FEAT/US
- [x] Every P0 criterion allocated to a primary layer without restating per-AC rows
