---
ddx:
  id: US-012
---

# US-012: Load UMF from Split-Format Directory

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer using git for schema version control,
**I want** store UMF specs as a directory of YAML files (one per column) and load them transparently,
**So that** git diffs show per-column changes and merge conflicts are isolated, while legacy single-file YAML stays outside the canonical path.

## Acceptance Criteria

- [ ] **US-012-AC1** - `UMFLoader` auto-detects split format from a directory containing `table.yaml` + `columns/`
- [ ] **US-012-AC2** - `UMFLoader` auto-detects JSON format from a `.json` file
- [ ] **US-012-AC3** - Loading from either format produces the same `UMF` object
- [ ] **US-012-AC4** - `UMFLoader` converts between formats bidirectionally
- [ ] **US-012-AC5** - Single-file YAML UMF documents require an explicit legacy migration path and are not auto-detected as canonical input
