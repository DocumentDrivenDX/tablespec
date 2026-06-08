---
ddx:
  id: US-018
---

# US-018: Merge Table Files with Survivorship

**Feature**: FEAT-007 — Table Validation
**PRD Requirements**: FR-15.1, FR-15.2, FR-15.3
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer merging vendor files,
**I want** merge multiple table files using UMF survivorship rules,
**So that** deduplication and conflict resolution follow the spec rather than ad-hoc logic.

## Acceptance Criteria

- [ ] **US-018-AC1** - `merge.py` merges multiple Spark DataFrames using UMF metadata (requires `tablespec[spark]`)
- [ ] **US-018-AC2** - Survivorship rules from UMF drive conflict resolution
- [ ] **US-018-AC3** - Configurable deduplication strategy
