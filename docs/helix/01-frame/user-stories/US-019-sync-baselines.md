---
ddx:
  id: US-019
---

# US-019: Sync Baseline Validations Across Tables

**Feature**: FEAT-012 — Quality Baselines
**PRD Requirements**: FR-13.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** platform engineer maintaining table standards,
**I want** sync metadata columns and baseline validations across all table definitions,
**So that** every table has required metadata columns and up-to-date programmatic validations.

## Acceptance Criteria

- [ ] **US-019-AC1** - `sync_baseline.py` ensures all tables have required metadata columns
- [ ] **US-019-AC2** - Baseline validations stay in sync with the baseline generator
- [ ] **US-019-AC3** - User customizations (severity changes) are preserved
- [ ] **US-019-AC4** - Conflicts (modified rule content) are detected and reported
- [ ] **US-019-AC5** - Operation is idempotent
