---
ddx:
  id: US-025
---

# US-025: Emit a dbt Project from UMF

**Feature**: FEAT-027 — dbt Project Emitter
**Feature Requirements**: DBT-01, DBT-02, DBT-03, DBT-05, DBT-08, DBT-09, DBT-12
**PRD Requirements**: FR-19.2 (dbt emitter), FR-19.1 (shared core seam)
**Priority**: P0
**Status**: Done (acceptance criteria met; emitter + opt-in `DbtRunner` shipped — see FEAT-027 DBT-14/15/16)

## Story

**As a** data engineer maintaining healthcare ETL pipelines
**I want** to compile one UMF (or a UMF set) into a complete, buildable dbt project
**So that** the dbt transforms, contracts, and tests are committed, reviewable diffs derived
from the single source of truth — not hand-authored per table and drifting from the GX suite.

## Context

dbt models, `schema.yml` contracts/tests, sources, and scaffolding are otherwise authored by
hand and reconciled against the SQL and GX representations manually, which drifts. This story
exercises FEAT-027's two emitters — `generate_dbt_project` (single-table ingest) and
`generate_dbt_dag_project` (multi-table gold DAG) — both of which reuse the shared cast core
and the shared `core.schema_facts`, so the dbt artifact asserts the same UMF-derived
constraints as the GX suite. Generation must work without the dbt runtime installed (dbt is a
dev/test-only tool), so the engineer can compile anywhere `tablespec` is present.

## Walkthrough

1. Engineer edits (or infers) a table's UMF and calls `generate_dbt_project(umf_data)`.
2. System reuses `build_ingest_select` for the model body, derives the write strategy from
   `ingestion.mode` + `primary_key`, and returns a `{relative_path: contents}` mapping for a
   complete project (model SQL, `schema.yml`, `sources.yml`, `dbt_project.yml`, `profiles.yml`).
3. Engineer reviews the generated files as an ordinary code-review diff.
4. For the whole platform, the engineer calls `generate_dbt_dag_project(umfs)`; the system
   builds the IR, fails closed on cycles/dangling refs, and renders `ingested_<t>` staging +
   `gold_<t>` mart models with `{{ ref() }}`/`{{ source() }}` edges and enforced contracts.
5. A CI/test lane (with the dev group installed) runs `dbt build` against the DuckDB / Spark /
   Databricks targets and the project builds and tests green — without `tablespec` having
   shipped dbt as a user dependency.

## Acceptance Criteria

- [x] **US-025-AC1** — Given a UMF with `ingestion.mode='incremental'` and a single-column
  `primary_key`, when `generate_dbt_project` runs, then the model `{{ config }}` is
  `materialized='incremental'`, `incremental_strategy='merge'`, `unique_key=[<pk>]` with
  `on_schema_change='fail'`, and the body applies the dedup-latest window.
  *(golden `tests/golden/dbt_project/incremental_pk/`; `tests/ingest_parity/test_dbt_idempotency.py`)*
- [x] **US-025-AC2** — Given a UMF with a non-nullable column and a single-column PK, when the
  emitter runs, then `schema.yml` declares an enforced contract with that column's
  `data_type` + a `not_null` constraint and a `unique` generic test, and no duplicate
  generic `not_null` test is emitted.
  *(`tests/dbt_roadmap/test_contracts_functional.py`, `test_schema_tests_functional.py`)*
- [x] **US-025-AC3** — Given a UMF set whose gold table references another emitted table by FK,
  when `generate_dbt_dag_project` runs, then the gold model carries a `relationships` test
  pointing at the referenced table's emitted model; an FK to a table in no UMF (not external)
  is skipped, never a dangling `ref()`.
  *(`tests/dbt_dag/test_dbt_dag_ref_branches.py`, golden `tests/golden/dbt_dag_project/`)*
- [x] **US-025-AC4** — Given a UMF set with a dependency cycle or a gold reference to an
  unknown, non-external relation, when `generate_dbt_dag_project` runs, then it raises
  `DbtProjectError` (fail closed), not a silently-dropped edge.
  *(`tests/dbt_dag/test_dbt_dag_ref_branches.py`)*
- [x] **US-025-AC5** — Given an environment with the dbt runtime packages NOT installed, when
  `generate_dbt_project` / `generate_dbt_dag_project` are imported and called, then they
  succeed (no `import dbt` at generation time).
  *(`test_src_never_imports_dbt`; the `DbtRunner` lazy-imports the dbt CLI only inside `build`)*

## Edge Cases

- **Composite FK**: emitted as one `relationships` test per scalar column.
- **spark/databricks incremental merge**: `file_format='delta'` is pinned so the merge
  materializes and downstream tests are not silently skipped.
- **`related` sibling not emitted**: an FK whose target is neither this table nor an emitted
  `related` model is skipped (skip-when-unresolvable).
- **Keyless incremental**: blind append (no dedup); contract is one batch per run.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Incremental + PK merge config | US-025-AC1 | UMF, `mode=incremental`, `primary_key=[id]` | `generate_dbt_project(umf)` | `models/<t>.sql` config has `incremental_strategy='merge'`, `unique_key=["id"]`, `on_schema_change='fail'`; body has dedup window |
| Enforced contract + unique | US-025-AC2 | UMF, non-null col `c`, PK `[id]` | inspect `models/schema.yml` | `c` has `data_type` + `not_null` constraint; `id` has `data_tests: [unique]`; no generic `not_null` test |
| FK relationships + skip | US-025-AC3 | UMF set, gold FK to emitted table + FK to absent table | `generate_dbt_dag_project(umfs)` | resolvable FK → `relationships` test on emitted model; absent-table FK → no test |
| Fail closed on cycle | US-025-AC4 | UMF set with a dependency cycle | `generate_dbt_dag_project(umfs)` | raises `DbtProjectError` |
| Generate without dbt installed | US-025-AC5 | env without dbt-core | import + call generator | returns project mapping, no `ModuleNotFoundError` |

## Dependencies

- **Stories**: none (foundational for the dbt backend).
- **Feature Spec**: FEAT-027.
- **Feature Requirements**: DBT-01, DBT-02, DBT-03, DBT-05, DBT-08, DBT-09, DBT-12.
- **PRD Requirements**: FR-19.2, FR-19.1.
- **External**: dbt-core / dbt-duckdb / dbt-spark / dbt-databricks for the *execution* test
  lane only (dev group); generation itself has no dbt dependency.

## Out of Scope

- Executing dbt at run time as a product surface (the runtime consumes committed artifacts).
- `state:modified` CI selection and seed emission (covered by DBT-10/DBT-11; separate slices).
- Production Databricks dbt execution as a supported runtime target; the shipped
  `DbtRunner` and CLI `emit --backend dbt [--run]` path are opt-in dev/test
  execution surfaces for generated projects.

## Review Checklist

- [x] Stored as its own file `US-025-<slug>.md`
- [x] Covers one persona (data engineer) completing one goal (emit a dbt project from UMF)
- [x] Links to parent FEAT-027 and names PRD FR-19.2 / FR-19.1
- [x] Every acceptance criterion is independently testable with a stable `US-025-ACm` ID
- [x] Walkthrough traces trigger → outcome; edge cases documented
