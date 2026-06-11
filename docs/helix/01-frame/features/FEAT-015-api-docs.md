---
ddx:
  id: FEAT-015
---

# FEAT-015: Browsable API Documentation

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-015
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: UMF Model and I/O
**Covered PRD Requirements**: None — meta-feature anchored to the Product Vision and Principles per the traceability convention (principles.md §Tension Resolution, decided 2026-06-10); documents the UMF surface modeled under FR-1.x.
**Cross-Subsystem Rationale**: Documentation support feature: API docs expose the modeled UMF surface rather than owning new product behavior.

## Description

Auto-generated API documentation using MkDocs + mkdocstrings, built from existing docstrings and Pydantic Field descriptions.

## Motivation

The library has 35+ public API symbols, complex nested Pydantic models, and domain-specific concepts. Inline documentation (docstrings, Field descriptions) is good but not browsable or searchable without reading source.

The GitHub Pages site currently serves a PyPI package index, not documentation. The checked-in MkDocs content is source documentation; it is not the live public product microsite.

## Planned Approach

- MkDocs with mkdocstrings plugin for auto-generation from type annotations and docstrings
- Pydantic models benefit most since their Field(description=...) metadata is already rich
- API-reference deployment must be coordinated with FEAT-030 and ADR-014 so the public product microsite and the existing `/simple/` package index remain available from the same Pages site
## User Stories

- [US-028 — Publish Browsable API Documentation](../user-stories/US-028-publish-browsable-api-docs.md)

## Source

- Configuration: `mkdocs.yml`
- Content: auto-generated from `src/tablespec/` docstrings

## Relationship to FEAT-030

FEAT-015 owns API reference generation. FEAT-030 owns the public product microsite, information architecture, Hugo/Hextra shell, demos, and Pages deployment architecture. If the microsite embeds or links API reference pages, this feature remains the source of truth for how Python symbols are generated and validated.
