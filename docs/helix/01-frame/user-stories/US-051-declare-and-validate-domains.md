---
ddx:
  id: US-051
---

# US-051: Declare and Validate Domains

**Feature**: FEAT-035 — Domains
**PRD Requirements**: FR-24.1, FR-24.2, FR-24.3, FR-24.4, FR-24.5
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer who owns one set of tables and consumes another team's,
**I want** to declare my domain's owner, exported tables, suppliers, and glossary in one file and have cross-domain references checked against the other team's declarations,
**So that** a reference into another domain is a reviewed contract, not a string prefix that happens to resolve.

## Context

This story covers the first vertical slice of FEAT-035: the `domain.yaml`
declaration, the cross-domain foreign-key fields, the validation rules, the
`tablespec validate` entry point, and the guidebook domain map. Surface is
defined in the solution design (SD-035), not here.

## Walkthrough

1. User creates `eligibility/domain.yaml` (exports `member`) and `claims/domain.yaml` (supplier `eligibility`, pattern `customer_supplier`, consumes `member`), each next to its split-format tables.
2. User adds a foreign key on `claims/medical_claims` with `references_domain: eligibility` targeting `member.member_id`.
3. User runs `tablespec validate <root>`.
4. System validates each domain's tables, then checks exports, suppliers, cross-domain keys, and glossary terms, printing `DOM-*` findings and exiting non-zero on errors.
5. User runs `tablespec guidebook <root>` and opens `domains.html` to review owners, exports, supplier edges, and cross-domain references.

## Acceptance Criteria

- [ ] **US-051-AC1** — Given a directory with a `domain.yaml`, when it is loaded, then `name` must equal the directory name, `exports`/`suppliers`/`glossary` parse into typed models, unknown keys and unknown integration patterns are rejected, and a glossary file in either bare or `terms:` shape loads.
- [ ] **US-051-AC2** — Given a foreign key with `references_domain` (or the legacy `references_pipeline`), when the UMF loads, then both spellings are populated, `cross_pipeline` is true, disagreement between the two is an error, an unknown key on the foreign key is rejected rather than dropped, and `term` on a table or column round-trips through split format without touching `canonical_name`.
- [ ] **US-051-AC3** — Given two loaded domains, when the domain rules run, then an export that is not a table or lacks a primary key, a supplier that does not exist or whose consumed table is not exported, a cross-domain key that targets a non-exported table or a non-primary-key column or an undeclared supplier, and a `term` missing from the glossary each produce one `DOM-*` error, while the same term defined differently in two glossaries produces a `DOM-DRIFT` warning and no error.
- [ ] **US-051-AC4** — Given a root that is or directly contains `domain.yaml` directories, when `tablespec validate <root>` runs, then it validates every domain's tables, prints domain errors and warnings, exits 1 on any error, and exits 0 with a domain and table count otherwise.
- [ ] **US-051-AC5** — Given a guidebook root with domains, when the guidebook generates, then `domains.html` lists domains with owner and exports, supplier edges with their pattern, and cross-domain references linking to the target table page, the top index links to it, and no such page is written for a root without domains.

## Edge Cases

- **Nested domain directories**: only the root and its direct children are domains; a `domain.yaml` deeper down is ignored (the qualifier must stay one segment).
- **A table fails to load inside a domain**: the domain still loads; the failure is a `DOM-LOAD` error and other rules still run.
- **Qualified `references_table` without `references_domain`**: `eligibility.member` is treated as cross-domain via its prefix; `references_domain` stays unset.
- **No glossary declared**: `DOM-TERM` is skipped for that domain.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Load domain.yaml | US-051-AC1 | `claims/domain.yaml` with `name: billing` | `load_domain` | `DomainLoadError` naming both names |
| FK reconciliation | US-051-AC2 | `references_domain: a`, `references_pipeline: b` | construct `ForeignKey` | `ValidationError` "disagree" |
| Export without key | US-051-AC3 | `member` exported, no `primary_key` | `validate_exports` | one `DOM-EXPORT` finding |
| Non-PK target | US-051-AC3 | FK targets `member.first_name` | `validate_cross_domain_keys` | one `DOM-XREF` finding |
| Term drift | US-051-AC3 | `member` defined differently in two glossaries | `validate_domains` | one `DOM-DRIFT` warning, `report.ok` |
| CLI clean | US-051-AC4 | valid two-domain corpus | `tablespec validate <root>` | exit 0, "2 domains" |
| CLI error | US-051-AC4 | supplier's export removed | `tablespec validate <root>` | exit 1, "Domain errors" |
| Domain map | US-051-AC5 | two-domain corpus | `generate_guidebook` | `domains.html` written and linked |

## Dependencies

- **Stories**: US-046 (guidebook) for the page and index conventions.
- **Feature Spec**: FEAT-035 — Domains
- **Feature Requirements**: F035-DECL-01..03, F035-REF-01..02, F035-VAL-01..05, F035-MAP-01
- **PRD Requirements**: FR-24.1–FR-24.5
- **External**: None.

## Out of Scope

- Domain-scoped `domain_type` registries.
- Filtering the compatibility report to a domain's exports.
- Deriving catalog or schema routing from `domain.yaml` (ADR-013 stands).
- Renaming the line-of-business `nullable` context keys or `context_column`.

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
