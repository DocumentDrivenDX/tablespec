---
ddx:
  id: ADR-021
---

# ADR-021: Published-Language Versioning and Advisory Integration Patterns

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-09-15 | Accepted | Erik LaBianca | FEAT-035, ADR-020, FEAT-022 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | ADR-020 gave a domain an `exports` list (its published language) and a `suppliers.pattern` (its context map) but no way to say the published language changed, no way for a consumer to say which supplier version it accepts, and no statement of what the patterns are allowed to do. A follow-up plan proposed enforcing each pattern (conformist, anti-corruption, shared kernel) and adding an entity/event/reference table classification; an adversarial review (Codex, 2026-09-15) blocked that plan on eleven findings. |
| Current State | `DomainMetadata.version` accepted any string. `SupplierRelationship` had no version range. `compatibility.check_compatibility` compares one old table to one new table and classifies backward and forward compatibility, but nothing pairs domains or export lists across revisions. `ChangeType` is a closed enum tied to git history. The consumer alone declares a supplier edge, so bilateral patterns cannot be verified from the metadata. `DerivationCandidate` carries no structured source-domain mapping, so "which columns copy supplier data" cannot be answered reliably. |
| Requirements | FEAT-035; PRD FR-24.6, FR-24.7. |
| Decision Drivers | A breaking change to an exported table must be signalled, not discovered; a consumer must be able to state what it accepts; rules must be derivable from declared metadata, never inferred from table shape; no new CLI command; deterministic output; no change to emitted artifacts. |

## Decision

1. **Published language has a defined boundary.** It is the export list plus,
   for each exported table, the column set, column types, nullability, and
   primary key: exactly what `check_compatibility` compares. Glossary terms,
   expectations, relationships, and non-exported tables are not part of it.
2. **`domain.version` is strict `MAJOR.MINOR.PATCH`.** Optional. A domain
   that exports tables without a version gets a `DOM-VERSION` warning. No
   pre-release or build suffix; comparison is numeric per segment. This is
   deliberately not PEP 440 and not a full SemVer range language.
3. **Consumers pin suppliers with a small range grammar.**
   `suppliers.<d>.version` is a comma-separated list of clauses, each an
   operator from `>=`, `<=`, `==`, `!=`, `>`, `<` and a version. `DOM-PIN`
   fails when the supplier declares no version or its version does not
   satisfy the range. Supplier release validation and consumer range
   resolution are separate rules: a major bump never makes a consumer safe;
   the consumer's own range decides.
4. **Baseline comparison lives on `validate`, read-only.**
   `tablespec validate <root> --baseline <old_root>` pairs domains by name
   across the two roots, compares the union of old and new export lists
   (removed export or removed exported table is breaking; added export is
   informational), runs `check_compatibility` on tables exported on both
   sides, and reports each change under "Published-language changes". A
   forward-only break (new required column) is reported as a warning because
   it constrains producers, not existing consumers. `DOM-COMPAT` fails when a
   breaking change is not matched by a MAJOR bump, or when either side has no
   version. Nothing is written; `ChangeType` is unchanged.
5. **Integration patterns are advisory, except `separate_ways`.** A pattern is
   the consumer's assertion, rendered on the domain map. The metadata cannot
   represent bilateral agreement (partnership, shared kernel) or supplier-side
   capabilities (open host), and conformance or translation cannot be
   detected from unstructured derivations, so enforcing them would be
   arbitrary. The one contradiction the metadata can see is enforced:
   `separate_ways` with a `consumes` list or a crossing foreign key is
   `DOM-WAYS`.
6. **Glossary terms are shown, not only checked.** The guidebook table page
   takes an optional glossary and renders each `term` as a chip whose tooltip
   and inline line carry the definition; the documentation prompt takes an
   optional keyword-only glossary and lists only the terms the table and its
   columns cite, sorted, aliases resolved to the canonical key.
7. **Deferred, not rejected.** An entity/event/reference table classification
   and a core/supporting/generic subdomain kind are not added. The first
   needs lifecycle fields (event time, append policy) before any rule on it
   is enforceable, and `table_type` already carries several vocabularies that
   need a migration design; the second asserts a one-to-one mapping between
   bounded context and subdomain that the model does not justify.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Enforce conformist / anti-corruption / shared kernel from `pattern` | Turns the context map into a contract | Consumer-only declaration cannot establish bilateral or supplier-side facts; term string equality is neither necessary (aliases) nor sufficient (same word, different definition); no structured mapping identifies copied columns; two local tables with one name are not a shared kernel | Rejected: findings 2-5 of the review |
| Reuse `packaging` SpecifierSet for pins | Existing dependency-resolver code | PEP 440 semantics differ from SemVer; the resolver is pipeline.yaml-specific dead code; `packaging` is not a declared dependency | Rejected: small explicit grammar instead |
| New `tablespec domain-diff` command | Clear separation | Raises the documented command count; two CLI designs for one read-only comparison | Rejected: `--baseline` on `validate` |
| Record `published_language_changed` in the changelog | Durable history | `ChangeType` is a closed, exhaustively tested enum tied to per-table git history that cannot see `domain.yaml` | Rejected: report output only |
| Add `UMF.kind: entity/event/reference` with export and dedup rules | Fixes a muddled classification | Rules import application-model assumptions into physical data (events are routinely exported; dedup by id and arrival does not make state); no lifecycle fields to validate against; overlaps `table_type` with no precedence | Deferred (decision 7) |
| **Versioned published language + pins + baseline on validate + advisory patterns (selected)** | Every rule derives from declared metadata; no new command; no artifact change | Patterns stay descriptive until the model can represent authority | **Selected** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | A breaking export change now has to be versioned and a consumer has to accept it explicitly. The context map is honest about what it enforces. Glossary definitions reach readers and the LLM. |
| Negative | Existing `domain.yaml` files with a non-SemVer `version` string fail to load until corrected. Pattern labels other than `separate_ways` carry no enforcement, which some readers will expect. |
| Neutral | `check_compatibility` semantics are reused unchanged; a later ADR may widen the published-language boundary to expectations or terms. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Teams expect `conformist` to be enforced | M | L | The SD-035 contract and the concepts page state that patterns are advisory; `DOM-WAYS` is the only enforced one |
| Baseline roots drift (comparing unrelated corpora) | L | M | Domains are paired by name; a domain missing on one side is reported, never silently skipped |
| Version grammar too small for real pins | L | L | Grammar is documented; extending it is additive |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Removing a column from an exported table without a MAJOR bump yields exactly one `DOM-COMPAT`; with the bump, none | `tests/unit/test_domain_versioning.py` fails |
| A pin outside the supplier's version yields one `DOM-PIN`; `separate_ways` with `consumes` yields `DOM-WAYS` | same |
| A table page rendered with a glossary carries the term definition; the prompt lists only cited terms | `tests/unit/test_glossary_surfaces.py` fails |

## Supersession

- **Supersedes**: None. Extends ADR-020.
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: None.
- **Practice override**: None; "no hardcoded catalogs in emitted artifacts" is preserved.
- **No concern impact**: Metadata declaration, validation, and rendering only.

## References

- Adversarial review record: Codex, 2026-09-15 (BLOCK; eleven blocking findings, all accepted or deferred as recorded here)
- FEAT-035 (F035-VER-01..04, F035-GLOSS-01..02); US-052; SD-035
- ADR-020 (domains); FEAT-022 (compatibility checker); ADR-018 (lineage words)
- `src/tablespec/models/domain.py` (`SemVer`, `validate_version_range`, `version_satisfies`, `is_major_bump`), `src/tablespec/domain_validator.py` (`validate_published_language`), `src/tablespec/guidebook/renderer.py`, `src/tablespec/prompts/documentation.py`

## Review Checklist

- [x] Context names a specific problem — unversioned exports, unpinnable suppliers, undefined pattern authority
- [x] Decision statement is actionable (seven numbered decisions)
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete
- [x] ADR consistent with FEAT-035 and PRD FR-24.6–FR-24.7
