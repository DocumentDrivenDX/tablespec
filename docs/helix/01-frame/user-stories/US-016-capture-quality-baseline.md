---
ddx:
  id: US-016
---

# US-016: Capture and Compare Quality Baselines

**Feature**: FEAT-012 — Quality Baselines
**PRD Requirements**: FR-13.1, FR-13.2, FR-13.3, FR-13.4
**Priority**: P1
**Status**: Implemented

## Story

**As a** data quality engineer monitoring pipeline health,
**I want** capture a quality baseline from a DataFrame and compare it to previous runs,
**So that** I can detect data drift in row counts, distributions, and statistics.

## Acceptance Criteria

- [ ] **US-016-AC1** - `BaselineService.capture()` records row counts, column distributions, and numeric stats (requires `tablespec[spark]`)
- [ ] **US-016-AC2** - `BaselineService.compare()` produces drift metrics between two baselines
- [ ] **US-016-AC3** - Distribution drift uses Jensen-Shannon divergence
- [ ] **US-016-AC4** - Baselines are stored and retrievable via `BaselineWriter`
