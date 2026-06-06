---
ddx:
  id: US-024
---

# US-024: Runtime consumes only compiled artifacts

**Feature**: FEAT-026 — Compile Orchestrator & Bootstrap Pipeline
**Feature Requirements**: ORCH-21, ORCH-30, ORCH-31
**PRD Requirements**: FR-18.3
**Priority**: P0
**Status**: Approved

## Story

**As a** data engineer running a table's pipeline in CI and production
**I want** the runtime backbone to execute only the committed compiled artifacts, loaded from disk via the manifest
**So that** production runs the exact diffable transforms that were reviewed, with no tablespec import and no risk of re-deriving a different result from the UMF

## Context

The whole point of compile-once / run-from-artifacts is that the runtime carries no
library dependency and runs precisely what was committed and reviewed. If the
runtime re-derived schema or transforms from the UMF, it would couple production to
tablespec and could drift from the reviewed artifacts. This story delivers the
runtime backbone that resolves every artifact from the `CompiledArtifacts` manifest
on disk and executes the staged runtime — ingest raw→row, validate raw, typed
transform, validate ingested, transforms — consuming only those committed
artifacts. It exercises ORCH-30/31 and depends on the manifest contract (ORCH-21).

## Walkthrough

1. User has a compiled artifact tree (from US-023) and raw input batches per table.
2. User loads the manifest from disk (`CompiledArtifacts.load(root)`) and calls the
   backbone with a Spark/Connect session and the raw batches.
3. System resolves each table's artifacts by path from the manifest — never from
   the UMF — and executes the compiled split ingest SQL to land raw→row.
4. System validates raw and ingested DataFrames using the compiled GX suite JSON,
   staging raw-stage vs ingested-stage expectations at execute time, then runs the
   compiled typed transform and the transform legs (dbt parse, gold plan, LDP).
5. System reports a per-stage outcome; a green run proves the compiled output is a
   self-sufficient runtime contract with no tablespec generation at run time.

## Acceptance Criteria

- [ ] **US-024-AC1** — Given a written manifest, when the backbone runs, then it resolves each table's artifacts via `CompiledArtifacts.load`/`.table(name)` and consumes them from disk, not from any UMF (`backbone.py:545`, `manifest.py:245`).
- [ ] **US-024-AC2** — Given a compiled ingest SQL artifact, when the backbone ingests a raw batch, then raw and ingested DataFrames are materialized from `<table>.ingest.sql` (`backbone.py:575`).
- [ ] **US-024-AC3** — Given the compiled GX suite JSON, when the backbone validates, then one staged execution classifies and runs raw-stage vs ingested-stage expectations against the correct DataFrame (`backbone.py:594`).
- [ ] **US-024-AC4** — Given a full bootstrap run, when it completes green, then no tablespec generation seam was imported at run time and the backbone consumed only persisted artifacts (asserted by `tests/e2e/test_bootstrap_from_specs.py:4`).
- [ ] **US-024-AC5** — Given the same compiled tree, when the backbone runs on DuckDB, classic Spark, and Sail (Connect), then every backend executes the committed artifacts and reports its stages (FR-18.5).

## Edge Cases

- **A stage fails (e.g. profile-derived `in_set` correctly rejects raw dirt)**: the
  backbone records that stage as failed with detail and continues; dirt-catching is
  correct behaviour, not a harness error (`backbone.py:585`).
- **Connect (Sail) cannot run a Delta `MERGE`**: the backbone materializes the inner
  typed SELECT extracted from the compiled `MERGE ... USING ( ... )` instead, so the
  Connect path still consumes the same compiled transform (`backbone.py:88`).
- **Relocated artifact tree**: because manifest paths are stored relative to root,
  `load` re-absolutizes against the new root and the backbone still resolves every
  artifact (`manifest.py:203`, `:245`).

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Artifacts resolved from disk | US-024-AC1 | a compiled tree + manifest | `CompiledArtifacts.load(root)` then `run_backbone(...)` | each `ta = artifacts.table(name)` resolves; no UMF read |
| Ingest from compiled SQL | US-024-AC2 | `member` batch CSV | backbone ingest stage | raw+ingested DataFrames materialized from `member.ingest.sql` |
| Staged validation | US-024-AC3 | compiled `member.suite.json` | backbone validate stage | raw-stage + ingested-stage expectations run against correct DF |
| Artifact-only invariant | US-024-AC4 | full Path B bootstrap | `tests/e2e/test_bootstrap_from_specs.py` | green; backbone consumed only persisted artifacts |
| Engine matrix | US-024-AC5 | same compiled tree | run on duckdb / spark / sail | each backend reports per-stage outcomes |

## Dependencies

- **Stories**: US-023 (produces the compiled artifact tree + manifest this story consumes).
- **Feature Spec**: FEAT-026
- **Feature Requirements**: ORCH-21, ORCH-30, ORCH-31
- **PRD Requirements**: FR-18.3
- **External**: a Spark (classic or Connect) session as the execution/validation
  substrate; the staged GX executor (FR-7.7/7.8); DuckDB / Sail for the matrix.

## Out of Scope

- Producing the artifacts — owned by US-023.
- The per-expectation Connect-safe validation *routing* internals (FR-7.7), owned by
  FEAT-007 / the Runtime Platform subsystem; this story consumes that executor.
- Real Databricks-serverless remote execution gating (local success never depends on
  a remote workspace; `backbone.py:30`).

## Review Checklist

- [x] Stored as its own file `US-024-<slug>.md`
- [x] Covers one persona (data engineer) completing one goal (run from committed artifacts), demonstrable end-to-end
- [x] Links to parent FEAT-026 and names the PRD FR it covers (FR-18.3)
- [x] Every acceptance criterion is independently testable and carries a stable `US-024-ACm` ID
- [x] Walkthrough traces trigger → outcome; edge cases documented
