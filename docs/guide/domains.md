# Domains

A **domain** is a directory of UMF tables with a `domain.yaml` at its root. It
gives that set of tables an owner, a list of tables other domains may
reference, the domains it consumes from, and a glossary. In Domain-Driven
Design terms the domain is the bounded context, `exports` is the published
language, `suppliers` is the context map, and the glossary is the ubiquitous
language. A column's `domain_type` is a value-object type scoped to its
domain.

The domain name is the directory name, the qualifier in `domain.table`
references, and the guidebook group. One name, one meaning.

## Layout

```
tables/
├── eligibility/
│   ├── domain.yaml
│   ├── glossary.yaml
│   └── member/            # split-format UMF
│       ├── table.yaml
│       └── columns/
└── claims/
    ├── domain.yaml
    ├── glossary.yaml
    └── medical_claims/
        ├── table.yaml
        └── columns/
```

Domains are the root and its direct children only. A `domain.yaml` deeper
down is ignored.

## domain.yaml

```yaml
name: claims                  # must equal the directory name
owner: claims-data-team
description: Adjudicated medical and pharmacy claims
exports:                      # tables other domains may reference
  - medical_claims            # each exported table must declare primary_key
glossary: glossary.yaml
suppliers:                    # domains this one consumes from
  eligibility:
    pattern: customer_supplier
    consumes: [member]        # must be in eligibility's exports
```

`pattern` is one of `partnership`, `shared_kernel`, `customer_supplier`,
`conformist`, `anti_corruption`, `open_host`, `separate_ways`. Only the
consumer declares the edge. Unknown keys are rejected.

## Glossary

```yaml
member:
  definition: A person enrolled in a plan for a coverage period
  aliases: [mbr, enrollee]
claim:
  definition: A billed encounter submitted for adjudication
```

Tables and columns point at terms with `term`:

```yaml
# claims/medical_claims/columns/mbr_id.yaml
column:
  name: mbr_id
  canonical_name: MBR ID      # still the source-spec label
  term: member                # resolved against claims/glossary.yaml
  data_type: VARCHAR
```

`term` and `canonical_name` are independent. The canonical name stays the
source header; the term says what the column means in this domain.

## Referencing another domain

```yaml
# claims/medical_claims/table.yaml (relationships section)
relationships:
  foreign_keys:
    - column: mbr_id
      references_table: member
      references_column: member_id
      references_domain: eligibility
      integration: customer_supplier
```

`references_domain` marks the key as cross-domain. The older
`references_pipeline` spelling still loads and is kept in sync. A qualified
`references_table: eligibility.member` is also treated as cross-domain.

## Validation

```bash
tablespec validate tables/
```

When the root is, or directly contains, `domain.yaml` directories, `validate`
checks each domain's tables as usual and then the cross-domain rules:

| Rule | Fires when |
|------|------------|
| `DOM-EXPORT` | an export is not a table in the domain, or has no `primary_key` |
| `DOM-SUPPLIER` | a supplier does not exist, or a consumed table is not in its exports |
| `DOM-XREF` | a cross-domain key targets a non-exported table, a non-primary-key column, or a supplier the consumer never declared |
| `DOM-TERM` | a `term` is not in the domain glossary |
| `DOM-DRIFT` | the same term is defined differently in two domains (warning only) |

Errors exit non-zero. `DOM-DRIFT` is a warning: two domains may legitimately
mean different things by one word, and the warning makes that a decision
rather than an accident.

From Python:

```python
from tablespec.domains import discover_domains
from tablespec.domain_validator import validate_domains

report = validate_domains(discover_domains("tables/"))
for finding in report.errors:
    print(finding)
```

## Domain map in the guidebook

```bash
tablespec guidebook tables/ -o out/guidebook
```

When domains exist the guidebook writes `domains.html`, linked from the top
index: each domain with its owner and exports, every supplier edge with its
pattern, and every cross-domain reference linking to the target table page.
The map uses **supplier** and **consumer**; the per-table lineage view keeps
**upstream** and **downstream** for value provenance.

## What domains do not do

- They do not choose a catalog or schema for emitted SQL, dbt, or Lakeflow
  artifacts. Placement stays with the emitter's routing policy.
- They do not rename anything. `canonical_name` is untouched.
- They do not replace the per-context nullability keys (`nullable: {MD: ...}`),
  which describe rows, not table sets.
