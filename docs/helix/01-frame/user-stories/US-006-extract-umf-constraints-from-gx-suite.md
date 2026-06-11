---
ddx:
  id: US-006
---

# US-006: Extract UMF Constraints from an Existing GX Suite

**Feature**: FEAT-004 — Great Expectations Integration
**PRD Requirements**: FR-4.4, FR-4.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data quality engineer with existing Great Expectations suites,
**I want** extract validation constraints from those suites back into UMF format,
**So that** I can consolidate tribal knowledge already captured in GX into the canonical UMF schema and avoid maintaining rules in two places.

## Acceptance Criteria

- [ ] `GXConstraintExtractor` parses an existing GX suite and extracts value sets, regex patterns, strftime format strings, and metadata hints into UMF `ValidationRules`
- [ ] Extracted constraints can be merged into an existing UMF schema
- [ ] Sample values are generated from extracted regex patterns for documentation purposes
- [ ] `GXSchemaValidator` validates expectation types against the GX library and produces corrected schemas containing only valid types
