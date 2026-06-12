---
ddx:
  id: US-008
---

# US-008: Generate LLM Prompts for Schema Enrichment

**Feature**: FEAT-006 — LLM Prompt Generation
**PRD Requirements**: FR-6.1, FR-6.2, FR-6.3, FR-6.4, FR-6.5, FR-6.6, FR-6.7
**Priority**: P1
**Status**: Approved

## Story

**As a** platform engineer integrating LLMs into a schema management pipeline,
**I want** generate structured prompts from UMF metadata for documentation, validation rules, relationship discovery, and survivorship logic,
**So that** I can feed consistent, domain-aware context to an LLM and get back enrichments that slot directly into the UMF schema.

## Context

This story covers the generate llm prompts for schema enrichment slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate llm prompts for schema enrichment fixture or source object.
2. System runs the the prompt-generation helpers run for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-008-AC1** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then `generate_documentation_prompt` produces a prompt covering business purpose, data flow, relationships, and compliance context for a given UMF table
- [ ] **US-008-AC2** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then `generate_validation_prompt` produces a table-level prompt for multi-column expectation generation
- [ ] **US-008-AC3** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then `generate_column_validation_prompt` produces single-column prompts with prompt hash tracking for incremental re-generation
- [ ] **US-008-AC4** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then `generate_relationship_prompt` produces a prompt for FK discovery with cardinality estimation, supporting both UMF schemas and lookup table directories, with healthcare-domain awareness (member/provider/claim IDs, drug codes)
- [ ] **US-008-AC5** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then `generate_survivorship_prompt` produces a prompt for data survivorship and merge logic mapping
- [ ] **US-008-AC6** — Given a `member` UMF plus a `claim_id -> member_id` relationship, when the prompt-generation helpers run, then Helper functions `has_validation_rules` and `should_generate_column_prompt` correctly filter columns to avoid redundant prompt generation

## Edge Cases

- **prompt generation must not duplicate prompts unnecessarily**: prompt generation must not duplicate prompts unnecessarily
- **relationship prompts need cardinality context**: relationship prompts need cardinality context
- **survivorship prompts should stay separate from validation prompts**: survivorship prompts should stay separate from validation prompts

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Generate documentation prompt | US-008-AC1 | member UMF plus claim_id -> member_id | the prompt-generation helpers run | `generate_documentation_prompt` produces a prompt covering business purpose, data flow, relationships, and compliance context for a given UMF table |
| Generate validation prompt | US-008-AC2 | member_id, plan_code, status | the prompt-generation helpers run | `generate_validation_prompt` produces a table-level prompt for multi-column expectation generation |
| Generate column validation prompt | US-008-AC3 | plan_code VARCHAR(12) | the prompt-generation helpers run | `generate_column_validation_prompt` produces single-column prompts with prompt hash tracking for incremental re-generation |
| Generate relationship prompt | US-008-AC4 | claim_id -> member_id with cardinality 1:many | the prompt-generation helpers run | `generate_relationship_prompt` produces a prompt for FK discovery with cardinality estimation, supporting both UMF schemas and lookup table directories, with healthcare-domain awareness (member/provider/claim IDs, drug codes) |
| Generate survivorship prompt | US-008-AC5 | member_id and status survivorship rules | the prompt-generation helpers run | `generate_survivorship_prompt` produces a prompt for data survivorship and merge logic mapping |
| Skip redundant prompt generation | US-008-AC6 | columns plan_code and status with validation rules | the prompt-generation helpers run | Helper functions `has_validation_rules` and `should_generate_column_prompt` correctly filter columns to avoid redundant prompt generation |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-006 — LLM Prompt Generation
- **Feature Requirements**: LLM-01, LLM-02, LLM-03
- **PRD Requirements**: FR-6.1, FR-6.2, FR-6.3, FR-6.4, FR-6.5, FR-6.6, FR-6.7
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- prompt execution or model selection
- authoring actual UMF content in the prompt generators

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
