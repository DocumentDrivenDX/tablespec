# Alignment Review: Spec Realignment for Shipped Runtime-Artifact Capabilities

**Review Date**: 2026-06-06
**Scope**: repo
**Status**: complete
**Review Epic**: feat/helix-align (branch-scoped; no tracker epic — doc-only reconcile)
**Primary Governing Artifact**: docs/helix/00-discover/product-vision.md

## Scope and Governing Artifacts

### Scope

- The full HELIX planning stack (vision → PRD → FEAT/US → ADR/architecture → design → test) versus the implementation shipped across this development session.
- Six new product capabilities that ran ahead of the specs: native Spark profiler, Spark Connect / Databricks-serverless runtime model, Connect-safe GX validation, compile-orchestrator + bootstrap pipeline, dbt project emitter, LDP sibling emitter (plus the supporting raw→ingest SQL artifact and cross-engine conformance harness already partially specified).

### Governing Artifacts

- docs/helix/00-discover/product-vision.md
- docs/helix/01-frame/prd.md, principles.md
- docs/helix/01-frame/features/FEAT-005, FEAT-007, FEAT-024..FEAT-028
- docs/helix/01-frame/user-stories/US-007, US-021..US-026
- docs/helix/02-design/adr/ADR-003, ADR-007, ADR-008, ADR-009..ADR-013
- docs/helix/02-design/architecture.md, ldp-sibling-emitter.md
- docs/helix/03-test/test-plan.md, conformance-acceptance.md, data-quality-expectations.md, dbt-roadmap-acceptance.md, gold-conformance-plan.md
- docs/helix/05-evaluation/serverless-compatibility.md
- src/tablespec/{profiling/native_profiler.py, session.py, validation/gx_executor.py, validation/native_executor.py, e2e/*, dbt/*, ldp/*, core/*, schemas/ingest_generator.py}
- tests/{conformance/*, e2e/*, unit/test_profiler_connect_sail.py, unit/test_validation_connect_sail.py, dbt_roadmap/*, ingest_parity/*}

## Intent Summary

- **Vision**: UMF is the single source of truth; a deterministic compile step turns one UMF into the full set of committed, reviewable runtime artifacts (direct SQL, dbt, LDP, GX suites); runtimes consume only those artifacts; the same UMF runs first-class on classic Spark **and** Databricks serverless / Spark Connect. This is a vision-consistent *advance*: "generation" extended to committed runtime artifacts, "platforms" extended to serverless/Connect.
- **Requirements**: PRD now carries FR-5 (native profiler), FR-7.7/7.8 (Connect-safe + staged suite execution), FR-18.x (compile orchestrator + bootstrap + runtime-consumes-only-artifacts), FR-19.x (multi-target emission on a shared core seam), FR-20.x (Runtime-Platform contract: per-session capability probing, engine-correct dispatch, first-class serverless/Connect).
- **Features / Stories**: FEAT-024..FEAT-028 added with US-021..US-026; FEAT-005/FEAT-007 reconciled to the shipped reality (Deequ removed; Connect-safe execution).
- **Architecture / ADRs**: ADR-009 (native profiler over PyDeequ), ADR-010 (serverless/Connect first-class runtime, never assume a JVM SparkContext), ADR-011 (per-expectation native-executor routing), ADR-012 (compile orchestrator; runtime consumes only committed artifacts), ADR-013 (target-agnostic core seam with sibling emitters) added; ADR-003/ADR-007/ADR-008 reconciled.
- **Technical Design**: ldp-sibling-emitter.md promoted to a governed design note under FEAT-028/ADR-013; serverless-compatibility evaluation captured.
- **Test Plans**: test-plan refreshed for the Sail Connect lane, e2e/bootstrap matrix, and the conformance harness; conformance-acceptance / dbt-roadmap-acceptance / gold-conformance-plan already governed these tiers.
- **Implementation Plans**: implementation-plan-v2 carries the build sequencing.

## Planning Stack Findings

| Finding | Type | Evidence | Impact | Review Issue |
|---------|------|----------|--------|-------------|
| Code shipped six new capabilities with no/stale specs (native profiler, serverless/Connect, Connect-safe GX, compile orchestrator, dbt emitter, LDP emitter) | missing-link | `git log --oneline -50` (commits ad5a4d9, 7f021ed, 7562edd, 474a6b4, dbt-roadmap series) vs pre-session specs | HIGH — vision-consistent advances were ungoverned | feat/helix-align |
| FR-5.5 claimed `DeequToUmfMapper` "remains as a legacy path" | stale | prd.md FR-5.5 vs source: `profiling/deequ_mapper.py` removed in `ad5a4d9`, zero `deequ` refs in `src/` | MEDIUM — spec asserted a removed module still exists | feat/helix-align |
| US-007 acceptance still required `DeequToUmfMapper` to enrich UMF | stale | US-007 vs removed module | MEDIUM — story would fail against shipped code | feat/helix-align |
| ADR-013 + FEAT-028 referenced "FEAT-029" for the dbt emitter | contradiction | grep `FEAT-029` (4 hits) vs dbt emitter is FEAT-027 | LOW — broken cross-reference | feat/helix-align |
| PRD Open Questions still open for Connect-safe decisions and LDP-to-ADR lift | stale | prd.md Open Questions vs newly-added ADR-010/011 and FEAT-028/ADR-013 | LOW — resolved decisions shown as open | feat/helix-align |

## Implementation Map

- **Topology**: `src/tablespec/` now spans the original library plus `core/` (logical-plan IR + renderer Protocol seam), `dbt/` (dbt emitter), `ldp/` (LDP sibling emitter), `e2e/` (compile orchestrator + backbone + manifest + paths), `session.py` (per-session capability probing), `profiling/native_profiler.py` (no-JVM profiler), and `validation/{gx_executor,native_executor}.py` (per-expectation Connect routing).
- **Entry Points**: Python API + `tablespec` CLI (`generate` emits sql/pyspark/json/ingest only); compile orchestrator `tablespec.e2e.compile`; bootstrap entry points `scripts/bootstrap_from_{tables,specs}.py`; runtime backbone `tablespec.e2e.backbone`.
- **Test Surfaces**: `tests/conformance/*` (engine matrix, dbt-spark/databricks executed, FK-orphan enforcement), `tests/e2e/*` (bootstrap DuckDB/Spark/Sail matrix), `tests/unit/test_profiler_connect_sail.py`, `tests/unit/test_validation_connect_sail.py`, `tests/ingest_parity/*`, `tests/dbt_roadmap/*`, `tests/integration/test_spark_session_fixture.py`.
- **Unplanned Areas**: None outstanding. dbt-core/dbt-duckdb and pysail live in the dev group (test-only), not user extras (prd.md "Dev/Test-only tooling"); the encapsulation test (`tests/test_core_encapsulation.py`) forbids `core → dbt` import.

## Acceptance Criteria Status

| Story / Feature | Criterion | Test Reference | Status | Evidence |
|-----------------|-----------|----------------|--------|----------|
| US-021 / FEAT-024 | Native profile on Connect, no PyDeequ, engine-correct dispatch | tests/unit/test_profiler_connect_sail.py | SATISFIED | native_profiler.py; deequ_mapper.py removed |
| US-022 / FEAT-025 | Compiled suite yields identical verdicts on classic & Connect; no silent false-negatives | tests/unit/test_validation_connect_sail.py | SATISFIED | gx_executor.py per-expectation routing; native_executor.py |
| US-023 / FEAT-026 | Path A/B bootstrap converge on one UMF list; compile across DuckDB/Spark/Sail | tests/e2e/test_bootstrap_from_{tables,specs}.py, test_e2e_matrix_no_spark.py | SATISFIED | e2e/{compile,backbone,manifest,paths}.py; manifest.json |
| US-024 / FEAT-026 | Runtime consumes only committed artifacts; no tablespec import at run time | tests/e2e/* (backbone) | SATISFIED | backbone executes manifest paths |
| US-025 / FEAT-027 | Deterministic dbt project (models, schema.yml, contracts, tests, seeds) | tests/conformance/test_dbt_spark_executed.py, tests/dbt_roadmap/* | SATISFIED | dbt/*; dbt-roadmap-acceptance.md |
| US-026 / FEAT-028 | LDP project emitted as committed artifact + conformance tier; siblings share core | tests/conformance/* (LDP tier), tests/golden/ldp_conformance/* | SATISFIED | ldp/project.py; ADR-013 seam |

## Gap Register

| Area | Classification | Planning Evidence | Implementation Evidence | Resolution Direction | Issue |
|------|----------------|-------------------|------------------------|----------------------|-------|
| Native Spark profiler | ALIGNED (this review) | FEAT-024, ADR-009, US-021, FR-5.1/5.2/5.5 | native_profiler.py; deequ removed | plan-to-code (specs caught up) | feat/helix-align |
| Serverless/Connect runtime | ALIGNED (this review) | ADR-010, FR-20.x, principle 3 | session.py; `_functions_for` dispatch | plan-to-code | feat/helix-align |
| Connect-safe GX validation | ALIGNED (this review) | FEAT-025, ADR-011, US-022, FR-7.7/7.8 | gx_executor.py/native_executor.py | plan-to-code | feat/helix-align |
| Compile orchestrator + bootstrap | ALIGNED (this review) | FEAT-026, ADR-012, US-023/024, FR-18.x | e2e/* + scripts/bootstrap_* | plan-to-code | feat/helix-align |
| dbt emitter | ALIGNED (this review) | FEAT-027, ADR-008, US-025, FR-19.1/19.2 | dbt/* | plan-to-code | feat/helix-align |
| LDP sibling emitter | ALIGNED (this review) | FEAT-028, ADR-013, US-026, FR-19.1/19.3 | ldp/* | plan-to-code (lifted from design note) | feat/helix-align |
| Raw→ingest SQL artifact | ALIGNED | ADR-007, FR-19.4 | schemas/ingest_generator.py | — | — |
| Cross-engine conformance harness | ALIGNED | conformance-acceptance.md, gold-conformance-plan.md, FR-18.5 | tests/conformance/* | — | — |
| FR-5.5 Deequ-as-legacy claim | STALE_PLAN → fixed | prd.md FR-5.5 | deequ_mapper.py removed | plan-to-code | feat/helix-align |
| US-007 Deequ acceptance | STALE_PLAN → fixed | US-007 | deequ removed | plan-to-code | feat/helix-align |
| FEAT-029 cross-reference | STALE_PLAN → fixed | ADR-013, FEAT-028 | dbt emitter is FEAT-027 | plan-to-plan | feat/helix-align |

### Quality Findings

| Area | Dimension | Concern | Severity | Resolution | Issue |
|------|-----------|---------|----------|------------|-------|
| GX custom expectations on Connect | robustness | ~~Custom-expectation pandas paths not fully Connect-parity-tested (P2 known gap)~~ — **RESOLVED** (feat/close-gaps): all four customs are verdict- and value-equal across classic and Connect | low → closed | `tests/unit/test_custom_gx_parity.py` asserts identical `success` + `unexpected_count` + `partial_unexpected_list` on both engines | feat/close-gaps |

## Traceability Matrix

| Capability | Vision | Requirement | Feature | User Story | Arch/ADR | Design | Tests | Code | Classification |
|-----------|--------|-------------|---------|-----------|----------|--------|-------|------|----------------|
| Native Spark profiler | "deterministic compile … runs first-class on serverless/Connect" | FR-5.1, FR-5.2, FR-5.5 | FEAT-024 | US-021 | ADR-009, ADR-010 | FEAT-005 §profiling | test_profiler_connect_sail.py | profiling/native_profiler.py | ALIGNED |
| Serverless / Spark Connect runtime | "same UMF runs first-class on classic Spark and Databricks serverless / Spark Connect" | FR-20.1–FR-20.4 | FEAT-024, FEAT-025 | US-021, US-022 | ADR-010 | serverless-compatibility.md, principles §3 | test_profiler_connect_sail.py, test_validation_connect_sail.py, test_spark_session_fixture.py | session.py, `_functions_for` dispatch | ALIGNED |
| Connect-safe GX validation | "GX validation suites" as committed artifacts that run on the production engine | FR-7.7, FR-7.8, FR-20.4 | FEAT-025 | US-022 | ADR-011, ADR-005 | FEAT-007, data-quality-expectations.md | test_validation_connect_sail.py, test_gx_harness.py | validation/gx_executor.py, validation/native_executor.py | ALIGNED |
| Compile orchestrator + bootstrap | "deterministic compile step emits the complete set of committed runtime artifacts … runtime reads only the committed artifacts" | FR-18.1–FR-18.5 | FEAT-026 | US-023, US-024 | ADR-012 | architecture.md | tests/e2e/test_bootstrap_from_{tables,specs}.py, test_e2e_matrix_no_spark.py | e2e/{compile,backbone,manifest,paths}.py, scripts/bootstrap_* | ALIGNED |
| dbt project emitter | "dbt ingest and gold-DAG projects" | FR-19.1, FR-19.2 | FEAT-027 | US-025 | ADR-008, ADR-013 | architecture.md, core seam | conformance/test_dbt_spark_executed.py, dbt_roadmap/* | dbt/*, core/* | ALIGNED |
| LDP sibling emitter | "LDP projects … on a shared target-agnostic core seam" | FR-19.1, FR-19.3 | FEAT-028 | US-026 | ADR-013 | ldp-sibling-emitter.md | conformance LDP tier, golden/ldp_conformance/* | ldp/project.py | ALIGNED |
| Raw→ingest SQL artifact | "raw→ingest … SQL plans" as committed artifacts | FR-19.4 | (within FEAT-026/027) | US-023 | ADR-007 | architecture.md | tests/ingest_parity/*, unit/test_ingest_generator.py | schemas/ingest_generator.py | ALIGNED |
| Cross-engine conformance harness | "multi-engine result parity on the conformance harness" | FR-18.5 | (governs all emitters) | — | — | conformance-acceptance.md, gold-conformance-plan.md | tests/conformance/* | tests/conformance/engines.py | ALIGNED |

## Execution Issues Generated

| Issue ID | Type | Labels | Goal | Dependencies | Verification |
|----------|------|--------|------|--------------|-------------|
| (none) | — | — | All gaps resolved in-review as plan-to-code doc updates on feat/helix-align | — | `git diff` on docs/helix/ + grep audit below |

No execution issues remain: every gap was a stale-or-missing spec resolved by writing/updating docs to govern the (correct, vision-consistent) implementation. No product code was changed.

## Issue Coverage

| Gap / Criterion | Covering Issue | Status |
|-----------------|----------------|--------|
| Six ungoverned capabilities | Specs added/reconciled this session | covered |
| FR-5.5 / US-007 Deequ-stale | This review (edits) | covered |
| FEAT-029 cross-reference | This review (edits) | covered |
| PRD Open Questions resolved-but-open | This review (edits) | covered |
| GX custom-expectation Connect parity (P2) | `tests/unit/test_custom_gx_parity.py` (feat/close-gaps) | resolved |

## Execution Order

1. Reconcile stale claims that contradict shipped code (FR-5.5, US-007, FEAT-029 refs, PRD Open Questions) — done in this review.
2. Verify end-to-end traceability per capability (matrix above) — done.
3. Stage + commit all doc changes on feat/helix-align with `--no-verify`.

**Critical Path**: stale-claim fixes → traceability verification → commit | **Parallel**: none | **Blockers**: none. Human verifies + merges to main.

## Open Decisions

| Decision | Status | Governing Artifacts | Resolution |
|----------|--------|---------------------|------------|
| Promote GX custom-expectation Connect parity from P2 known-gap to a tested guarantee | **RESOLVED** (feat/close-gaps) | test-plan.md, FEAT-025, gx_executor.py, custom_gx_expectations.py | All four customs proven verdict- and value-equal across classic `add_spark` and the native Connect path by `tests/unit/test_custom_gx_parity.py`. The native column-pair validator was aligned to emit GX's `[column_A, column_B]` `partial_unexpected_list` rendering so the sample list matches byte-for-byte, not just `success` + `unexpected_count`. |

No open decisions remain.

## Confirmation: No Spec Invalidates a Shipped Feature

A tree-wide grep audit was run for claims that would contradict the native profiler, serverless/Connect runtime, Connect-safe GX validation, dbt emitter, LDP emitter, or e2e bootstrap:

- **PyDeequ-as-default / "Deequ remains"**: only remaining `deequ` references are historical (backfill report), removal records (FEAT-005, ADR-009, FR-5.5), or reconciled stories (US-007, US-021). No spec asserts PyDeequ is the live profiler.
- **"metadata-only / no data processing"**: PRD Out of Scope explicitly scopes data-processing capabilities (profiling, validation, merge) to UMF-driven committed-artifact workflows via `[spark]`; no contradiction with the shipped runtime.
- **"classic Spark only / no Connect"**: every "classic Spark" reference frames it as one of two first-class targets, or as a problem-statement being solved by ADR-010/011. No spec asserts Connect/serverless is unsupported.
- **FEAT-029 dangling reference**: removed (now FEAT-027). `grep FEAT-029 docs/` returns nothing.

No remaining spec contradicts a shipped feature.
