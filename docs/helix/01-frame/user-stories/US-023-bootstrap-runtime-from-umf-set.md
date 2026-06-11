---
ddx:
  id: US-023
---

# US-023: Bootstrap a runtime from a UMF set (Path A / Path B)

**Feature**: FEAT-026 — Compile Orchestrator & Bootstrap Pipeline
**Feature Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-10, ORCH-20, ORCH-21
**PRD Requirements**: FR-18.1, FR-18.2, FR-18.4, FR-18.5
**Priority**: P0
**Status**: Approved

## Story

**As a** data engineer onboarding tables onto the healthcare platform
**I want** to produce a UMF set from either an existing table or an authored spec and compile it in one step into the full committed artifact set
**So that** I can stand up a reviewable, diffable runtime for a table without hand-authoring DDL, GX suites, dbt, or LDP per tool

## Context

A table's truth lives in its UMF, but a UMF is not directly runnable. Today the
only generation surface is the CLI `generate` command, which emits sql/pyspark/
json/ingest for a single table — not the multi-table gold DAG, LDP project, or
compiled GX suite, and with no manifest a runtime could consume. This story
delivers the two bootstrap entry points and the compile orchestrator so a data
engineer goes from "a UMF (inferred or authored)" to "a pinned, manifested artifact
tree" in one path-agnostic step. It exercises ORCH-01/02/03 (entry points) and
ORCH-10/20/21 (orchestration + manifest).

## Walkthrough

1. User chooses Path A (an existing Spark table) or Path B (an authored UMF spec directory or JSON artifact).
2. Path A: the system reflects `spark.table(name)` into a UMF and, by default,
   profiles the data to build profile-derived expectations. Path B: the system
   loads the authored spec into a UMF. Both produce the same `list[UMF]`.
3. User calls the compile orchestrator on that UMF set with an output directory.
4. System drives every compile seam and writes one committed artifact each under
   the pinned layout — ingest SQL, DDL, PySpark schema, JSON schema, compiled GX
   suite, single-table dbt ingest project, the multi-table gold dbt DAG, the LDP
   project — and serializes a `CompiledArtifacts` manifest enumerating every path.
5. User reviews the generated transforms as ordinary diffs and re-loads the
   manifest from disk to confirm the artifact tree is self-describing.

## Acceptance Criteria

- [ ] **US-023-AC1** — Given an existing Spark table, when the user runs Path A with `profile=True`, then a UMF is reflected for the table and a profile-derived expectation list is returned for it (`paths.py:43`).
- [ ] **US-023-AC2** — Given an authored UMF spec directory or JSON artifact, when the user runs Path B, then the spec loads into a UMF with no Spark session required (`paths.py:92`).
- [ ] **US-023-AC3** — Given a `list[UMF]` from either path, when the user calls `compile_umfs`, then one committed artifact is persisted per seam under the pinned layout and a `manifest.json` is written (`compile.py:72`, `manifest.py:239`).
- [ ] **US-023-AC4** — Given a multi-table set with at least one gold-deriving table, when the set is compiled, then the multi-table gold dbt DAG and the per-target gold SQL plan are both emitted as distinct artifacts (`compile.py:127`, `:216`).
- [ ] **US-023-AC5** — Given a written manifest, when the user calls `CompiledArtifacts.load(root)`, then every recorded path re-absolutizes against the root and resolves to an existing file/dir (`manifest.py:245`).
- [ ] **US-023-AC6** — Given the bootstrap pipeline, when it is run across the DuckDB / Spark / Sail matrix, then every engine produces the artifact set and a green backbone run (FR-18.5).

## Edge Cases

- **Pure-ingest set (no gold target)**: the gold DAG and per-target gold plans are
  absent (not malformed); compile still succeeds (`compile.py:127`).
- **Path A schema-only (`profile=False`)**: no enriched suite is returned; the
  orchestrator generates the baseline suite from the UMF instead (`paths.py:82`).
- **Schema-qualified Path A table name**: reflected to a bare-name UMF so the
  compiled raw/ingested tables stay unqualified (`paths.py:74`).
- **Path B spec with no sibling raw CSV**: compile runs to completion; there is
  simply nothing to ingest in the backbone leg (`bootstrap_from_specs.py:95`).

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Path A reflect + profile | US-023-AC1 | An existing Spark table `member` | `umfs_from_tables(spark, ["member"], profile=True)` | `([UMF(member)], {"member": [expectation dicts]})` |
| Path B load | US-023-AC2 | `member/` or `member.json` | `umfs_from_specs(["member/"])` | `[UMF(member)]`, no Spark used |
| Compile emits full set | US-023-AC3 | `[UMF(member)]` + out dir | `compile_umfs(umfs, out, source="specs")` | ingest/ddl/pyspark/json/suite/dbt_ingest persisted; `manifest.json` exists |
| Distinct gold artifacts | US-023-AC4 | set incl. `claim_enriched` (gold) | `compile_umfs(..., gold_targets=["claim_enriched"])` | `dbt_gold/` project AND `gold_plan/claim_enriched.plan.sql` both present |
| Manifest round-trips | US-023-AC5 | a written compile tree | `CompiledArtifacts.load(root)` | all paths resolve; `member` bundle has existing files |

## Dependencies

- **Stories**: None (this story produces the artifact tree US-024 consumes).
- **Feature Spec**: FEAT-026
- **Feature Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-10, ORCH-20, ORCH-21
- **PRD Requirements**: FR-18.1, FR-18.2, FR-18.4, FR-18.5
- **External**: Spark (classic or Connect) for Path A reflection/profiling; DuckDB /
  Sail for the engine matrix; the dbt/LDP/GX/native-profiler generation seams.

## Out of Scope

- Backbone execution of the artifacts — owned by US-024.
- A user-facing `tablespec compile` CLI command (the orchestrator is a library +
  demo-script surface).
- The internals of the individual generator seams.

## Review Checklist

- [x] Stored as its own file `US-023-<slug>.md`
- [x] Covers one persona (data engineer) completing one goal (bootstrap → compile), demonstrable end-to-end
- [x] Links to parent FEAT-026 and names the PRD FRs it covers (FR-18.1/18.2/18.4/18.5)
- [x] Every acceptance criterion is independently testable and carries a stable `US-023-ACm` ID
- [x] Walkthrough traces trigger → outcome; edge cases documented
