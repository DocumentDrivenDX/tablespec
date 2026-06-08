---
ddx:
  id: US-017
---

# US-017: Infer Domain Types for Columns

**Feature**: FEAT-013 — Domain Type Inference
**PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer building table specs,
**I want** automatically detect domain types (state code, SSN, phone) from column names and descriptions,
**So that** I can enrich UMF specs with semantic types without manual tagging.

## Acceptance Criteria

- [ ] **US-017-AC1** - `DomainTypeInference` infers domain types from column name patterns
- [ ] **US-017-AC2** - `DomainTypeRegistry` loads domain definitions from YAML
- [ ] **US-017-AC3** - Inferred types integrate with sample data generation and validation
- [ ] **US-017-AC4** - Unknown columns return no domain type rather than a false match
