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

The directory that holds domain directories is a domain root, and the domains
in it are each other's siblings. A `domain.yaml` nested inside another domain
directory is ignored, so the `domain.table` qualifier stays one segment.

## domain.yaml

```yaml
name: claims                  # must equal the directory name
owner: claims-data-team
description: Adjudicated medical and pharmacy claims
version: 1.0.0                # version of the published language
exports:                      # tables other domains may reference
  - medical_claims            # each exported table must declare primary_key
glossary: glossary.yaml
suppliers:                    # domains this one consumes from
  eligibility:
    pattern: customer_supplier
    consumes: [member]        # must be in eligibility's exports
    version: ">=1.0.0,<2.0.0" # accepted supplier versions
```

`pattern` is one of `partnership`, `shared_kernel`, `customer_supplier`,
`conformist`, `anti_corruption`, `open_host`, `separate_ways`. Only the
consumer declares the edge, so the pattern is the consumer's assertion: it is
shown on the domain map and not enforced, with one exception. `separate_ways`
means no integration, so it may not consume anything and no foreign key may
cross it. Unknown keys are rejected.

## Versioning the published language

`version` is `MAJOR.MINOR.PATCH`. It versions the published language: the
export list plus, for each exported table, its columns, types, nullability,
and primary key. Glossary terms, expectations, and non-exported tables are not
part of it, so changing them never needs a bump.

A consumer pins the versions it accepts on the supplier edge. The range is a
comma-separated list of clauses using `>=`, `<=`, `==`, `!=`, `>`, `<`.
`DOM-PIN` fails when the supplier's version is outside the range or the
supplier declares none. A domain that exports without a version gets a
`DOM-VERSION` warning.

To check a change before it lands, validate against the previous revision:

```bash
tablespec validate tables/ --baseline tables-at-last-release/
```

The run prints every published-language change. Removing an export or an
exported table is breaking. Removing or narrowing a column is breaking, as the
compatibility checker already classifies it. Adding a nullable column is
informational; adding a required column is a warning because it constrains
producers, not existing consumers. A breaking change without a MAJOR bump is
`DOM-COMPAT` and fails the run. After the bump, every consumer whose range
excludes the new major fails `DOM-PIN` until it widens the range. That is the
point: the supplier signals, and each consumer accepts explicitly.

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

Terms are shown, not only checked. A guidebook table page renders each cited
term as a chip whose tooltip and inline line carry the definition, aliases
resolved to the canonical entry. The documentation prompt accepts the glossary
and lists only the terms the table and its columns cite:

```python
from tablespec.prompts.documentation import generate_documentation_prompt
from tablespec.domains import load_domain_dir

domain = load_domain_dir("tables/claims")
prompt = generate_documentation_prompt(
    domain.tables["medical_claims"].model_dump(exclude_none=True),
    glossary=domain.glossary,
)
```

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
`references_pipeline` spelling still loads, is read the same way, and is never
rewritten, so existing specs save unchanged. A qualified
`references_table: eligibility.member` is also treated as cross-domain.

## Validation

```bash
tablespec validate tables/
```

`validate` has one behavior. It finds every table under the path, at any
depth, and validates each. When a `domain.yaml` applies to the path, it also
checks the rules below. "Applies" means the path is a domain, is inside one,
or has domains beneath it.

A domain's suppliers live next to it, not beneath it, so `validate` always
loads the sibling domains from the directory that holds them. Validating one
domain, or one table, still checks its references into the others:

```bash
tablespec validate tables/                        # every domain
tablespec validate tables/claims/                 # one domain, siblings resolved
tablespec validate tables/claims/medical_claims/  # one table, its cross-domain keys
```

Findings are limited to what the path covers. A problem in `eligibility` is
reported when you validate `eligibility` or the root, not when you validate
`claims`; `claims` sees only the consequence for its own keys.

| Rule | Fires when |
|------|------------|
| `DOM-EXPORT` | an export is not a table in the domain, or has no `primary_key` |
| `DOM-SUPPLIER` | a supplier does not exist, or a consumed table is not in its exports |
| `DOM-XREF` | a cross-domain key targets a non-exported table, a non-primary-key column, or a supplier the consumer never declared |
| `DOM-WAYS` | a `separate_ways` edge consumes a table or is crossed by a foreign key |
| `DOM-PIN` | the supplier's `version` is outside the consumer's range, or the supplier has none |
| `DOM-TERM` | a `term` is not in the domain glossary |
| `DOM-COMPAT` | with `--baseline`, an exported table changed in a breaking way without a MAJOR bump |
| `DOM-VERSION` | a domain exports tables but declares no `version` (warning only) |
| `DOM-DRIFT` | the same term is defined differently in two domains (warning only) |

Errors exit non-zero. `DOM-DRIFT` is a warning: two domains may legitimately
mean different things by one word, and the warning makes that a decision
rather than an accident.

## Mapping to Domain-Driven Design

tablespec uses the strategic half of DDD, the part about boundaries between
models. Each term below names the file or field that embodies it.

| DDD term | In tablespec |
|---|---|
| Bounded context | a domain: `domain.yaml` → `name` |
| Ubiquitous language | the glossary, and `term` on tables and columns |
| Published language | `exports` plus `version` |
| Aggregate root | an exported table; only its primary key may be referenced |
| Context map and its integration patterns | `suppliers.<d>.pattern`, advisory except `separate_ways` |
| Value object | `domain_type` on a column |
| Entity | a table with `primary_key` |

Primary sources: Evans, *Domain-Driven Design* (2003), part IV; Vernon,
*Implementing Domain-Driven Design* (2013), chapters 2 and 3; Fowler's
[BoundedContext](https://martinfowler.com/bliki/BoundedContext.html) and
[UbiquitousLanguage](https://martinfowler.com/bliki/UbiquitousLanguage.html);
Brandolini's [EventStorming](https://www.eventstorming.com/) as the workshop
that produces a `domain.yaml`. Adjacent ideas that map onto the same files but
are not DDD: Dehghani, *Data Mesh* (2022), for domain ownership and data as a
product; Skelton and Pais, *Team Topologies* (2019), for the team behind
`owner`; the [Open Data Contract Standard](https://bitol-io.github.io/open-data-contract-standard/)
for what a domain's exports amount to. Tactical DDD (repositories, services,
factories, the Specification pattern) is not part of tablespec's vocabulary.

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
