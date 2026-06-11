---
ddx:
  id: FEAT-028
---

# Feature Specification: FEAT-028 — LDP Sibling Emitter

**Feature ID**: FEAT-028
**Status**: Approved
**Priority**: P1
**Owner**: Platform / Compilation
**Covered PRD Subsystem(s)**: Multi-Target Emission
**Covered PRD Requirements**: FR-19.3 (LDP sibling emitter), FR-19.1 (shared target-agnostic core seam)
**Cross-Subsystem Rationale**: None — single subsystem (Multi-Target Emission). FR-19.1 (the shared core seam) is the contract this emitter is built on, not a second capability; it is co-owned with FEAT-027 (dbt emitter) and governed at the seam by ADR-013.

## Overview

This feature implements PRD FR-19.3: emit a Lakeflow Declarative Pipelines (LDP)
project from one UMF set as a committed runtime artifact, built as a sibling of
the dbt emitter on the shared target-agnostic core (FR-19.1). It proves the core
seam (`tablespec.core` logical-plan IR / `NodeRegistry`, `build_ingest_select` /
`cast_column_sql`, the `TableRenderer` Protocol) is genuinely target-agnostic by
emitting a second, structurally different backend from the same inputs the dbt
emitter consumes (`src/tablespec/ldp/project.py:1`).

## Ideal Future State

A data engineer who edits a table's UMF and runs the compile step gets, among the
other committed artifacts, a reviewable LDP project: one `.sql` file per dataset
(`raw/raw_<t>.sql`, `ingested/ingested_<t>.sql`, `gold/gold_<t>.sql`,
`src/tablespec/ldp/project.py:234`). Each dataset declares the correct LDP
materialization (streaming table, APPLY CHANGES, or materialized view) for the
table's ingestion mode, carries inline `EXPECT` constraints derived from UMF
nullability and domain enums, and references upstream datasets by the same plan
the dbt path renders. The casts in every dataset body are character-identical to
the dbt and direct-SQL paths, so the engineer can trust that switching target
backends does not silently change the transform. Rules LDP cannot express as a
single-dataset constraint (uniqueness, foreign keys) appear as honest comments,
never as faked constraints.

## Problem Statement

- **Current situation**: The compile step emits direct SQL, dbt projects, and GX
  suites. Databricks teams that run Lakeflow Declarative Pipelines (the DLT
  rebrand) had no committed LDP artifact and would hand-author streaming-table /
  APPLY CHANGES / materialized-view declarations from the same schema truth.
- **Pain points**: A hand-authored LDP pipeline drifts from the UMF and from the
  dbt/direct transforms; the cast logic and expectation semantics get
  re-implemented per backend and diverge. There was also no executable proof that
  the "target-agnostic core" claim holds for a backend whose execution model
  (declared datasets, platform-owned DAG) is fundamentally different from dbt's
  ordered run.
- **Desired outcome**: One UMF compiles deterministically to an LDP project whose
  cast layer is provably the shared cast (cross-engine duckdb parity), with the
  emitter importing no Databricks/Spark runtime and no other backend.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Dataset materialization | "What LDP object should each table become?" | Map ingestion mode + primary key to streaming table / APPLY CHANGES / materialized view |
| Inline expectations | "How are UMF validation rules enforced in LDP?" | Derive `EXPECT (...) ON VIOLATION ...` from UMF nullability, primary key, and accepted_values, with action from blocking/severity meta |
| Cross-dataset references | "How do gold datasets reference upstream tables?" | Render the shared `SQLPlanGenerator` plan with an `LdpRefRenderer` emitting bare LDP dataset names |
| Honest gaps | "What can't LDP enforce per-row?" | Surface uniqueness and FK intent as comments, never as fabricated constraints |

## Requirements

### Functional Requirements by Area

#### Dataset materialization

LDP-01. The emitter MUST produce one `.sql` file per dataset under a pinned
layout: `raw/raw_<t>.sql` and `ingested/ingested_<t>.sql` for every landing
table, and `gold/gold_<t>.sql` for every table with cross-table derivations
(`src/tablespec/ldp/project.py:276`).
LDP-02. A raw landing table MUST be emitted as `CREATE OR REFRESH STREAMING TABLE
raw_<t> ... FROM STREAM read_files(<landing_path>, format => ...)` (continuous
file ingestion) (`src/tablespec/ldp/project.py:60`).
LDP-03. An incremental ingested dataset WITH a primary key MUST be emitted as a
streaming-table shell carrying the EXPECTATIONS plus `APPLY CHANGES INTO
ingested_<t> ... KEYS (<pk>) SEQUENCE BY <order_by>`, where KEYS equals the UMF
primary key and SEQUENCE BY equals the dedup order_by (a single column bare,
multiple wrapped in `STRUCT(...)`) (`src/tablespec/ldp/project.py:123`).
LDP-04. An incremental ingested dataset WITHOUT a primary key MUST be emitted as a
streaming table that appends the cast SELECT over the raw stream (no KEYS, no
dedup) (`src/tablespec/ldp/project.py:153`).
LDP-05. A snapshot ingested dataset MUST be emitted as a `CREATE OR REFRESH
MATERIALIZED VIEW` full reload (`src/tablespec/ldp/project.py:163`).
LDP-06. A gold dataset MUST be emitted as a materialized view whose body is the
SAME `SQLPlanGenerator` plan the dbt path renders, with references rendered as
bare LDP dataset names (`src/tablespec/ldp/project.py:176`).

#### Inline expectations

LDP-07. Non-nullable columns and primary-key columns MUST emit `CONSTRAINT
not_null_<col> EXPECT (<col> IS NOT NULL) ON VIOLATION FAIL UPDATE`
(`src/tablespec/ldp/expectations.py:160`).
LDP-08. An `expect_column_values_to_be_in_set` expectation MUST emit `CONSTRAINT
accepted_values_<col> EXPECT (<col> IS NULL OR <col> IN (...))`, NULLs passing
(`src/tablespec/ldp/expectations.py:178`).
LDP-09. The `ON VIOLATION` action MUST be derived from expectation meta:
`blocking: true` → FAIL UPDATE; non-blocking with severity in
{critical, error, warning} → DROP ROW; non-blocking info/unset → WARN (no `ON
VIOLATION` clause). `blocking` is authoritative for aborting; a high severity
never overrides a non-blocking check into FAIL UPDATE
(`src/tablespec/ldp/expectations.py:87`).

#### Honest gaps

LDP-10. Uniqueness (primary key / unique_constraints) and foreign-key
relationships MUST be emitted as comments stating intent and where enforcement
actually comes from, never as fabricated single-dataset constraints. The PK
comment MUST reflect the materialization (incremental → enforced by APPLY CHANGES
KEYS; snapshot → not enforced) (`src/tablespec/ldp/expectations.py:229`).

#### Shared core seam

LDP-11. The cast SELECT body of every ingested dataset MUST be the shared
`build_ingest_select` / `cast_column_sql` output, character-identical to the dbt
path's `IngestSelect.select_block` (`src/tablespec/ldp/project.py:284`).
LDP-12. The emitter MUST fail closed: a cycle, a dangling non-external reference,
or a physical-name collision in the UMF set MUST raise `LdpProjectError`; an
unknown relation in a gold plan MUST raise `UnknownDatasetError`
(`src/tablespec/ldp/project.py:255`, `src/tablespec/ldp/renderer.py:80`).

### Non-Functional Requirements

- **Encapsulation**: Generating an LDP project MUST import 0 Databricks or Spark
  runtime packages; `tablespec.core` MUST NOT import `tablespec.ldp`, and
  `tablespec.ldp` and `tablespec.dbt` MUST NOT import each other (enforced by
  `tests/test_core_encapsulation.py`).
- **Determinism**: Re-compiling the same UMF set MUST produce 0 byte diffs in LDP
  SQL (verified by structure goldens, `tests/golden/ldp/`).
- **Cast parity**: The LDP ingested cast SELECT MUST produce the same canonical
  rows as the dbt/direct path on real duckdb for every LDP conformance case that
  has an executable local tier (`tests/conformance/test_ldp_tiers.py`).
## User Stories

- [US-026 — Emit an LDP Project from a UMF Set](../user-stories/US-026-emit-ldp-project-from-umf.md)

## Edge Cases and Error Handling

- **Multi-column dedup order**: When `order_by` has more than one column, SEQUENCE
  BY wraps them in `STRUCT(...)` to preserve lexicographic ordering.
- **Cross-pipeline foreign key**: A reference marked external resolves to its
  registered external dataset name; an unmarked unknown relation fails closed.
- **No emittable constraints**: A table with no nullability/enum facts emits a
  dataset with no parenthesised constraint clause (not an empty `()`).

## Success Metrics

- LDP project emitted for 100% of tables in a compiled UMF set, or an explicit
  fail-closed omission is recorded for unsupported set shapes (no manual LDP
  authoring needed for the covered patterns).
- Zero cast divergence: LDP ingested cast body equals the dbt path's
  `select_block` on every conformance case. Evidence: `uv run pytest
  tests/ldp tests/conformance/test_ldp_tiers.py`.

## Constraints and Assumptions

- LDP runs ONLY on Databricks; structure and cast parity are tested locally
  (JVM-free), real end-to-end pipeline execution is a Databricks-only tier and is
  not exercised in CI (scope-local; see ADR-013).
- The emitter is text-generation only; it deploys nothing.

## Dependencies

- **Other features**: FEAT-027 (dbt emitter — the parallel sibling sharing the
  core seam); FEAT-026 (compile orchestration & bootstrap — drives this emitter
  as one compile seam).
- **Architecture**: ADR-013 (target-agnostic core seam / sibling emitters) governs
  the seam this feature plugs into; ADR-007 (raw→ingest SQL artifact) and ADR-008
  (dbt adoption) establish the core.
- **External services**: Databricks / Lakeflow runtime (consumes the emitted
  artifact; not required to generate it).
- **PRD requirements**: FR-19.3 (P1), FR-19.1 (P1).

## Out of Scope

- Executing or deploying the LDP pipeline to a Databricks workspace (text
  generation only; the Databricks-execute tier is out of CI scope).
- An open-source / local LDP runner or linter (none exists; no local develop loop).
- Row-local enforcement of uniqueness or referential integrity (LDP has no
  row-scoped UNIQUE / FK `EXPECT`; surfaced as comments).
- Changing `tablespec.dbt`, `tablespec.core` semantics, or the direct-SQL path.

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements listed; single subsystem, no mega-FEAT
- [x] Overview connects this feature to FR-19.3
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is broken
- [x] Functional areas are subordinate parts of one capability
- [x] Requirements are grouped by area and each is testable
- [x] Non-functional requirements have specific targets
- [x] Acceptance criteria live in US-026, not here
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes plausible scope questions
- [x] No implementation-library prescriptions beyond the shipped seam being governed
