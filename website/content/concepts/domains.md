---
title: Domains and the context map
weight: 5
---

This page is for readers who own one set of tables and consume another team's.
It defines the boundary tablespec draws between teams: a **domain** is a
directory of UMF specs with a `domain.yaml`, and that file says who owns the
tables, which tables other domains may reference, which domains this one
depends on, and what its words mean.

The vocabulary comes from Domain-Driven Design (DDD). tablespec uses the
strategic half of DDD, the part about boundaries between models, and leaves
the tactical half (repositories, services, factories) to application code.

## The file

```yaml
# claims/domain.yaml
name: claims                  # equals the directory name
owner: claims-data-team
version: 1.0.0                # version of the published language
exports: [medical_claims]     # tables other domains may reference
glossary: glossary.yaml
suppliers:
  eligibility:
    pattern: customer_supplier
    consumes: [member]
    version: ">=1.0.0,<2.0.0"
```

`tablespec validate tables/` checks every domain's tables, then the rules
between domains. `tablespec guidebook tables/` renders `domains.html`.

## What each DDD term is in tablespec

| DDD term | In tablespec | Where |
|---|---|---|
| Bounded context | A domain: one directory, one `domain.yaml`, one name that is also the guidebook group and the `domain.table` qualifier | `domain.yaml` → `name` |
| Ubiquitous language | The domain glossary, and `term` on a table or column that points into it | `glossary.yaml`; `term:` in `table.yaml` and `columns/*.yaml` |
| Published language | The exported tables: the only ones another domain may reference. Each must declare a primary key | `domain.yaml` → `exports` |
| Aggregate root | An exported table. A cross-domain foreign key may target only its primary-key column | `exports` + `primary_key` |
| Context map | The supplier edges each consumer declares, with a DDD integration pattern | `domain.yaml` → `suppliers` |
| Customer-supplier, conformist, anti-corruption layer, shared kernel, partnership, open host, separate ways | The `pattern` on a supplier edge. Advisory and rendered on the map; only `separate_ways` is enforced (it may not consume anything) | `suppliers.<d>.pattern` |
| Value object | A `domain_type`: a typed, validated, formatted value such as a state code or an NPI, scoped to the domain's vocabulary | `columns/*.yaml` → `domain_type` |
| Entity | A table with a declared primary key | `table.yaml` → `primary_key` |

## Rules `validate` enforces between domains

| Rule | Fires when |
|---|---|
| `DOM-EXPORT` | an export is not a table in the domain, or has no primary key |
| `DOM-SUPPLIER` | a supplier does not exist, or a consumed table is not in its exports |
| `DOM-XREF` | a cross-domain foreign key targets a non-exported table, a non-primary-key column, or a supplier the consumer never declared |
| `DOM-WAYS` | a `separate_ways` edge consumes a table or is crossed by a foreign key |
| `DOM-PIN` | the supplier's `version` does not satisfy the consumer's range |
| `DOM-TERM` | a `term` is not in the domain glossary |
| `DOM-COMPAT` | with `--baseline`, an exported table changed in a breaking way without a MAJOR bump of `version` |
| `DOM-VERSION` | warning: a domain exports tables but declares no `version` |
| `DOM-DRIFT` | warning: the same term is defined differently in two domains |

The published language is the export list plus each exported table's columns,
types, nullability, and primary key. Glossary terms, expectations, and
non-exported tables are not part of it, so changing them never requires a
version bump.

## What domains do not do

- They do not choose a catalog or schema for emitted SQL, dbt, or Lakeflow
  artifacts. Placement stays with the emitter's routing policy.
- They do not rename anything. `canonical_name` stays the source-spec label.
- They do not replace the per-context nullability keys (`nullable: {MD: ...}`),
  which describe rows, not sets of tables.

## Sources

Primary DDD sources, in the order to read them:

- Eric Evans, *Domain-Driven Design* (2003), part IV, for bounded context,
  context map, and the integration patterns as first defined.
- Vaughn Vernon, *Implementing Domain-Driven Design* (2013), chapters 2 and
  3, for the clearest treatment of published language and the difference
  between customer-supplier and conformist.
- Martin Fowler, [BoundedContext](https://martinfowler.com/bliki/BoundedContext.html)
  and [UbiquitousLanguage](https://martinfowler.com/bliki/UbiquitousLanguage.html),
  short definitions for readers new to the terms.
- Alberto Brandolini, context mapping and
  [EventStorming](https://www.eventstorming.com/), the workshops that produce a
  `domain.yaml` and a glossary in the first place.

Adjacent ideas that are not DDD but map onto the same files:

- Zhamak Dehghani, *Data Mesh* (2022): domain ownership is the `owner` field;
  data as a product is `exports` plus a validation suite; federated
  computational governance is the `DOM-*` rules.
- Matthew Skelton and Manuel Pais, *Team Topologies* (2019): a
  stream-aligned team owning a domain is the organizational assumption
  behind `owner`.
- The [Open Data Contract Standard](https://bitol-io.github.io/open-data-contract-standard/):
  a domain's exports with their schema, expectations, owner, and version is a
  data contract in this sense. tablespec does not emit that format today.
