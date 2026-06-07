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

- [ ] `sync_baseline.py` ensures all tables have required metadata columns
- [ ] Baseline validations stay in sync with the baseline generator
- [ ] User customizations (severity changes) are preserved
- [ ] Conflicts (modified rule content) are detected and reported
- [ ] Operation is idempotent
