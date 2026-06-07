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

- [ ] Sample data engine generates rows matching UMF column types and constraints
- [ ] Foreign key relationships produce referentially consistent data across tables
- [ ] Healthcare domain types (SSN, NPI, state codes) generate realistic values
- [ ] Output available in CSV and JSON formats with configurable row counts
