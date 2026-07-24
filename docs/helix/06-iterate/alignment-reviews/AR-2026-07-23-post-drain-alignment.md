---
ddx:
  id: AR-2026-07-23-post-drain
  links:
    - AR-2026-07-22-desired-state-realignment
---

# Alignment Review: Post-Drain Spec ↔ Code (Agent-Executable Focus)

**Review Date**: 2026-07-23  
**Scope**: full repo HELIX stack vs `main` after PRs #12/#13; PR #14 in-flight  
**Status**: complete  
**Primary Governing Artifact**: `docs/helix/00-discover/product-vision.md`

## Principle

- Specs describe **desired future state**; incomplete code is residual, not a
  reason to shrink FR/FEAT language.
- Specs **behind** shipped code are `STALE_PLAN` and get plan-to-code updates.
- Follow-up work filed only when **agent-executable** in this repo without a
  live Databricks workspace or human-only ops.

## Scope and Governing Artifacts

### Scope

- Structural floor: FR→FEAT coverage, AC `@covers` citations, ADR inventory
- Delivery honesty: FEAT-031/032/034, US-038–050, app/demo residuals
- Tracker state after alignment drain (#12/#13) and open PR #14
- Distinction: workspace-only residual vs agent-fixable gaps

### Governing Artifacts

- `docs/helix/00-discover/product-vision.md`
- `docs/helix/01-frame/prd.md`, `principles.md`, `concerns.md`, `feature-registry.md`
- `docs/helix/01-frame/features/FEAT-001`…`FEAT-034`
- `docs/helix/01-frame/user-stories/US-001`…`US-050`
- `docs/helix/02-design/architecture.md`, ADR-001…019
- `docs/helix/03-test/test-plan.md`, `conformance-acceptance.md`
- `docs/helix/04-build/implementation-plan.md`
- `docs/helix/05-deploy/deployment-checklist.md`
- `src/tablespec/`, `apps/data-profiling/`, `website/`, `notebooks/`
- Prior AR: `AR-2026-07-22-desired-state-realignment.md`

## Intent Summary

- **Vision**: UMF compiler + Connect-safe multi-engine runtime; optional
  Databricks App and guidebook as first-party companions.
- **Post-drain reality**: Beads queue is **empty** (0 open / 0 ready after #13).
  Remaining product residual is mostly **operational** (workspace deploy/demo
  job) or **citation hygiene** on already-shipped surfaces.
- **PR #14** (green CI, unmerged at review time) carries plan-to-code honesty
  for FEAT-034 Built, US-044 Built, and `@covers` for US-040/042–050 and
  US-047–049.

## Structural Floor (`helix_align_check`)

Run against **current `main`** (pre-#14 merge):

| Dimension | Floor | Notes |
|-----------|-------|-------|
| FR → FEAT | **clean** | 23/23 FRs covered by a FEAT |
| Decomposition | **clean** | 23 subsystems / 34 FEATs / 49 stories |
| ADRs | **clean** | 19 ADRs; 18 accepted, 1 proposed |
| AC `@covers` | **advisory** | **152/206** ACs cited; **54** `NO_CITATION`; 0 dangling |

### Uncited ACs on `main` (54)

| Band | ACs | Agent-executable fix? |
|------|-----|------------------------|
| US-037 | AC1–AC5 | **Yes** — add `@covers` on Connect/capability tests |
| US-038 | AC1–AC5 | **Yes** — add `@covers` on Playwright + pages tests |
| US-040, 042–044, 047–050 | bulk | **Yes — already on PR #14** |
| US-045 | AC1–AC6 | **Yes for citations** (notebook `@covers` on #14); live job remains operational residual |

After #14 merges, expected uncited residual: **US-037 + US-038 only** (plus any
new ACs).

## Gap Register

| Area | Classification | Planning Evidence | Implementation Evidence | Resolution Direction |
|------|----------------|-------------------|-------------------------|----------------------|
| PR #14 unmerged | INCOMPLETE | FEAT-034 Built, US-044 Built, covers on branch | CI green on #14 | **plan-to-code land**: merge #14 |
| FEAT-034 registry **Specified** on `main` | STALE_PLAN | feature-registry.md FEAT-034 row | config/provision/diagnostics/stack shipped | Fixed on #14 → Built |
| US-044 status **Draft** on `main` | STALE_PLAN | US-044 status line | `notebooks/kaggle-demo/` complete pair | Fixed on #14 → Built |
| US-040/042/043/047–050 uncited on `main` | UNCITED_COVERAGE | stories + tests exist | tests lack `@covers` on main | Fixed on #14 |
| US-037 uncited | UNCITED_COVERAGE | US-037 ACs | `test_safe_timestamp`, Connect sail tests | Add `@covers` (agent) |
| US-038 uncited | UNCITED_COVERAGE | US-038 ACs; closed as shipped earlier | `website/e2e/microsite.spec.ts`, pages tests | Add `@covers` (agent) |
| Live app deploy-and-drive | INCOMPLETE (ops) | FR-23 / FEAT-034 phase residual | Unit path only | **No bead** — requires workspace/operator |
| US-045 workspace job | INCOMPLETE (ops) | US-045 limitations | notebooks + type core shipped | **No bead** — operational residual |
| concerns conflict text on `main` | STALE_PLAN | concerns.md “no whole-stack exercise” | `test_fr23_stack.py` exists; #14 rewrites conflict | Land #14 |
| `make lint` excludes `apps/` | QUALITY | CLAUDE.md / AGENTS.md | `ruff check apps/` not clean | Optional agent chore (not product gap) |
| AR-2026-07-22 residual language | STALE_PLAN | prior AR lists DUMP/JSON open | DUMP/JSON/story floor closed #12–#13 | This AR supersedes residual table |

### Quality Findings

| Area | Dimension | Concern | Severity | Resolution |
|------|-----------|---------|----------|------------|
| App e2e slot | verification | Live deploy still not CI | low | Accept as operational residual; unit composition is the agent gate |
| Citation vs exercise | verification | Bulk `@covers` may over-claim exercise | medium | Prefer story-local primary tests; sample-audit in future align |
| Demo notebooks | verification | Workspace PASS not in CI | low | Documented residual; no agent bead |

## Traceability Matrix (high level)

| Requirement family | Feature | Stories | Code status | Classification |
|--------------------|---------|---------|-------------|----------------|
| FR-1.x UMF core | FEAT-001–023 | US-001–036 | Built | ALIGNED |
| FR-18/19 compile/emit | FEAT-026–028 | US-023–026 | Built | ALIGNED |
| FR-21 multi-source | FEAT-031 | US-039–044, 050 | Cores shipped; US-044 notebooks Built (#14); US-045 residual | ALIGNED after #14 / residual ops |
| FR-1.11 EMBEDDING | FEAT-032 | US-045 | Type+CORP shipped; demo residual ops | ALIGNED (ops residual) |
| FR-22 guidebook | FEAT-033 | US-046 | Built + `@covers` | ALIGNED |
| FR-23 app deploy | FEAT-034 | US-047–049 | Code shipped; honesty on #14 | ALIGNED after #14 |
| FR-30 microsite | FEAT-030 | US-038 | Built; `@covers` missing on main | UNCITED_COVERAGE |

## Execution Issues (agent-executable only)

| ID | Goal | Verification |
|----|------|--------------|
| *(file after this AR)* | Merge or land PR #14 (operator or agent with merge rights) | CI already green |
| *(file after this AR)* | `@covers` US-037-AC1..5 on capability/session tests | `helix_align_check` drops US-037 NO_CITATION |
| *(file after this AR)* | `@covers` US-038-AC1..5 on Playwright/pages tests | same for US-038 |

**Explicitly not filed** (human/workspace-only):

- Live Databricks Apps deploy-and-drive recording
- Foundation Model API embedding widget on US-045 job
- Any “run notebook on my cluster” evidence capture

## Execution Order

1. Land **PR #14** (closes most STALE_PLAN + bulk UNCITED_COVERAGE).
2. Add **US-037 / US-038 `@covers`** (remaining citation floor on main).
3. Optionally: next product feature frame (no open build residual in tracker).

**Critical path**: #14 land → US-037/038 covers.  
**Blockers**: none for agent citation work; workspace residual is non-blocking for queue drain.

## Open Decisions

| Decision | Why Open | Recommendation |
|----------|----------|----------------|
| Treat live app deploy as forever-ops residual? | No CI secrets/workspace in default gates | **Yes** — keep documented residual, no open bead |
| Expand `make lint` to `apps/`? | Quality hygiene, not FR gap | Optional chore bead if desired |

## Tracker Snapshot at Review

```
Total: 117 (or +4 if #14 beads not yet on main)
Open: 0 | Ready: 0 | Blocked: 0 | Proposed: 0
```

Beads queue remains empty of product build work; alignment follow-ups are
citation/hygiene only.
