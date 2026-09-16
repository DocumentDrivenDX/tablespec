---
ddx:
  id: FEAT-035
  links:
    - ADR-020
    - US-051
---

# Feature Specification: FEAT-035 — Domains

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-035
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Domains
**Covered PRD Requirements**: FR-24.1, FR-24.2, FR-24.3, FR-24.4, FR-24.5
**Cross-Subsystem Rationale**: The guidebook (FR-22) renders the domain map from the same declarations; the guidebook feature (FEAT-033) keeps ownership of page conventions, this feature owns the declarations and the rules.

## Overview

Give a directory of UMF tables an owner, a published surface, a context map,
and a vocabulary through one `domain.yaml`, and check cross-domain references
against those declarations. A domain is the DDD bounded context; its exports
are the published language; its suppliers are the context map; its glossary is
the ubiquitous language. `domain_type` on a column is a value-object type
scoped to a domain.

## Ideal Future State

A data engineer adds `domain.yaml` next to a team's tables, lists what other
teams may reference, names the teams it depends on and how, and points at a
glossary. `tablespec validate <root>` refuses a foreign key into another
domain unless the target is exported, keyed, and supplied through a declared
edge. The guidebook shows the map. Renaming or un-exporting a table is a
reviewed diff in `domain.yaml`, and every consumer's next validate run says
what broke.

## Problem Statement

- **Current situation**: Cross-directory references resolve by string prefix.
  The registry calls the prefix a namespace, the guidebook a group, the
  foreign-key model a pipeline. None carries an owner or a published surface.
  Validation only sees sibling tables in one directory.
- **Pain points**: A reference into another team's table cannot be checked
  against anything that team declared. The same word means different things
  in different directories with no place to say so. Nested models silently
  dropped unknown foreign-key keys.
- **Desired outcome**: One declaration per domain, one name for the unit,
  checkable cross-domain references, a rendered map, and loud failure on
  unknown keys.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Declaration | What does my domain own, export, consume, and mean? | `domain.yaml`: name, owner, description, version, exports, suppliers (with integration pattern), glossary. |
| References | How do I point at another domain's table? | `ForeignKey.references_domain` and `integration`; legacy `references_pipeline` reconciled; `term` on tables and columns. |
| Validation | Is my reference into another domain allowed? | Rules `DOM-EXPORT`, `DOM-SUPPLIER`, `DOM-XREF`, `DOM-TERM`, advisory `DOM-DRIFT`, via `tablespec validate <root>`. |
| Map | Who supplies whom, and through what? | Guidebook `domains.html` with owners, exports, supplier edges, cross-domain references. |

## Requirements

### Functional Requirements by Area

#### Declaration

F035-DECL-01. The feature SHALL load a `domain.yaml` whose `name` equals its directory name, rejecting a mismatch, an unknown key, or an unknown integration pattern.
F035-DECL-02. The feature SHALL treat `exports` as the only tables another domain may reference and SHALL require each exported table to declare a primary key.
F035-DECL-03. The feature SHALL load an optional glossary (bare `term: {definition}` mapping or `terms:` wrapper) and expose term and alias lookup.

#### References

F035-REF-01. The feature SHALL add `references_domain` and `integration` to `ForeignKey`, populate the legacy `references_pipeline` from `references_domain` (and vice versa), reject disagreement, and force `cross_pipeline` for any cross-domain reference.
F035-REF-02. The feature SHALL forbid unknown keys on `ForeignKey` and SHALL add an optional `term` to tables and columns that round-trips through split format without changing `canonical_name`.

#### Validation

F035-VAL-01. The feature SHALL discover domains as the root and its direct child directories that contain `domain.yaml`, recording a table that fails to load as a finding rather than aborting.
F035-VAL-02. The feature SHALL report `DOM-EXPORT` when an export is not a table in the domain or lacks a primary key.
F035-VAL-03. The feature SHALL report `DOM-SUPPLIER` when a supplier is missing, is the domain itself, or a consumed table is not in the supplier's exports.
F035-VAL-04. The feature SHALL report `DOM-XREF` when a cross-domain foreign key targets a missing domain, a non-exported table, a non-primary-key column, or a supplier not declared by the consumer.
F035-VAL-05. The feature SHALL report `DOM-TERM` when a declared term is absent from the domain glossary, and SHALL report `DOM-DRIFT` as a warning (not an error) when two domains define the same term differently; `tablespec validate <root>` SHALL enter domain mode when the root is or directly contains domain directories, exiting non-zero only on errors.

#### Map

F035-MAP-01. The feature SHALL render `domains.html` in the guidebook output when domains exist, listing domains (owner, tables, exports), supplier edges with their pattern, and cross-domain references linking to the target table page, and SHALL link it from the top index; it SHALL write no such page otherwise.

### Non-Functional Requirements

- **Performance**: Domain discovery loads each UMF once per validate or guidebook run; no network access.
- **Security**: Reads YAML with `safe_load`; no code execution.
- **Scalability**: Rules are linear in the number of tables and foreign keys.
- **Reliability**: A malformed `domain.yaml` is skipped with a logged warning during discovery and surfaced as an error by `load_domain_dir`; unknown foreign-key keys fail at load time.

## User Stories

- US-051 — Declare and Validate Domains

## Edge Cases and Error Handling

- Nested domain directories are ignored below the first level.
- A qualified `references_table` (`eligibility.member`) counts as cross-domain by prefix without setting `references_domain`.
- A domain without a glossary skips `DOM-TERM`.
- `references_domain` and `references_pipeline` with different values is a model-level `ValidationError`.

## Success Metrics

- A clean two-domain corpus validates with zero findings; each single fault yields exactly one finding (see US-051 test scenarios).
- The checked-in UMF JSON schema equals the model schema (`test_umf_schema_json_sync.py`).

## Constraints and Assumptions

- Domains do not influence catalog or schema routing (ADR-013; concerns register "no hardcoded catalogs in emitted artifacts").
- The line-of-business `nullable` context keys and `context_column` are untouched; "domain" is the DDD unit precisely to avoid that word.
- `pipeline.yaml` and `DependencyResolver` are left in place; nothing new reads them.

## Dependencies

- **Other features**: FEAT-001 (UMF models), FEAT-033 (guidebook), FEAT-021 (validator).
- **External services**: None.
- **PRD requirements**: FR-24.1–FR-24.5.
- **Source Evidence**: `src/tablespec/models/domain.py`, `src/tablespec/domains.py`, `src/tablespec/domain_validator.py`, `src/tablespec/guidebook/domain_map.py`, `src/tablespec/validator.py` (`validate_domain_root`), `src/tablespec/cli.py` (`validate`).

## Out of Scope

- Domain-scoped `domain_type` registries.
- Compatibility report filtered to a domain's exports.
- Routing from `domain.yaml`.
- Excel round-trip of `term` and `integration`.

## Review Checklist

- [x] Every functional requirement carries a stable `F035-<AREA>-NN` ID
- [x] Surface (file keys, CLI behavior, rule IDs) is defined in the solution design SD-035, referenced here rather than restated
- [x] Story US-051 carries the acceptance criteria; tests cite them with `@covers`
- [x] Consistent with ADR-020 and PRD FR-24.1–FR-24.5
