---
name: tablespec-umf-authoring
description: Authoring and editing Universal Metadata Format (UMF) table specs in split YAML format - creating table.yaml and per-column columns/*.yaml files, adding or modifying columns, relationships, nullability, domain types, and validation expectations, and converting between split, inline YAML, and JSON formats. Use when writing or editing UMF spec files by hand or via the tablespec CLI mutation commands (column-add, column-modify, domains-set, convert).
---

# UMF Authoring

Author UMF specs as split YAML directories. Treat JSON as the artifact and
interchange format, and inline whole-document YAML (`table.umf.yaml`) as
legacy/migration-only — never author new specs that way.

## Split Directory Layout

```text
tables/<table_name>/
  table.yaml            # table metadata + relationships
  expectations.yaml     # table-level / cross-column expectation suite
  columns/
    <column>.yaml       # one file per column
```

Gotchas the loader enforces:

- A split directory requires BOTH `table.yaml` and a `columns/` subdirectory.
  The loader rejects a directory missing either one.
- Relationships are embedded in `table.yaml`, NOT a separate
  `relationships.yaml` file.
- Column-specific expectations live in `columns/<column>.yaml` under a
  `validations:` key; table-level and cross-column expectations live in
  `expectations.yaml`.
- `UMFLoader.load()` does not auto-detect single-file `.yaml`/`.yml`/`.umf`
  documents. Migrate them explicitly with
  `UMFLoader().migrate_legacy_inline_yaml(source, dest)`.

## table.yaml Anatomy

```yaml
version: "1.0"
table_name: medical_claims
table_type: data_table   # data_table, lookup_table, or configuration
description: Healthcare claims and billing information
primary_key:
  - claim_id
relationships:
  foreign_keys:
    - column: provider_id
      references_table: providers
      references_column: provider_id
      confidence: 0.95
  referenced_by:
    - table: claim_lines
      column: claim_id
      foreign_key_column: claim_id
metadata:
  updated_at: 2025-01-15T10:30:00Z
  created_by: data-platform-team
```

Do not put columns or expectations in `table.yaml`; those live in `columns/`
and `expectations.yaml`.

## Column File Anatomy

Column attributes nest under a top-level `column:` key. Column-specific
expectations are a sibling `validations:` list, and derivations (for derived
tables) a sibling `derivation:` mapping — do not put fields at the file root.

```yaml
# columns/claim_amount.yaml
column:
  name: claim_amount
  data_type: DECIMAL
  precision: 10
  scale: 2
  description: Claim amount in USD
  domain_type: null
  nullable:
    MD: false   # Medicaid
    MP: true    # Medicare Part D
    ME: true    # Medicare
validations:
  - type: expect_column_values_to_be_between
    kwargs:
      column: claim_amount
      min_value: 0
```

Data type rules:

- Types: `VARCHAR`, `CHAR`, `TEXT`, `INTEGER`, `DECIMAL`, `FLOAT`, `DATE`,
  `DATETIME`, `BOOLEAN`.
- `VARCHAR` requires `length` (>= 1); `DECIMAL` requires `precision` and
  `scale`.
- `nullable` is either a plain boolean or a per-context struct. Context keys
  are arbitrary (MD/MP/ME are the common line-of-business ones); an omitted
  `nullable` means nullable everywhere.
- `domain_type` must name a registered domain type compatible with the
  column's `data_type` — the model validates both at load time.

## Naming Rules

Use lowercase_snake_case for table names and column names (validation flags
anything else). When renaming away from a legacy name, keep the old name in
`aliases` rather than losing it — `column-rename --keep-alias` does this.

## Editing via CLI

Prefer the CLI mutation commands over hand-editing for mechanical changes;
they load, mutate, and re-save the split directory with consistent formatting.

```bash
tablespec column-add tables/claims/ --name status_cd --type VARCHAR --length 10
tablespec column-modify tables/claims/ --name status_cd --type VARCHAR --length 20
tablespec column-rename tables/claims/ --from mbr_id --to member_id --keep-alias
tablespec column-remove tables/claims/ --name legacy_field
tablespec domains-set tables/claims/ --column state_cd --type us_state_code
```

`column-add` also accepts `--description` and `--nullable/--not-nullable`.
Discover domain types with `tablespec domains-list`, inspect one with
`tablespec domains-show us_state_code`, and get a suggestion with
`tablespec domains-infer --column state --description "State code abbreviation"`
(optionally `--samples "CA,NY,TX"`).

## Loading and Converting

```python
from tablespec import UMFLoader, UMFFormat

loader = UMFLoader()
umf = loader.load("tables/medical_claims/")   # auto-detects split dir or JSON
loader.convert("medical_claims.json", "tables/medical_claims/", target_format=UMFFormat.SPLIT)
```

`load_umf_from_yaml()` reads a single whole-document YAML file — use it only
for legacy inline UMFs, not split directories.

On the CLI, `tablespec convert` inverts the format by default: a split source
converts to JSON (artifact), and a JSON source converts to split (for
editing). Pass `--format split|json` to be explicit, `--force` to overwrite.

```bash
tablespec convert tables/medical_claims/ medical_claims.json   # split -> JSON
tablespec convert medical_claims.json tables/medical_claims/   # JSON -> split
tablespec batch-convert tables/ output/ --format split
```

## Verify Your Edit

Always validate after editing, whether by hand or CLI:

```bash
tablespec validate tables/medical_claims/   # single table or whole directory
tablespec info tables/medical_claims/       # schema summary
```

## Related

- Expectation lifecycle (baselines, validation-sync, apply-response, staged
  execution): see the `tablespec-validation` skill.
- Compiling UMFs into runtime artifacts and running pipelines: see the
  `tablespec-pipeline` skill.
- Full docs: `docs/guide/split-format.md` in this repository, and
  https://documentdrivendx.github.io/tablespec/
