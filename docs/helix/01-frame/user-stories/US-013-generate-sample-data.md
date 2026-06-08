---
ddx:
  id: US-013
---

# US-013: Generate Sample Data from UMF

**Feature**: FEAT-011 — Sample Data Generation
**PRD Requirements**: FR-12.1, FR-12.2, FR-12.3, FR-12.4, FR-12.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** QA engineer setting up test environments,
**I want** generate realistic sample data from UMF specifications,
**So that** I can test pipelines with data that respects types, constraints, and foreign key relationships.

## Acceptance Criteria

- [ ] **US-013-AC1** - Sample data engine generates rows matching UMF column types and constraints
- [ ] **US-013-AC2** - Foreign key relationships produce referentially consistent data across tables
- [ ] **US-013-AC3** - Healthcare domain types (SSN, NPI, state codes) generate realistic values
- [ ] **US-013-AC4** - Output available in CSV and JSON formats with configurable row counts
