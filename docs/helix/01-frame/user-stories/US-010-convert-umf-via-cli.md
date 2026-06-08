---
ddx:
  id: US-010
---

# US-010: Convert UMF Formats via CLI

**Feature**: FEAT-008 — CLI Interface
**PRD Requirements**: FR-8.1, FR-8.2, FR-8.3, FR-8.4, FR-8.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer managing table specs,
**I want** convert UMF between JSON, split, and Excel formats from the command line,
**So that** I can work with specs in the format best suited to each workflow (git for split, artifact for JSON, review for Excel), while treating legacy single-file YAML as a migration-only input.

## Acceptance Criteria

- [ ] `tablespec convert input.json output/` converts JSON to split-format directory
- [ ] `tablespec convert tables/my_table/ output.json` converts split to JSON
- [ ] `tablespec batch-convert tables/ output/ --format json` batch-converts a directory
- [ ] Format is auto-detected from input path (file vs directory) for split and JSON inputs; legacy single-file YAML requires explicit migration
- [ ] Errors are displayed with Rich formatting and clear messages
