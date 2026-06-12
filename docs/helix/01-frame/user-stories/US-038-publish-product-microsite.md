---
ddx:
  id: US-038
---

# US-038: Publish Product Microsite

**Feature**: FEAT-030 - Product Microsite
**Feature Requirements**: SITE-01, SITE-02, SITE-03, SITE-04, SITE-05, SITE-06, SITE-07, SITE-08
**PRD Requirements**: None — documentation/meta-feature
**Priority**: P1
**Status**: Approved

## Story

**As a** data platform engineer evaluating tablespec
**I want** a public microsite that explains the product, source-semantic bronze boundary, installation path, and reference material
**So that** I can decide whether to adopt tablespec and try the happy path without reading the repository internals first

## Context

GitHub Pages currently serves the package index used for installation. The
microsite must share that Pages site without breaking `/simple/`. FEAT-015 owns
API reference generation; this story owns the public product shell and navigation.

## Walkthrough

1. User opens `https://documentdrivendx.github.io/tablespec/`.
2. System presents the Hugo/Hextra homepage with tablespec's category, value, and first action.
3. User follows Getting Started to install from `/simple/` and run the compile path.
4. User opens Concepts to understand raw, ingested, and silver boundaries.
5. User opens Reference or API Reference for exact commands, artifacts, and Python surfaces.

## Acceptance Criteria

- [ ] **US-038-AC1** - Given the site source under `website/`, when Hugo builds, then the output includes Home, Getting Started, Core Concepts, CLI Reference, API Reference entry point, and Demos pages.
- [ ] **US-038-AC2** - Given the Pages artifact, when it is inspected before deployment, then `/index.html`, `/simple/index.html`, and `/simple/tablespec/index.html` are all present.
- [ ] **US-038-AC3** - Given the generated site, when Playwright checks desktop and mobile viewports, then the homepage, top-level sections, representative deep pages, and navigation state render without clipped or overlapping text.
- [ ] **US-038-AC4** - Given the Getting Started page, when a user follows installation instructions, then the documented command still uses the project package index and remains compatible with release verification.
- [ ] **US-038-AC5** - Given the Concepts section, when a user reads the raw/ingested/silver boundary, then it states that ingested preserves source semantics while silver begins with cross-source conformance, survivorship, entity resolution, enrichment, or dimensional modeling.

## Edge Cases

- **Docs deploy without a new package release**: `/simple/` is rebuilt from release metadata or carried forward; it is not emptied.
- **API reference deferred**: a stable API Reference entry point exists and broken links fail the docs build.
- **Mobile navigation**: the mobile drawer reaches the same core pages as desktop navigation.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Hugo inventory | US-038-AC1 | `website/` source | run Hugo build | required pages exist in output |
| Pages coexistence | US-038-AC2 | built Pages artifact | inspect paths | site root and `/simple/` package index exist |
| Responsive UI | US-038-AC3 | local site server | run Playwright desktop/mobile tests | screenshots pass; no nav/state regressions |
| Install command | US-038-AC4 | Getting Started page | run link/content check | install command points at `/simple/` |
| Boundary concept | US-038-AC5 | Concepts page | inspect rendered content | raw/ingested/silver boundary is present |

## Dependencies

- **Feature Spec**: FEAT-030
- **ADR**: ADR-014
- **Related Feature**: FEAT-015

## Out of Scope

- Operational web application behavior.
- Publishing private data, credentials, or Databricks workspace state.
