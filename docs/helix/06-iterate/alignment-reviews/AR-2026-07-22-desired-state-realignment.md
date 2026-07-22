# Alignment Review: Desired-State Realignment (Specs Ahead of Code)

**Review Date**: 2026-07-22
**Scope**: repo (HELIX stack + post-June features + app/guidebook wave)
**Status**: complete (plan-to-code doc updates applied; residual gaps filed as beads)
**Primary Governing Artifact**: `docs/helix/00-discover/product-vision.md`

## Principle

- **Specs describe the desired future state.** Do not shrink FR/FEAT/US to match incomplete code.
- **Specs behind implementation** receive plan-to-code catch-up edits in this review.
- **Code behind specs** is tracked only in the DDx beads queue (alignment epic).

## Scope and Governing Artifacts

### Scope

- Full HELIX planning stack vs shipped library/app/docs surfaces.
- Authority contradiction: PRD Non-Goals vs FR-23 / FEAT-034 / concerns.
- Honesty gaps: FEAT-032 “nothing implemented”, FEAT-031 phase banner, FEAT-030 delivery status.
- Downstream lag: architecture, test plan, deployment checklist relative to FR-22/23.

### Governing Artifacts

- `docs/helix/00-discover/product-vision.md`
- `docs/helix/01-frame/prd.md`, `principles.md`, `concerns.md`, `feature-registry.md`
- `docs/helix/01-frame/features/FEAT-030`…`FEAT-034` (and core FEAT-001–029)
- `docs/helix/01-frame/user-stories/US-038`…`US-049`
- `docs/helix/02-design/architecture.md`, ADR-015…019
- `docs/helix/03-test/test-plan.md`
- `docs/helix/04-build/implementation-plan.md`
- `docs/helix/05-deploy/deployment-checklist.md`
- `src/tablespec/` (models, type_mappings, guidebook, ingestion, e2e, …)
- `apps/data-profiling/`, `website/`

## Intent Summary

- Vision/PRD: UMF compiler + Connect-safe multi-engine runtime remains core; optional Databricks App and guidebook are first-party companion surfaces.
- Specs catch up where code already ships EMBEDDING, multi-kind `source:` models/readers, guidebook, and microsite.
- Specs keep FR-23, dump-dialect completeness, parquet cast residual, CORP/DEMO, and app e2e as **desired** requirements with bead coverage.

## Gap Register

| Area | Classification | Planning Evidence | Implementation Evidence | Resolution |
|------|----------------|-------------------|-------------------------|------------|
| PRD Non-Goal “no Application GUI” vs FR-23 | DIVERGENT → fixed | prd.md Non-Goals vs FR-23/FEAT-034 | `apps/data-profiling/` in repo | PRD Non-Goals rewritten (scoped exclusion) |
| FEAT-032 “nothing implemented” | STALE_PLAN → fixed | FEAT-032 Draft banner | EMBEDDING in models/mappings/tests | Status Approved; type core shipped; CORP/DEMO residual |
| FEAT-031 “JDBC/dump/parquet planned” blanket | STALE_PLAN → fixed | FEAT-031/PRD FR-21 intro | models + ingestion readers for 4 kinds | Phase table; residual DUMP/PARQ/JSON/US stories |
| FEAT-030 registry Specified | STALE_PLAN → fixed | feature-registry | `website/`, Playwright, Pages workflows | Registry Built |
| Architecture/TP/deploy lag FR-22/23 | STALE_PLAN → fixed | architecture 2026-06-06; TP; deploy checklist | guidebook package; app tree; microsite | Docs updated to desired topology |
| Registry “every Approved is Built” | DIVERGENT → fixed | feature-registry prose | FEAT-031/034 not Built | Dual-enum prose corrected |
| US-040…043 missing | INCOMPLETE | FEAT-031 User Stories section | Stories not on disk | Beads to author stories |
| FR-23 app portability | INCOMPLETE | FEAT-034, US-047–049, ADR-019 | POC `connections.yaml` catalogs | Beads for config/provision/e2e |
| Dump-dialect / parquet cast residual | INCOMPLETE | FR-21.2/21.3, FEAT-031 | Partial readers | Beads after US-042/043 |
| CORP pattern + US-045 residual | INCOMPLETE | FEAT-032 CORP/DEMO | Type core only | Beads for pattern + demo ACs |
| App whole-stack e2e | UNDERSPECIFIED/INCOMPLETE | concerns e2e-framework slot | No app e2e harness | Bead for e2e gate |

## Spec Updates Applied (this PR)

1. PRD v3.1: Summary, Non-Goals, FR-1.2/1.11, FR-21 honesty, FR-23 note
2. Product vision: companion app + guidebook UX
3. FEAT-031 phase table + kinds include `json`
4. FEAT-032 Approved + honest phase table
5. FEAT-033 already Approved (registry Built)
6. Feature registry statuses + dual-enum prose
7. Architecture v3.1: app, guidebook, ingestion, microsite, ADR-018/019
8. Test plan v3.1: FR-21/22/23 levels and ACs
9. Deployment checklist v2.1: `app_deploy` section
10. Implementation plan v3.1: slices 6–8 + app note
11. Concerns: e2e-framework points at alignment tracking

## Execution Issues Generated

**Epic**: `tablespec-263a0248` — HELIX desired-state alignment — implementation gaps

### B1 App deployability (FR-23 / FEAT-034)

| Bead | Title |
|------|-------|
| `tablespec-2a68a0ad` | App: single config precedence resolver (FR-23.1 / CFG-01) |
| `tablespec-859aa1ea` | App: strip environment-identifying literals (FR-23.1 / CFG-02) |
| `tablespec-48f4fce6` | App: idempotent metadata home provision step (FR-23.3 / US-048) |
| `tablespec-5173ff2e` | App: parameterized deployment manifest inputs (FR-23.4) |
| `tablespec-0e6cd069` | App: startup fail-fast configuration validation (FR-23.6 / US-049) |
| `tablespec-112c6f19` | App: optional integrations degrade cleanly (FR-23.5) |
| `tablespec-6bd3e4f7` | App: whole-stack e2e gate for FR-23 (e2e-framework slot) |

### B2 Multi-source residual (FEAT-031)

| Bead | Title |
|------|-------|
| `tablespec-20513f4f` | Author US-040: source model + ingestion seam (backfill ACs) |
| `tablespec-1af0828a` | Author US-041: JDBC reader + discovery slices |
| `tablespec-e322b612` | Author US-042: dump-dialect text landing |
| `tablespec-e9c21567` | Author US-043: typed-raw parquet cast mode residual |
| `tablespec-557f8a24` | Author US-050: JSON/JSONL source kind residual (FR-21.7) |
| `tablespec-7ec86390` | Implement dump-dialect end-to-end (DUMP-01..04) |
| `tablespec-502c6126` | Implement parquet identity/safe-narrowing residual (PARQ) |
| `tablespec-9f98cf03` | Implement JSON source residual compile/backbone path |
| `tablespec-0aa41072` | Northwind Databricks acceptance residual (US-039) |

### B3 Embeddings residual (FEAT-032)

| Bead | Title |
|------|-------|
| `tablespec-a3458685` | Ship document-corpus pattern example for FEAT-032 |
| `tablespec-abd68023` | Close US-045 SEC 10-K demo residual ACs |

### B4 / B5 Polish

| Bead | Title |
|------|-------|
| `tablespec-9c79765e` | Link US-046 guidebook ACs to tests |
| `tablespec-e1956759` | Close residual US-038 microsite ACs if any open |
| `tablespec-a4d6dc58` | Feature registry Trace Links: fill high-traffic rows or document partial matrix |

## Definition of Aligned (post-PR)

| Check | Pass |
|-------|------|
| No higher-authority contradiction | PRD Non-Goals consistent with FR-23 |
| No false “unimplemented” claims for shipped type/source cores | FEAT-032/031 banners honest |
| Desired future still ambitious | FR-23, DUMP, residuals remain requirements |
| Gaps queued | Alignment epic + child beads |
| Downstream docs govern app/guidebook | Architecture, TP, deploy |
| Machine gates | `tests/docs/` green |

## Open Decisions

None blocking. Tool selection for app e2e remains an assumption until the e2e bead lands a choice.
