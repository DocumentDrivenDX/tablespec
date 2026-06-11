---
ddx:
  id: US-026
---

# US-026: Emit an LDP Project from a UMF Set

**Feature**: FEAT-028 — LDP Sibling Emitter
**Feature Requirements**: LDP-01, LDP-03, LDP-07, LDP-09, LDP-10, LDP-11, LDP-12
**PRD Requirements**: FR-19.3 (LDP sibling emitter), FR-19.1 (shared target-agnostic core seam)
**Priority**: P1
**Status**: Approved

## Story

**As a** data/data-quality engineer maintaining healthcare table schemas and
transforms across SQL, dbt, and LDP
**I want** to compile one UMF set into a committed Lakeflow Declarative Pipelines
project whose casts and expectations match the dbt/direct artifacts
**So that** my Databricks pipeline is a reviewable diff of the same schema truth
instead of hand-authored streaming/APPLY CHANGES SQL that drifts from the UMF.

## Context

Databricks teams run Lakeflow Declarative Pipelines (the DLT rebrand), where
datasets are declared and the platform owns the DAG, ordering, and
incrementalisation. Before this story, the compiler emitted direct SQL, dbt, and
GX but no LDP artifact, so an LDP pipeline had to be hand-written from the same
UMF — duplicating the cast layer and the expectation semantics. This story
exercises the LDP emitter (`generate_ldp_project`) as a sibling of the dbt emitter
on the shared core seam (FEAT-028 LDP-01/03/07/09/10/11/12), proving the cast body
is the shared `build_ingest_select` output and that references and failure modes
behave correctly.

## Walkthrough

1. Engineer assembles a UMF set (e.g. `claims` incremental+pk, `member` snapshot,
   a gold join) and calls `generate_ldp_project(umfs, file_format="csv")`.
2. System builds the logical-plan IR via the shared `NodeRegistry`, failing loudly
   on a cycle or a dangling non-external reference.
3. System emits one `.sql` file per dataset: `raw/raw_<t>.sql` (streaming
   autoloader), `ingested/ingested_<t>.sql` (APPLY CHANGES / streaming-append /
   materialized view per ingestion mode), and `gold/gold_<t>.sql` (materialized
   view of the shared SQL plan with bare LDP dataset refs).
4. For `ingested_claims`, system emits a streaming-table shell carrying the
   `EXPECT` constraints, then `APPLY CHANGES INTO ingested_claims ... KEYS
   (claim_id) SEQUENCE BY _load_ts`, with the cast SELECT body equal to the dbt
   path's `select_block`.
5. System surfaces uniqueness and FK rules as comments (PK enforced by APPLY
   CHANGES KEYS for the incremental dataset; FK as a relationship-intent comment).
6. Engineer reviews the generated `.sql` files as an ordinary code-review diff.

## Acceptance Criteria

- [ ] **US-026-AC1** — Given a UMF set with a landing table, when `generate_ldp_project` runs, then it returns a `raw/raw_<t>.sql` with `CREATE OR REFRESH STREAMING TABLE raw_<t> ... FROM STREAM read_files(...)` and an `ingested/ingested_<t>.sql`.
- [ ] **US-026-AC2** — Given an incremental table with a primary key and order_by, when the ingested dataset is emitted, then it contains `APPLY CHANGES INTO ingested_<t>` with `KEYS (<primary_key>)` and `SEQUENCE BY <order_by>` (a single column bare, multiple wrapped in `STRUCT(...)`).
- [ ] **US-026-AC3** — Given a non-nullable / primary-key column, when expectations are derived, then the dataset carries `CONSTRAINT not_null_<col> EXPECT (<col> IS NOT NULL) ON VIOLATION FAIL UPDATE`.
- [ ] **US-026-AC4** — Given an `expect_column_values_to_be_in_set` with non-blocking meta and severity `error`, when the constraint is emitted, then its action is `DROP ROW`; with `blocking: true` it is `FAIL UPDATE`; with info/unset it is a `WARN` (no `ON VIOLATION` clause).
- [ ] **US-026-AC5** — Given a table with a primary key and a foreign key, when the dataset is emitted, then uniqueness and FK appear as comments (never as a fabricated `CONSTRAINT`), with the PK comment stating APPLY CHANGES KEYS for an incremental dataset.
- [ ] **US-026-AC6** — Given the ingested dataset's cast SELECT, when compared to the dbt path's `IngestSelect.select_block`, then the two are character-identical (cast layer is shared, not forked).
- [ ] **US-026-AC7** — Given a UMF set with a cycle, a dangling non-external reference, or a name collision, when `generate_ldp_project` runs, then it raises `LdpProjectError`; an unknown relation in a gold plan raises `UnknownDatasetError`.

## Edge Cases

- **Multi-column order_by**: SEQUENCE BY wraps the columns in `STRUCT(...)` to keep lexicographic ordering.
- **Keyless incremental**: Emits a streaming-table append with no KEYS / SEQUENCE BY (duplicates accumulate, mirroring the dbt blind-append branch).
- **Snapshot mode**: Emits a `MATERIALIZED VIEW`; the PK comment states uniqueness is NOT enforced (no row-local UNIQUE in LDP).
- **No emittable facts**: A table with no nullability/enum facts emits no parenthesised constraint clause (not an empty `()`).

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Raw + ingested emitted | US-026-AC1 | UMF set with `claims` landing table | `generate_ldp_project(umfs)` | `raw/raw_claims.sql` (STREAMING TABLE read_files) and `ingested/ingested_claims.sql` present |
| APPLY CHANGES keys | US-026-AC2 | `claims` incremental, pk=`claim_id`, order_by=`_load_ts` | emit ingested | `APPLY CHANGES INTO ingested_claims ... KEYS (claim_id) SEQUENCE BY _load_ts` |
| not_null FAIL UPDATE | US-026-AC3 | `claim_id` is pk / non-nullable | derive expectations | `CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE` |
| accepted_values action | US-026-AC4 | in-set on `status`, meta blocking=false severity=error | derive expectations | `... IN (...)` with `ON VIOLATION DROP ROW` |
| Honest gaps as comments | US-026-AC5 | pk + FK `member_id → ingested_member.member_id`, incremental | emit ingested | `-- uniqueness intent: PRIMARY KEY (claim_id) is enforced by APPLY CHANGES ... KEYS` and a relationship-intent comment; no UNIQUE/FK CONSTRAINT |
| Cast parity | US-026-AC6 | same UMF compiled for dbt and LDP | compare cast bodies | LDP ingested cast lines == dbt `IngestSelect.select_block`; duckdb run yields identical rows |
| Fail closed | US-026-AC7 | gold references an unknown, non-external relation | `generate_ldp_project(umfs)` | raises `LdpProjectError` (dangling) / `UnknownDatasetError` (renderer) |

## Dependencies

- **Stories**: None (parallel sibling of the dbt-emitter story; consumes the shared core seam).
- **Feature Spec**: FEAT-028
- **Feature Requirements**: LDP-01, LDP-03, LDP-07, LDP-09, LDP-10, LDP-11, LDP-12
- **PRD Requirements**: FR-19.3, FR-19.1
- **External**: Databricks / Lakeflow runtime (consumes the artifact; not needed to generate or test structure/cast parity).

## Out of Scope

- Deploying or running the LDP pipeline on a Databricks workspace (the Databricks-execute conformance tier is out of CI scope).
- Row-local enforcement of uniqueness or referential integrity (LDP cannot express these; surfaced as comments).
- Any change to the dbt emitter, the direct-SQL path, or `tablespec.core` semantics.

## Review Checklist

- [x] Stored as its own file `US-026-emit-ldp-project-from-umf.md`
- [x] Covers one persona completing one goal, demonstrable end-to-end
- [x] Links to FEAT-028 and names PRD FR-19.3 / FR-19.1
- [x] Every acceptance criterion is independently testable with a stable `US-026-ACm` ID
- [x] Walkthrough traces trigger → outcome; edge cases documented
