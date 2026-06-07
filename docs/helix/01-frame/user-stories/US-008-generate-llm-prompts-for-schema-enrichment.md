---
ddx:
  id: US-008
---

# US-008: Generate LLM Prompts for Schema Enrichment

**Feature**: FEAT-006 — LLM Prompt Generation
**PRD Requirements**: FR-6.1, FR-6.2, FR-6.3, FR-6.4, FR-6.5, FR-6.6, FR-6.7
**Priority**: P1
**Status**: Implemented

## Story

**As a** platform engineer integrating LLMs into a schema management pipeline,
**I want** generate structured prompts from UMF metadata for documentation, validation rules, relationship discovery, and survivorship logic,
**So that** I can feed consistent, domain-aware context to an LLM and get back enrichments that slot directly into the UMF schema.

## Acceptance Criteria

- [ ] `generate_documentation_prompt` produces a prompt covering business purpose, data flow, relationships, and compliance context for a given UMF table
- [ ] `generate_validation_prompt` produces a table-level prompt for multi-column expectation generation
- [ ] `generate_column_validation_prompt` produces single-column prompts with prompt hash tracking for incremental re-generation
- [ ] `generate_relationship_prompt` produces a prompt for FK discovery with cardinality estimation, supporting both UMF schemas and lookup table directories, with healthcare-domain awareness (member/provider/claim IDs, drug codes)
- [ ] `generate_survivorship_prompt` produces a prompt for data survivorship and merge logic mapping
- [ ] Helper functions `has_validation_rules` and `should_generate_column_prompt` correctly filter columns to avoid redundant prompt generation
