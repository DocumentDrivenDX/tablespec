---
ddx:
  id: US-028
---

# US-028: Publish Browsable API Documentation

**Feature**: FEAT-015 - Browsable API Documentation
**Feature Requirements**: DOCS-01, DOCS-02
**PRD Requirements**: FR-1.1
**Priority**: P1
**Status**: Implemented

## Story

**As a** platform engineer evaluating tablespec APIs
**I want** browsable API documentation generated from the shipped Python package
**So that** I can discover models, generators, validators, and CLI surfaces without reading source files manually

## Context

The PRD does not define API documentation as a standalone product subsystem, but the docs expose the UMF model and generation surface that downstream teams consume. This story restores structural traceability for the documentation feature.

## Walkthrough

1. User opens the documentation site.
2. System presents API pages for models, generators, type mappings, GX, and CLI surfaces.
3. User navigates from public concepts to Python symbols and examples.

## Acceptance Criteria

- [ ] **US-028-AC1** - Given the docs configuration, when documentation is built, then API pages for models, generators, type mappings, GX, and CLI are present.
- [ ] **US-028-AC2** - Given a public API page, when a user follows module links, then the referenced Python symbols resolve to shipped package modules.

## Edge Cases

- **Missing optional dependencies**: docs for optional Spark/GX surfaces remain import-safe enough for documentation generation.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| API page inventory | US-028-AC1 | mkdocs config | inspect docs/api files | expected API pages exist |
| Symbol resolution | US-028-AC2 | generated docs references | build/import docs target | package modules resolve |

## Dependencies

- **Feature Spec**: FEAT-015
- **PRD Requirements**: FR-1.1

## Out of Scope

- Public marketing site content or versioned documentation hosting.
