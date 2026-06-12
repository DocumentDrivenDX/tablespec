---
ddx:
  id: US-028
---

# US-028: Publish Browsable API Documentation

**Feature**: FEAT-015 - Browsable API Documentation
**PRD Requirements**: FR-1.1
**Priority**: P1
**Status**: Approved

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

## Context

This story covers the publish browsable api documentation slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a publish browsable api documentation fixture or source object.
2. System runs the the docs build runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-028-AC1** — Given docs for `models`, `generators`, `type-mappings`, `GX`, and `CLI`, when the docs build runs, then **US-028-AC1** - Given the docs configuration, when documentation is built, then API pages for models, generators, type mappings, GX, and CLI are present.
- [ ] **US-028-AC2** — Given docs for `models`, `generators`, `type-mappings`, `GX`, and `CLI`, when the docs build runs, then **US-028-AC2** - Given a public API page, when a user follows module links, then the referenced Python symbols resolve to shipped package modules.

## Edge Cases

- **module links must resolve to shipped packages**: module links must resolve to shipped packages
- **API docs should cover the public surfaces only**: API docs should cover the public surfaces only
- **docs generation should stay buildable**: docs generation should stay buildable

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Build docs for public APIs | US-028-AC1 | docs for models, generators, type-mappings, GX, CLI | the docs build runs | **US-028-AC1** - Given the docs configuration, when documentation is built, then API pages for models, generators, type mappings, GX, and CLI are present. |
| Resolve module links | US-028-AC2 | models/index.html module links to tablespec.models.umf | the docs build runs | **US-028-AC2** - Given a public API page, when a user follows module links, then the referenced Python symbols resolve to shipped package modules. |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-015 - Browsable API Documentation
- **Feature Requirements**: DOCS-01, DOCS-02
- **PRD Requirements**: FR-1.1
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- public API behavior changes
- non-doc generation tooling

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
