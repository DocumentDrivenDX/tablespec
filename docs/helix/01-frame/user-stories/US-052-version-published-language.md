---
ddx:
  id: US-052
---

# US-052: Version the Published Language and Surface the Glossary

**Feature**: FEAT-035 — Domains
**PRD Requirements**: FR-24.6, FR-24.7
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer who exports tables to other teams,
**I want** a breaking change to an exported table to require a version bump that consumers must explicitly accept, and the domain's vocabulary to show up where people and prompts read the schema,
**So that** consumers learn about a break from a failing validate run before it lands, not from a broken load after.

## Context

Second slice of FEAT-035 after the adversarial review recorded in ADR-021.
Integration patterns stay advisory; this story adds the version contract, the
baseline comparison, the `separate_ways` rule, and the glossary surfaces.

## Walkthrough

1. User sets `version: 1.0.0` on `eligibility/domain.yaml` and pins it from `claims/domain.yaml` with `suppliers.eligibility.version: ">=1.0.0,<2.0.0"`.
2. User removes a column from the exported `member` table and bumps `version` to `1.1.0`.
3. User runs `tablespec validate tables/ --baseline tables-at-last-release/`.
4. System lists the published-language changes and fails with `DOM-COMPAT` because a breaking change needs a MAJOR bump.
5. User sets `version: 2.0.0`; validate now fails `DOM-PIN` in `claims` because its range excludes 2.x, until the consumer widens the range.
6. User opens the guidebook: each column with a `term` shows the definition; the documentation prompt for the table lists the cited terms.

## Acceptance Criteria

- [ ] **US-052-AC1** — Given `domain.yaml`, when it is loaded, then `version` must be `MAJOR.MINOR.PATCH` and `suppliers.<d>.version` must be a comma-separated list of `>=`, `<=`, `==`, `!=`, `>`, `<` clauses; anything else is rejected.
- [ ] **US-052-AC2** — Given loaded domains, when the supplier rules run, then a pin the supplier's version does not satisfy, or a pin on an unversioned supplier, is one `DOM-PIN` error; a `separate_ways` edge with a `consumes` list or a crossing foreign key is a `DOM-WAYS` error; a domain that exports without a version is a `DOM-VERSION` warning.
- [ ] **US-052-AC3** — Given two roots, when the published language is compared, then a removed export or removed exported table is breaking, an added export is informational, a column change is classified by the compatibility checker with a new required column downgraded to a warning, and a breaking change without a MAJOR bump (or with a missing version on either side) is one `DOM-COMPAT` error.
- [ ] **US-052-AC4** — Given `tablespec validate <path> --baseline <old>` where a `domain.yaml` applies to the path (a corpus root, one domain, or one table), when it runs, then it prints the published-language changes for the domains the path covers, exits 1 on `DOM-COMPAT`, and exits 0 otherwise; when no `domain.yaml` applies on either side it prints a note saying nothing was compared.
- [ ] **US-052-AC5** — Given a glossary, when a table page renders or a documentation prompt is generated, then each cited `term` shows its definition (aliases resolved to the canonical key), only cited terms appear in the prompt in sorted order, and both surfaces are unchanged when no glossary is supplied.

## Edge Cases

- Both roots unversioned with a breaking change: `DOM-COMPAT` says "unset -> unset".
- A domain present only in the old root with exports: reported as `domain_removed`, no `DOM-COMPAT` (nothing to version on the new side).
- A term cited through an alias appears once in the prompt under its canonical key.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Bad version string | US-052-AC1 | `version: v1.0.0` | load | `ValidationError` |
| Pin outside range | US-052-AC2 | supplier 2.0.0, pin `<2.0.0` | `validate_suppliers` | one `DOM-PIN` |
| Separate ways consumes | US-052-AC2 | pattern `separate_ways`, consumes `[member]`, FK crosses | `validate_domains` | two `DOM-WAYS` |
| Removed column, minor bump | US-052-AC3 | 1.0.0 → 1.1.0 | `validate_published_language` | one `DOM-COMPAT` |
| Removed column, major bump | US-052-AC3 | 1.0.0 → 2.0.0 | same | no findings |
| CLI baseline | US-052-AC4 | as above | `validate new --baseline old` | exit 1, "Published-language changes" |
| Glossary on page | US-052-AC5 | column `term: mbr` (alias) | `render_table_page(glossary=...)` | definition in tooltip and inline |

## Dependencies

- **Stories**: US-051.
- **Feature Spec**: FEAT-035 — Domains
- **Feature Requirements**: F035-VER-01..04, F035-GLOSS-01..02
- **PRD Requirements**: FR-24.6, FR-24.7
- **External**: None.

## Out of Scope

- Enforcing conformist, anti-corruption, shared-kernel, partnership, or open-host semantics (ADR-021 decision 5).
- Entity/event/reference table classification and subdomain kind (ADR-021 decision 7).
- Persisting published-language changes to the changelog.

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
