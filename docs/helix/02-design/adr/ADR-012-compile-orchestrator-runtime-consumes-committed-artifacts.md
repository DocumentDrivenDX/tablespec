---
ddx:
  id: ADR-012
---

# ADR-012: Compile Orchestrator — Runtime Consumes Only Committed Artifacts

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Platform / Data Engineering | FEAT-026 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | One UMF must compile into the full set of runtime artifacts (ingest SQL, DDL, PySpark, JSON schema, GX suite, dbt ingest + gold DAG, LDP, gold plan), but the CLI `generate` emits only sql/pyspark/json/ingest for one table (`src/tablespec/cli.py`). There is no single orchestrator and no defined hand-off for a runtime to execute the output. |
| Current State | Generation seams exist independently (`schemas/generators.py`, `gx_baseline.py`, `dbt/*`, `ldp/*`, `schemas/ingest_generator.py`). Each consumer re-derives artifact names and re-invokes seams ad hoc; a runtime that imports tablespec to re-derive schema couples production to the library. |
| Requirements | FR-18.1 (compile orchestrator), FR-18.2 (pinned manifest layout), FR-18.3 (runtime consumes only committed artifacts), FR-18.4 (path-agnostic bootstrap), FR-18.5 (engine matrix). Vision: "the runtime never re-derives schema or transforms from UMF; it reads only the committed artifacts." |
| Decision Drivers | Zero drift between UMF and what runs; transforms reviewable as diffs; runtime carries no tablespec dependency; same artifacts run on classic Spark, Sail (Connect), and Databricks serverless. |

## Decision

We will introduce an explicit **compile orchestrator** (`tablespec.e2e.compile.compile_umfs`)
that takes a `list[UMF]`, drives every compile seam, and **persists one committed
artifact each** under a **pinned layout** described by a serialized
`CompiledArtifacts` manifest (`tablespec.e2e.manifest`). A separate **runtime
backbone** (`tablespec.e2e.backbone.run_backbone`) then executes **only those
committed artifacts**, resolved from disk via the manifest — it never re-derives
schema or transforms from the UMF and never imports a tablespec generation seam at
run time. Two **path-agnostic bootstrap entry points** (`tablespec.e2e.paths`) feed
the orchestrator: Path A reflects (and by default profiles) existing tables; Path B
loads UMF specs. Both produce the same `list[UMF]`, so the compile is identical
regardless of origin.

**Key Points**: UMF → committed artifacts → runtime reads ONLY artifacts (compile-once, run-from-artifacts) | Pinned, relocatable manifest is the compile↔runtime contract | Path A / Path B converge on one path-agnostic compile

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Runtime imports tablespec and re-derives schema/transforms from UMF on the fly | No artifact tree to manage; always "fresh" from UMF | Couples production runtime to the library; transforms are not diffable in review; re-derivation can drift from what was reviewed; pulls dbt/LDP/Spark deps into the runtime | Rejected: violates the vision's "runtime reads only committed artifacts" and the zero-drift / runtime-independence success metrics |
| Extend the CLI `generate` command to emit the full set per table | Reuses an existing surface | Per-table, not per-set (no multi-table gold DAG / FK resolution); still no manifest contract or runtime consumer; conflates an authoring command with a runtime-artifact compiler | Rejected: cannot express whole-set seams (gold DAG, LDP) or the runtime hand-off; `generate` stays scoped to single-table authoring output |
| Implicit layout (each consumer recomputes artifact paths) | No manifest to write | Every consumer re-derives filenames; relocation breaks; no single provenance record; runtime cannot be driven purely from disk | Rejected: brittle and un-relocatable; the pinned manifest is what makes the runtime artifact-only |
| **Compile orchestrator + pinned manifest + artifact-only backbone (selected)** | One orchestrator emits the full set; manifest is a relocatable, loadable contract; runtime needs no tablespec import; path-agnostic bootstrap | Adds an artifact tree + manifest to manage; introduces a `tablespec.e2e` surface distinct from the per-seam generators | **Selected: it is the only option that delivers diffable transforms, zero drift, and a runtime with no library dependency — the vision's compile-once/run-from-artifacts model** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Runtime executes committed, reviewable artifacts with no tablespec import; recompile-and-diff makes UMF↔artifact drift detectable in CI; one orchestrator replaces ad-hoc per-consumer generation; the same manifest runs across DuckDB / Spark / Sail / serverless |
| Negative | A compiled artifact tree + `manifest.json` must be committed and kept in sync (recompile on UMF change); the `tablespec.e2e` orchestrator/backbone is an added surface to maintain alongside the per-seam generators |
| Neutral | The CLI `generate` command stays scoped to single-table sql/pyspark/json/ingest output and is explicitly NOT the compiler (documented in `manifest.py:10`); provenance (`source`, `profile_enriched`) is recorded but does not change the compile |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Committed artifacts drift from the UMF that produced them | L | H | Persist a UMF snapshot per compile (`compile.py:186`); recompile + byte-diff artifacts in CI; deterministic seams |
| A runtime path accidentally re-derives from UMF / imports a generation seam | L | H | Backbone consumes the manifest only; e2e asserts an artifact-only run (`tests/e2e/test_bootstrap_from_specs.py:4`); the wheel ships no `tests/` and the backbone reuses shipped helpers (`backbone.py:26`) |
| Pinned layout churn breaks consumers | L | M | Filenames are single-sourced as layout constants in `manifest.py`; the manifest, not hard-coded paths, is the consumer contract |
| A whole-set seam emits a malformed artifact for an ill-formed set | L | M | Fail-closed omission (e.g. no gold DAG for a pure-ingest set), not malformed emission (`compile.py:127`) |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `compile_umfs` emits the full committed set + a loadable manifest for a multi-table set (`tests/e2e/test_bootstrap_from_specs.py`) | A new runtime artifact type is added that the orchestrator does not emit |
| Backbone runs green consuming only committed artifacts across DuckDB / Spark / Sail (FR-18.5) | A runtime consumer is found re-deriving schema from UMF or importing a generation seam |
| Zero UMF→artifact drift (recompile + diff in CI) | Recompiling a UMF set produces a non-empty artifact diff with no UMF change |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **Concern selection**: This ADR selects the compile-once / run-from-artifacts
  boundary as the project's runtime-coupling concern: the runtime↔library boundary
  is the manifest, not a Python import.
- **Practice override**: None — it does not override a library concern practice.

## References

- PRD: Subsystem "Compile Orchestration & Bootstrap" (FR-18.1–18.5); Goal 2;
  Success Metrics "UMF→artifact drift" and "Runtime independence"; Open Question on
  the compile-orchestrator ADR (now resolved by this ADR)
- Product Vision: "Compile to committed runtime artifacts" / "Compile-once,
  run-from-artifacts" value propositions
- FEAT-026 — Compile Orchestrator & Bootstrap Pipeline
- Related ADRs: ADR-007 (raw→ingest SQL artifact), ADR-008 (dbt adoption
  architecture) — committed-artifact seams this orchestrator drives
- Evidence: `src/tablespec/e2e/compile.py`, `manifest.py`, `paths.py`,
  `backbone.py`; `scripts/bootstrap_from_{tables,specs}.py`

## Review Checklist

- [x] Context names a specific problem — no single orchestrator; CLI `generate` is single-table only
- [x] Decision statement is actionable ("we will introduce …")
- [x] At least two alternatives evaluated (four)
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete
- [x] Consistent with the governing FEAT-026 and PRD FR-18.x
