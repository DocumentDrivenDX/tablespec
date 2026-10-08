---
ddx:
  id: US-013
---

# US-013: Generate Sample Data from UMF

**Feature**: FEAT-011 — Sample Data Generation
**PRD Requirements**: FR-12.1, FR-12.2, FR-12.3, FR-12.4, FR-12.5
**Priority**: P1
**Status**: Approved

## Story

**As a** QA engineer setting up test environments,
**I want** generate realistic sample data from UMF specifications,
**So that** I can test pipelines with data that respects types, constraints, and foreign key relationships.

## Context

This story covers the generate sample data from umf slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a generate sample data from umf fixture or source object.
2. System runs the the sample-data generator runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-013-AC1** — Given a `member` UMF with `claim_id`, `status`, and `service_date` constraints, when the sample-data generator runs, then **US-013-AC1** - Sample data engine generates rows matching UMF column types and constraints
- [ ] **US-013-AC2** — Given a `member` UMF with `claim_id`, `status`, and `service_date` constraints, when the sample-data generator runs, then **US-013-AC2** - Foreign key relationships produce referentially consistent data across tables
- [ ] **US-013-AC3** — Given a `member` UMF with `claim_id`, `status`, and `service_date` constraints, when the sample-data generator runs, then **US-013-AC3** - Healthcare domain types (SSN, NPI, state codes) generate realistic values
- [ ] **US-013-AC4** — Given a `member` UMF with `claim_id`, `status`, and `service_date` constraints, when the sample-data generator runs, then **US-013-AC4** - Output available in CSV and JSON formats with configurable row counts

- [ ] **US-013-AC5** — Given fabricated legal specs and a fixed seed, repeated generation produces identical rows with legal row/parent correlations.
- [ ] **US-013-AC6** — Given a verified dataset and an offline sink, staging batches publish one replacement per table; failed staging leaves that target data untouched.
- [ ] **US-013-AC7** — Given a configured scale and parent overrides, child counts propagate and all generated foreign keys reference fabricated parent rows.
- [ ] **US-013-AC8** — Given unsupported or unsatisfiable constraints, generation fails before sink writes; a local review requires no authentication or workspace access.

- [ ] **US-013-AC9** — Given small and demo legal fixtures at several seeds, unique team/wall pairs are disjoint, every matter has a partner and another member, and entries use eligible team members; independent audits fail on injected violations.
- [ ] **US-013-AC10** — Given typed documents, narratives and sample invoice windows, issue labels match clauses, hours/rates reconcile exactly, invoice totals equal period sums, and parent coverage/skew meet tested bounds.
- [ ] **US-013-AC11** — Given an offline Files API port, explicit bulk loading uploads bounded CSV chunks, COPY loads staging, then overwrites targets and cleans files; verify-only issues reads and fails on mismatched counts or integrity checks.

## Edge Cases

- **foreign keys must stay referentially consistent**: foreign keys must stay referentially consistent
- **domain values must look realistic**: domain values must look realistic
- **CSV and JSON output should both honor row counts**: CSV and JSON output should both honor row counts

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Generate typed sample rows | US-013-AC1 | member UMF with claim_id, status, service_date | the sample-data generator runs | **US-013-AC1** - Sample data engine generates rows matching UMF column types and constraints |
| Preserve foreign-key consistency | US-013-AC2 | claims.claim_id -> member.member_id | the sample-data generator runs | **US-013-AC2** - Foreign key relationships produce referentially consistent data across tables |
| Use healthcare domain generators | US-013-AC3 | domain types ssn, npi, state_code | the sample-data generator runs | **US-013-AC3** - Healthcare domain types (SSN, NPI, state codes) generate realistic values |
| Emit CSV and JSON row sets | US-013-AC4 | 10 rows to CSV and 25 rows to JSON | the sample-data generator runs | **US-013-AC4** - Output available in CSV and JSON formats with configurable row counts |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-011 — Sample Data Generation
- **Feature Requirements**: SAMPLE-01, SAMPLE-02, SAMPLE-03
- **PRD Requirements**: FR-12.1, FR-12.2, FR-12.3, FR-12.4, FR-12.5
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- foreign-key discovery beyond the UMF constraints
- production data ingestion

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
