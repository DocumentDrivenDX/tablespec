---
ddx:
  id: SD-035
---

# Solution Design

**Feature**: FEAT-035 - Domains | **Artifact**: `docs/helix/02-design/domains-solution-design.md`

## Scope

- Feature-level design and the governing Contract for the domain surface:
  the `domain.yaml` file, the glossary file, the new `ForeignKey` and
  `term` fields, the validation rule IDs, the `tablespec validate` domain
  mode, and the guidebook `domains.html` page.
- Governing artifacts: FEAT-035, ADR-020, PRD FR-24.1–FR-24.5, US-051.
- Does not change `tablespec.core`, any emitter, or routing (ADR-013).

## Requirements Mapping

### Functional Requirements

| Requirement | Technical Capability | Component | Priority |
|------------|----------------------|-----------|----------|
| FR-24.1 domain declaration | Parse and validate `domain.yaml` and its glossary | `models/domain.py` | P1 |
| FR-24.2 cross-domain reference fields | `references_domain`, `integration`, legacy reconciliation, `extra="forbid"` | `models/umf.py` (`ForeignKey`) | P1 |
| FR-24.3 cross-domain validation | Discovery plus rules `DOM-*`; `validate` domain mode | `domains.py`, `domain_validator.py`, `validator.py`, `cli.py` | P1 |
| FR-24.4 domain map | Render `domains.html`; link from top index | `guidebook/domain_map.py`, `guidebook/generator.py`, `guidebook/index_renderer.py` | P1 |
| FR-24.5 glossary terms | `term` on `UMF` and `UMFColumn`; split-format persistence | `models/umf.py`, `umf_loader.py` | P1 |

## Solution Approaches

| Approach | Chosen | Why |
|----------|--------|-----|
| One `domain.yaml` per directory; validation reads all domains under a root | Yes | One name for the unit; rules need a multi-directory view the per-table validator lacks |
| Extend `pipeline.yaml` | No | Dead model, wrong word (ADR-020) |
| New CLI command for domain validation | No | `validate <root>` already means "validate this directory"; domain mode is detected from `domain.yaml`, so the command count and docs surface do not grow |

## Domain Model

### `domain.yaml` (Contract)

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `name` | `^[a-z][a-z0-9_]*$` | yes | Must equal the directory name; the qualifier in `domain.table` |
| `description` | string | no | What the domain is about |
| `owner` | string | no | Accountable team or person |
| `version` | `^\d+\.\d+\.\d+$` | no | Version of the published language; MAJOR must bump on a breaking change (ADR-021). `DOM-VERSION` warns when exports exist without it |
| `exports` | list of table names | no (default `[]`) | Tables other domains may reference; each must have `primary_key` |
| `glossary` | relative path | no | Glossary YAML |
| `suppliers` | map of domain name to `{pattern, consumes}` | no (default `{}`) | Context-map edges this domain consumes |
| `suppliers.<d>.pattern` | one of `partnership`, `shared_kernel`, `customer_supplier`, `conformist`, `anti_corruption`, `open_host`, `separate_ways` | yes | DDD integration pattern. Advisory (the consumer's assertion, rendered on the map); only `separate_ways` is enforced |
| `suppliers.<d>.consumes` | list of table names | no (default `[]`) | Must be in the supplier's `exports`; must be empty for `separate_ways` |
| `suppliers.<d>.version` | range: comma-separated clauses of `>=`, `<=`, `==`, `!=`, `>`, `<` + `MAJOR.MINOR.PATCH` (e.g. `>=1.0.0,<2.0.0`) | no | Accepted supplier versions; checked by `DOM-PIN`. Not PEP 440, not a full SemVer range language |

Unknown keys are rejected.

### Glossary file (Contract)

Either a bare mapping `term: {definition, aliases?}` or the same under a
top-level `terms:` key. Lookup is case-insensitive over keys and aliases.

### `ForeignKey` additions (Contract)

| Key | Type | Meaning |
|-----|------|---------|
| `references_domain` | string | Owning domain of the target when not this domain |
| `integration` | integration pattern | Advisory pattern for this edge |
| `references_pipeline` | string | Legacy alias of `references_domain`. Populated from `references_domain` on load; a key that sets only this spelling is left as authored. Disagreement is an error |
| `cross_pipeline` | bool | Forced `true` when `references_domain` is set; untouched for legacy-only keys |

Read model: `target_domain` = `references_domain`, else `references_pipeline`,
else the prefix of a qualified `references_table`. Upgrade guarantee: a spec
that does not use `references_domain` loads, saves, and compiles byte-for-byte
as before, except that an unknown key on a foreign key is now an error.

`ForeignKey` now forbids unknown keys.

### `term` (Contract)

`UMF.term` and `UMFColumn.term` are optional strings resolved against the
owning domain's glossary. `canonical_name` is unchanged.

### Validation rule IDs (Contract)

| Rule | Severity | Fires when |
|------|----------|------------|
| `DOM-LOAD` | error | A table inside a domain failed to load |
| `DOM-EXPORT` | error | An export is not a table, or has no `primary_key` |
| `DOM-SUPPLIER` | error | Supplier missing, self-supplier, or consumed table not exported |
| `DOM-XREF` | error | Cross-domain FK to a missing domain, non-exported table, non-PK column, or undeclared supplier |
| `DOM-TERM` | error | A `term` is absent from the domain glossary |
| `DOM-WAYS` | error | A `separate_ways` edge has a `consumes` list, or a cross-domain FK crosses a `separate_ways` edge |
| `DOM-PIN` | error | Supplier's `version` does not satisfy the consumer's range, or the supplier declares no version while the consumer pins one |
| `DOM-COMPAT` | error | Baseline mode: a breaking published-language change without a MAJOR bump, or with a missing version on either side |
| `DOM-VERSION` | warning | A domain exports tables but declares no `version` |
| `DOM-DRIFT` | warning | One term defined differently in two domains |

Message shape: `[RULE] <domain>/<entity>: <message>`.

### Published language (Contract)

Boundary: the export list, plus for each exported table the column set,
column types, nullability, and primary key (what `check_compatibility`
compares). Not included: glossary terms, expectations, relationships,
non-exported tables.

Change classification between a baseline root and the current root, domains
paired by name, export lists compared as a union:

| Change | Severity |
|--------|----------|
| `domain_removed` (old domain with exports absent in new) | breaking |
| `export_removed` | breaking |
| `table_removed` (still exported, table gone) | breaking |
| `export_added` | info |
| compatibility issue on a table exported on both sides | as classified by `check_compatibility`, except `added_required` (forward-only) → warning |

Output line shape: `[<severity>] <domain>/<component>: <description>`.
Nothing is persisted; the changelog is not written.

### CLI (Contract)

`tablespec validate <root>` enters domain mode when `<root>` is, or directly
contains, a directory with `domain.yaml`. It validates each domain's tables as
today, prints `Domain errors:` and `Domain warnings:` blocks, exits 1 on any
table or domain error, and otherwise prints `Valid <n> domains, <m> tables`.

`--baseline <dir>` (domain mode only; must be a directory) adds a
`Published-language changes:` block before the errors and enables
`DOM-COMPAT`. No new command is added.

### Glossary surfaces (Contract)

`render_table_page(..., glossary: Glossary | None = None)`: each cited term is
a `<span class="chip chip-term" title="<definition>">term: <term></span>`;
the column section adds `<p class="term-definition"><strong><term></strong>:
<definition></p>`. Without a glossary the chip renders with no title and no
definition line. `generate_documentation_prompt(umf_data, *, glossary=None)`
accepts a `Glossary` or a `{term: definition}` mapping and adds a
`## Domain Glossary` section listing only cited terms, sorted by canonical
key; absent glossary or no cited terms leaves the prompt unchanged.

### Guidebook (Contract)

`domains.html` is written to the output root when domains exist, with sections
Domains, Supplier edges, Cross-domain references. The top index links to it.
Direction words are supplier and consumer.

## System Decomposition

| Component | Responsibility | Imports |
|-----------|----------------|---------|
| `models/domain.py` | Pydantic models, `load_domain`, `load_glossary` | pydantic, yaml |
| `domains.py` | `find_domain_dirs`, `load_domain_dir`, `discover_domains`, `LoadedDomain` | models, `umf_loader` |
| `domain_validator.py` | Pure rule functions and `validate_domains` | `domains`, models |
| `validator.py` | `is_domain_root`, `validate_domain_root` | the above plus `validate_pipeline` |
| `cli.py` | Domain-mode branch of `validate` | `validator` |
| `guidebook/domain_map.py` | `render_domain_map` | `domains`, `index_renderer` |

`tablespec.core`, `tablespec.dbt`, and `tablespec.ldp` import none of these;
`models/domain.py` is importable from them if a later feature needs it.

## Technology Rationale

- Pydantic with `extra="forbid"` for every new model so a typo fails at load.
- Plain dataclasses for findings so the validator stays free of I/O.
- No new CLI command: detection from `domain.yaml` keeps the documented
  command count stable.

## Traceability

| Artifact | Reference |
|----------|-----------|
| Feature | FEAT-035 |
| Decisions | ADR-020, ADR-021 |
| Stories | US-051 (AC1–AC5), US-052 (AC1–AC5) |
| Tests | `tests/unit/test_domain_models.py`, `tests/unit/test_domain_validator.py`, `tests/unit/test_domain_versioning.py`, `tests/unit/test_glossary_surfaces.py`, `tests/unit/test_cli_validate_domains.py`, `tests/unit/test_guidebook_domain_map.py`, `tests/unit/test_umf_schema_json_sync.py` |
| Guide | `docs/guide/domains.md`; microsite `concepts/domains` |
