---
ddx:
  id: AR-2026-09-15-ddd-follow-up-plan-review
  links:
    - ADR-020
    - ADR-021
    - FEAT-035
---

# Adversarial Review: DDD Follow-Up Plan (FEAT-035 slice 2)

**Review Date**: 2026-09-15  
**Scope**: the six-item follow-up plan after the first domains slice (ADR-020)  
**Status**: complete; verdict incorporated in ADR-021 and US-052  
**Reviewer**: Codex (`codex exec`, read-only sandbox, independent of the author's reasoning)  
**Primary Governing Artifact**: `docs/helix/02-design/adr/ADR-021-published-language-versioning-and-advisory-patterns.md`

## Plan under review

1. Make integration patterns executable (conformist, anti-corruption, shared kernel, customer-supplier rules).
2. Version the published language (compatibility filtered to exports, version bump rule, consumer pins, changelog entry, `domain-diff` or `--baseline`).
3. Replace the table classification with `UMF.kind: entity | event | reference` plus export and dedup rules.
4. Subdomain kind `core | supporting | generic` with a shared-kernel suggestion.
5. Glossary in guidebook column pages and documentation prompts.
6. DDD concept page and mapping table with external sources.

## Verdict

**BLOCK** (11 blocking, 6 warning). Disposition below; every blocking finding was accepted or resolved by re-scoping. No finding was rejected.

## Findings and disposition

| # | Severity | Area | Disposition | Where it landed |
|---|---|---|---|---|
| 1 | BLOCKING | Contracts before code | accept | SD-035 extended with version grammar, rule IDs, published-language boundary, CLI and glossary contracts; FR-24.6, FR-24.7; US-052 |
| 2 | BLOCKING | Pattern authority (consumer-only declaration) | accept | Patterns advisory; only `separate_ways` enforced (`DOM-WAYS`) — ADR-021 decision 5 |
| 3 | BLOCKING | Shared-kernel identity undefined | accept | Shared-kernel rule dropped |
| 4 | BLOCKING | Conformist string equality neither necessary nor sufficient | accept | Conformist rule dropped |
| 5 | BLOCKING | No structured mapping to detect copied columns / ACL | accept | Anti-corruption rule dropped |
| 6 | BLOCKING | Item 1 depends on item 2 | accept | Versioning implemented first; customer-supplier enforcement not built |
| 7 | BLOCKING | "Unpinned consumer exempt" is backwards | accept | Supplier release rule (`DOM-COMPAT`) and consumer range rule (`DOM-PIN`) are separate; a bump never exempts a consumer |
| 8 | BLOCKING | Domain compatibility boundary undefined | accept | Boundary defined (exports + columns/types/nullability/PK); union of export lists; removals breaking; forward-only break downgraded to warning |
| 9 | BLOCKING | Version contract undefined (PEP 440 vs SemVer, optionality) | accept | Strict `MAJOR.MINOR.PATCH`; small explicit range grammar; missing version on either side of a breaking change is itself `DOM-COMPAT`; `DOM-VERSION` warning |
| 10 | BLOCKING | Changelog enum and CLI design open | accept | `--baseline` on `validate`, read-only report; no `ChangeType` change; command count unchanged |
| 11 | BLOCKING | `kind` rules import application semantics into data | accept | Item 3 deferred entirely (ADR-021 decision 7) |
| 12 | WARNING | `kind` overlaps `table_type` | accept | Same deferral |
| 13 | WARNING | Shared-kernel suggestions from shape or consumer count | accept | Dropped |
| 14 | WARNING | Subdomain kind asserts 1:1 with bounded context | accept | Item 4 deferred |
| 15 | WARNING | Glossary rendering interface unspecified | accept | Explicit `glossary` keyword on `render_table_page`; chip with `title` plus inline definition line; generator passes the owning domain's glossary |
| 16 | WARNING | Prompt API unspecified | accept | Keyword-only `glossary` accepting `Glossary` or mapping; only cited terms, sorted, aliases canonicalized; output unchanged without it |
| 17 | WARNING | Concepts page needs index card, seeds, tests; sources conflated | accept | `concepts/domains.md` with card, link-check seed, Playwright coverage; primary DDD sources separated from adjacent ideas |

## Uncertainty the reviewer raised

- Whether glossary, `domain_type`, expectations, and relationships belong to the published language: decided **no** for this slice (SD-035 boundary); may be widened by a later ADR.
- Compatibility direction: decided **backward** gates releases; forward-only breaks are warnings.
- Whether `kind` is descriptive or operational: deferred until lifecycle fields exist.

## Evidence

- Review brief and raw JSON verdict were produced in the session scratchpad and are summarized here; the brief's constraints are the same as SD-035 and ADR-020.
- Verification after incorporation: `tests/unit/test_domain_versioning.py`, `tests/unit/test_glossary_surfaces.py`, microsite content and link-check suites.
