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

Auto-generated API documentation site using MkDocs + mkdocstrings, built from existing docstrings and Pydantic Field descriptions.

## Motivation

The library has 35+ public API symbols, complex nested Pydantic models, and domain-specific concepts. Inline documentation (docstrings, Field descriptions) is good but not browsable or searchable without reading source.

The GitHub Pages site currently serves a PyPI package index, not documentation.

## Planned Approach

- MkDocs with mkdocstrings plugin for auto-generation from type annotations and docstrings
- Pydantic models benefit most since their Field(description=...) metadata is already rich
- Deploy alongside or integrated with the existing GitHub Pages PyPI index
## User Stories

- [US-028 — Publish Browsable API Documentation](../user-stories/US-028-publish-browsable-api-docs.md)

## Source

- Configuration: `mkdocs.yml`
- Content: auto-generated from `src/tablespec/` docstrings
