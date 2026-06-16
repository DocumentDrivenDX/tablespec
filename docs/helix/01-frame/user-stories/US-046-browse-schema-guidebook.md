---
ddx:
  id: US-046
---

# US-046: Browse a Schema as a Guidebook

**Feature**: FEAT-033 — Guidebook
**PRD Requirements**: FR-22.1, FR-22.2, FR-22.3, FR-22.4
**Priority**: P1
**Status**: Built

## Story

**As a** data engineer onboarding to an unfamiliar UMF schema,
**I want** to generate a navigable HTML guidebook from a directory of UMFs,
**So that** I can browse tables, columns, and cross-table lineage without reading YAML.

## Context

This story covers the end-to-end guidebook generation slice of FEAT-033. It
exercises discovery, rendering, lineage, and the entry points within the linked
PRD requirements without adding runtime surface beyond the governing feature
spec.

## Walkthrough

1. User points `tablespec guidebook <root> -o <out>` (or calls `generate_guidebook`) at a directory of UMFs.
2. System discovers every UMF, builds the reverse-lineage index, and renders one HTML page per table plus indexes and a search index.
3. User opens `<out>/index.html` and follows links between tables.
4. System's pages cross-link by relative URL: a hub table lists its downstream consumers; a derived column shows upstream sources and SQL.

## Acceptance Criteria

- [ ] **US-046-AC1** — Given a directory of UMFs (split dirs and/or `*.umf.json`), when the guidebook is generated, then one self-contained HTML page is written per table plus a top-level index and a `search_index.json`.
- [ ] **US-046-AC2** — Given a referenced (hub) table, when the guidebook is generated, then its referenced column lists each foreign-key consumer as a downstream link (`via fk`).
- [ ] **US-046-AC3** — Given a derived column with derivation candidates, when the guidebook is generated, then the column page shows its upstream sources and the SQL expression (priority + join filter for multi-candidate columns).
- [ ] **US-046-AC4** — Given a directory containing a malformed UMF, when the guidebook is generated, then the malformed UMF is skipped with a warning and the remaining tables still render.

## Edge Cases

- **flat vs grouped layout**: UMFs in subfolders nest output by group; UMFs all at the root render flat with no per-group index.
- **malformed or duplicate UMF**: skipped with a logged warning, run continues.
- **column-only derivation candidate with a join filter but no expression**: still renders its rule (priority + filter), with no empty SQL block.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Generate pages + index + search | US-046-AC1 | A directory with 2–3 UMFs | run `generate_guidebook` | One HTML page per table, an `index.html`, and a populated `search_index.json` |
| Downstream FK consumer link | US-046-AC2 | A hub table referenced by an FK from another table | run `generate_guidebook` | Hub column shows the consumer as a `via fk` downstream link |
| Upstream derivation + SQL | US-046-AC3 | A derived column with ≥1 candidate (with expression / join filter) | run `generate_guidebook` | Column page shows upstream sources and the formatted SQL expression |
| Malformed UMF skipped | US-046-AC4 | A directory with one malformed `table.yaml` plus valid UMFs | run `generate_guidebook` | Malformed UMF skipped with a warning; valid tables render |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-033 — Guidebook
- **Feature Requirements**: F033-DISC-01, F033-REND-01, F033-LIN-01, F033-LIN-02, F033-ENTRY-01
- **PRD Requirements**: FR-22.1, FR-22.2, FR-22.3, FR-22.4
- **External**: UMF fixtures / docs tooling as implied by the story slice and feature spec.

## Out of Scope

- An interactive lineage graph or git-history feed.
- Generating UMFs from a live catalog (documented two-step flow using existing features).

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story).
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow.
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers.
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID.
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented.
- [x] No exact API/CLI surface is defined inline; normative surface links to the feature spec / implementation.
