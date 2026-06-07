---
ddx:
  id: US-002
---

# US-002: Construct a UMF Schema Programmatically

**Feature**: FEAT-001 — UMF Models and I/O
**PRD Requirements**: FR-1.1, FR-1.2, FR-1.3, FR-1.5, FR-1.6, FR-1.10
**Priority**: P1
**Status**: Implemented

## Story

**As a** platform engineer managing schema standards,
**I want** construct UMF schemas programmatically using type-safe Python models,
**So that** I can generate and manage table specifications across Medicaid, Medicare Part D, and Medicare lines of business in automated workflows without hand-editing YAML.

## Acceptance Criteria

- [ ] UMF, UMFColumn, Nullable, ValidationRules, Relationships, and UMFMetadata models can be instantiated with keyword arguments and compose into a complete schema
- [ ] Pydantic validation fires on construction, catching invalid column names, unsupported data types, and missing required fields immediately
- [ ] ForeignKey confidence scoring and legacy format support work when building relationships programmatically
- [ ] The constructed UMF object can be serialized to YAML via `save_umf_to_yaml` for storage or distribution
