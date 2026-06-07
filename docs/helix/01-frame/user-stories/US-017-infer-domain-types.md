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

- [ ] `DomainTypeInference` infers domain types from column name patterns
- [ ] `DomainTypeRegistry` loads domain definitions from YAML
- [ ] Inferred types integrate with sample data generation and validation
- [ ] Unknown columns return no domain type rather than a false match
