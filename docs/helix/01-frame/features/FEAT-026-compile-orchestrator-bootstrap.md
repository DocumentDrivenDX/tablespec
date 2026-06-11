---
ddx:
  id: FEAT-026
---

# Feature Specification: FEAT-026 — Compile Orchestrator & Bootstrap Pipeline

**Feature ID**: FEAT-026
**Status**: Approved
**Priority**: P0
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Compile Orchestration & Bootstrap
**Covered PRD Requirements**: FR-18.1, FR-18.2, FR-18.3, FR-18.4, FR-18.5
**Cross-Subsystem Rationale**: None — single subsystem. The bootstrap entry points
(Path A / Path B) and the compile orchestrator are one capability: produce a UMF
set, compile it to committed artifacts, and run the runtime from those artifacts.

## Overview

This feature is the *compile orchestrator* that turns a UMF set into the full set
of committed runtime artifacts, plus the two *bootstrap* entry points that produce
that UMF set (Path A: inferred from existing tables; Path B: loaded from specs). It
realizes the PRD's central goal — "compile one UMF deterministically into the full
set of committed runtime artifacts (direct SQL, dbt projects, LDP, GX suites), with
the runtime consuming only those artifacts" (PRD Goal 2, FR-18.1/18.3).

## Ideal Future State

A data engineer onboards a table by producing a UMF — either by pointing the
bootstrap at an existing Spark table (Path A reflects, and by default profiles, it)
or by loading an authored spec (Path B). They run one compile step. tablespec
writes a pinned artifact layout (`ingest/<t>.ingest.sql`, `schemas/<t>.ddl.sql` /
`.schema.py` / `.schema.json`, `validation/<t>.suite.json`, a single-table dbt
ingest project, the multi-table gold dbt DAG, an LDP project, and per-target gold
SQL plans) and a `manifest.json` that enumerates every persisted path. The runtime
backbone then executes only those committed artifacts, resolved purely from disk
via the manifest — it never re-derives schema or transforms from the UMF and never
imports tablespec at run time. The compile is path-agnostic: both bootstrap paths
converge on the same `list[UMF]` and the same compiled output.

## Problem Statement

- **Current situation**: The CLI `generate` command emits only sql/pyspark/json/
  ingest for one table at a time (`src/tablespec/cli.py`); there is no single
  command that compiles a UMF *set* into every runtime artifact, and no defined
  hand-off contract for a runtime to consume them.
- **Pain points**: Without one orchestrator and a pinned manifest, every consumer
  re-derives artifact names and re-runs generation seams ad hoc; a runtime that
  imports tablespec to re-derive schema couples production to the library and
  invites drift between what was reviewed and what runs.
- **Desired outcome**: One orchestrator compiles a UMF set to a pinned, manifested
  artifact layout; a runtime backbone executes only those artifacts; both bootstrap
  paths feed the same orchestrator. Measurable: a green end-to-end run where the
  backbone loads artifacts from disk and never touches the UMF.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Bootstrap entry points | "How do I get a UMF set to compile — from a table or from a spec?" | Path A reflects (+ optionally profiles) existing tables; Path B loads specs; both return `list[UMF]` |
| Compile orchestration | "How do I turn that UMF set into every committed artifact at once?" | Drive each compile seam, persist one artifact each under the pinned layout, emit the manifest |
| Manifest & layout | "Where is each artifact, deterministically?" | Pin filenames/dirs; serialize a relocatable `CompiledArtifacts` manifest the runtime resolves |
| Runtime consumption | "How does the runtime run without re-deriving schema?" | The backbone loads the manifest from disk and executes only the committed artifacts |

## Requirements

### Functional Requirements by Area

#### Bootstrap Entry Points

ORCH-01. Path A (`umfs_from_tables`) SHALL reflect each named Spark table into a
UMF via `SparkToUmfMapper`, and by default additionally profile it (native
profiler + `ProfileToGxMapper`) and return profile-derived expectation lists so the
compiled suite is data-enriched; `profile=False` SHALL yield the schema-only
baseline path. (`src/tablespec/e2e/paths.py:43`)
ORCH-02. Path B (`umfs_from_specs`) SHALL load each authored spec directory or
JSON artifact into a UMF with no Spark required to load; legacy single-file YAML
is migration-only. (`src/tablespec/e2e/paths.py:92`)
ORCH-03. Both paths SHALL return the same `list[UMF]` type so the orchestrator is
path-agnostic; Path A's reflected dict SHALL be normalized to the strict UMF model
shape (`version`, `Nullable`-shaped `nullable`). (`src/tablespec/e2e/paths.py:106`)

#### Compile Orchestration

ORCH-10. `compile_umfs` SHALL drive every compile seam and persist one committed
artifact each per table: ingest SQL, DDL, PySpark schema source, JSON schema,
compiled GX suite, and the single-table dbt ingest project; plus, once per compile
spanning the set, the multi-table gold dbt DAG project and the LDP project.
(`src/tablespec/e2e/compile.py:72`, `:158`)
ORCH-11. The compiled GX suite SHALL be the profile-enriched expectation list when
the caller supplies one for that table (Path A), and the generated baseline suite
otherwise. (`src/tablespec/e2e/compile.py:206`)
ORCH-12. A per-target gold SQL plan SHALL be emitted only for tables named as gold
targets; the multi-table gold dbt DAG and the per-target gold plan SHALL remain
distinct artifacts. (`src/tablespec/e2e/compile.py:216`)
ORCH-13. Whole-compile seams that are ill-formed for a given set (e.g. a gold DAG
for a pure-ingest set with no derived gold table) SHALL be omitted fail-closed, not
emitted malformed. (`src/tablespec/e2e/compile.py:127`)
ORCH-14. A UMF snapshot SHALL be persisted per table for audit/reproducibility,
recording exactly the UMF the compile ran against. (`src/tablespec/e2e/compile.py:186`)

#### Manifest & Layout

ORCH-20. Compiled artifacts SHALL be written under a pinned directory layout with
pinned filenames (`umf/`, `ingest/`, `schemas/`, `validation/`, `dbt_ingest/`,
`dbt_gold/`, `ldp/`, `gold_plan/`). (`src/tablespec/e2e/manifest.py:65`)
ORCH-21. A `CompiledArtifacts` manifest enumerating every persisted path SHALL be
serialized to `manifest.json`, storing paths relative to the root so the tree is
relocatable, and re-absolutized on load. (`src/tablespec/e2e/manifest.py:203`, `:245`)
ORCH-22. The manifest SHALL record provenance — `source` (`"tables"`/`"specs"`) and
`profile_enriched` — without that provenance changing the compile.
(`src/tablespec/e2e/manifest.py:155`)

#### Runtime Consumption

ORCH-30. `run_backbone` SHALL accept a `CompiledArtifacts` manifest and raw input
batches and execute the staged runtime (ingest raw→row, validate raw, typed
transform, validate ingested, transforms) by consuming only the committed artifacts.
(`src/tablespec/e2e/backbone.py:545`)
ORCH-31. The backbone SHALL resolve every artifact by path from the manifest and
SHALL NOT re-derive schema/transforms from the UMF or import tablespec generation
seams at run time. (asserted by `tests/e2e/test_bootstrap_from_specs.py:4`)

### Non-Functional Requirements

- **Determinism**: Recompiling the same UMF set SHALL produce 0 byte diffs across
  committed artifacts (drift target: zero; PRD Success Metric "UMF→artifact
  drift"). Evidence: `uv run pytest tests/e2e/test_bootstrap_from_specs.py -k
  compile_persists_every_seam`.
- **Reproducibility**: Every compile SHALL persist the UMF snapshot it ran against
  so an artifact tree is independently reproducible; 100% of per-table manifest
  entries SHALL include a UMF snapshot path.
- **Portability**: The compiled artifact tree SHALL be relocatable (manifest paths
  relative to root) and consumable on DuckDB, classic Spark, and Sail (Connect);
  relocation is verified by `CompiledArtifacts.load()`.
- **Runtime independence**: The backbone SHALL run with no tablespec import at run
  time (PRD Success Metric "Runtime independence"); import-encapsulation tests
  enforce 0 runtime imports of generation seams.
## User Stories

- [US-023 — Bootstrap a runtime from a UMF set (Path A / Path B)](../user-stories/US-023-bootstrap-runtime-from-umf-set.md)
- [US-024 — Runtime consumes only compiled artifacts](../user-stories/US-024-runtime-consumes-only-compiled-artifacts.md)

## Edge Cases and Error Handling

- **Pure-ingest set (no gold target)**: gold DAG and per-target gold plans are
  absent, not malformed; the compile still succeeds. (`compile.py:127`)
- **Schema-only Path A (`profile=False`)**: the compiled suite degrades to
  structural + type checks; this is an explicit, documented contract, not a failure.
- **Spec with no sibling raw batch (Path B)**: compile runs to completion; the
  backbone leg is skipped because there is nothing to ingest. (`bootstrap_from_specs.py:95`)
- **Schema-qualified table name (Path A)**: reflected to a bare-name UMF so the
  compiled raw/ingested tables stay unqualified. (`paths.py:74`)

## Success Metrics

- A single `compile_umfs` call emits 100% of required committed artifact seams plus
  a loadable manifest for a multi-table set, or records each omitted seam as an
  explicit fail-closed omission (asserted: `tests/e2e/test_bootstrap_from_specs.py`).
- A backbone run loads the manifest from disk and reports every stage green while
  consuming only committed artifacts; generation seams are not imported at runtime.
- The bootstrap pipeline is green across the DuckDB / Spark / Sail engine matrix
  (FR-18.5; `tests/e2e/test_e2e_matrix_*.py`).

## Constraints and Assumptions

- The compile is path-agnostic: Path A and Path B differ only in how the `list[UMF]`
  is produced, never in the compile.
- Downstream runtimes execute committed artifacts and do not import tablespec at
  run time (PRD Assumption).
- dbt and pysail are dev/test-only tooling, never a user runtime dependency.

## Dependencies

- **Other features**: FEAT-002 (schema generation seams), FEAT-004 (GX baseline
  suite), FEAT-005 (native profiling for Path A enrichment), FEAT-007 (staged GX
  execution consumed by the backbone). Multi-target emission seams: dbt + LDP +
  raw→ingest (governed under PRD Multi-Target Emission, FR-19.x).
- **External services**: a Spark (classic or Connect) session for Path A reflection
  and for backbone execution; DuckDB / Sail for the test matrix.
- **PRD requirements**: P0 — FR-18.1, FR-18.2, FR-18.3, FR-18.4, FR-18.5.

## Out of Scope

- The individual generator seams themselves (DDL, PySpark, dbt, LDP emit logic) —
  owned by their own features/PRD subsystems; this feature *orchestrates* them.
- A user-facing `tablespec compile` CLI command — the orchestrator is a library
  entry point plus demo scripts; promoting it to the CLI is a separate decision.
- Connect-safe validation routing internals (FR-7.7) — consumed here, specified by
  FEAT-007 / the Runtime Platform subsystem.
- Real-time / watch-mode recompilation — compile is an explicit step (PRD Non-Goal).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements (`FR-18.x`) are listed; single subsystem, no cross-subsystem rationale needed
- [x] Functional areas are subordinate parts of one capability (bootstrap → compile → manifest → consume)
- [x] Overview connects this feature to a specific PRD requirement (FR-18.1/18.3)
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now (CLI `generate` only) and what is broken
- [x] Requirements grouped by functional area
- [x] Domain objects separated (multi-table gold dbt DAG vs per-target gold SQL plan)
- [x] Every functional requirement is testable and cites source `file:line`
- [x] Acceptance criteria live in the decomposing user stories (US-023, US-024)
- [x] Non-functional requirements have specific targets (zero drift)
- [x] Edge cases cover realistic failure scenarios
- [x] Success metrics are specific to this feature
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes plausibly-assumed scope
- [x] No implementation details beyond the WHAT (seams named as the contract surface)
- [x] Consistent with governing PRD requirements
- [x] No unresolved `[NEEDS CLARIFICATION]` markers
