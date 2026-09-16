---
title: CLI Reference
weight: 3
next: /api-reference
---

This page is for readers who want command names, inputs, outputs, and exit
codes. The `tablespec` command line interface (CLI) has 22 commands. Run
`tablespec --help` for the live list, or `tablespec COMMAND --help` for one
command's options.

```
tablespec [OPTIONS] COMMAND [ARGS]...
```

Most commands take a Universal Metadata Format (UMF) **split directory** or a
UMF **JSON file** as input. A split directory contains `table.yaml` plus one
file per column under `columns/`. Legacy single-file YAML specs are refused.
Exit code is 0 on success, 1 on validation or command failure, and 2 on usage
errors.

## Inspect and validate

### `validate`

Validate a UMF spec for structure, model correctness, relationships,
expectation compatibility, and pipeline completeness.

```bash
tablespec validate tables/
tablespec validate medical_claims.json -v
```

Checks JSON-schema conformance, Pydantic model structure, filename pattern
correctness, column naming (lowercase_snake_case), Great Expectations rule
compatibility, relationship integrity (when multiple tables are present), and
pipeline completeness — provenance columns, domain types, and baseline
expectations.

| Option | Description |
|--------|-------------|
| `--verbose`, `-v` | Show detailed validation errors. |

### `info`

Display table name, description, version, and a column table.

```bash
tablespec info tables/medical_claims/
```

### `preview`

Preview generated validation expectations classified by stage (`raw` source
records vs. typed `ingested` tables), with severity and source for each. See the
[validation model](/concepts/validation/) for what the stages mean.

```bash
tablespec preview tables/medical_claims/
```

### `explore`

Launch an interactive TUI: browse tables and columns in a tree view, search
across loaded UMFs, edit descriptions and types inline. Requires the `tui`
extra (`tablespec[tui]`); without it the command exits with an install hint.

```bash
tablespec explore tables/
```

## Generate and emit

### `generate`

Generate one artifact from a UMF spec: SQL DDL, PySpark schema source, JSON
Schema, or an ingest SQL plan. Output goes to stdout so it can be piped.

```bash
tablespec generate tables/medical_claims/ -f sql > medical_claims.ddl.sql
tablespec generate tables/medical_claims/ -f pyspark > schema.py
tablespec generate tables/medical_claims/ -f json > schema.json
tablespec generate tables/medical_claims/ -f ingest > medical_claims.ingest.sql
```

| Option | Description |
|--------|-------------|
| `--format`, `-f` | Required. `sql`, `pyspark`, `json`, or `ingest`. |

The `ingest` format emits the raw-to-ingested SQL artifact for
Databricks/Delta: raw landing DDL, typed target DDL, and the `MERGE`
transform.

### `emit`

Emit a runnable project for one UMF spec or a set of related UMF specs.

```bash
tablespec emit tables/ out/dbt --backend dbt --dialect databricks
```

| Option | Description |
|--------|-------------|
| `--backend`, `-b` | Emission backend. Currently `dbt` (default). |
| `--project-name` | dbt project and profile name. |
| `--dialect` | Cast dialect: `duckdb` (default), `spark`, or `databricks` (the Databricks-facing alias for Spark-family cast SQL). |
| `--run` | After emitting, run `dbt build` via dbt-duckdb. |

`--run` targets a DuckDB database at `<out_dir>/tablespec.duckdb`; the raw
landing table (`raw_<table>`) must exist there for the build to pass.

### `guidebook`

Render a directory of UMF specs into a static HTML guidebook.

```bash
tablespec guidebook tables/ -o out/guidebook
tablespec guidebook tables/ -o out/guidebook --group clinical
```

| Option | Description |
|--------|-------------|
| `--output`, `-o` | Output directory for generated HTML (default `guidebook`). |
| `--group`, `-g` | Render only one discovered group/subfolder. Indexes are left unchanged in single-group mode. |

The command discovers split `table.yaml` directories and `.umf.json` files
recursively. It writes one self-contained page per table, group and top-level
indexes, and `search_index.json`.

## Convert formats

### `convert`

Convert a single UMF spec between split-directory and JSON formats. The
direction is auto-detected from the input and output paths.

```bash
tablespec convert tables/medical_claims/ medical_claims.json
tablespec convert medical_claims.json tables/medical_claims/
```

| Option | Description |
|--------|-------------|
| `--format`, `-f` | Target format: `split` or `json` (auto-detected if omitted). |
| `--force` | Overwrite existing destination. |

### `batch-convert`

Convert every UMF in a directory.

```bash
tablespec batch-convert tables/ json_out/ --format json
```

| Option | Description |
|--------|-------------|
| `--format`, `-f` | Required. Target format: `split` or `json`. |
| `--pattern`, `-p` | File pattern to match (default `*.umf.yaml`). |
| `--force` | Overwrite existing files. |

### `export-excel` / `import-excel`

Round-trip a spec through an Excel workbook for review by people who do not
edit YAML. The workbook carries data-validation dropdowns, helper columns,
instructions, and a machine-readable `Derivations` sheet; import validates
before converting back to split format.

```bash
tablespec export-excel tables/medical_claims/ medical_claims.xlsx --force
tablespec import-excel medical_claims.xlsx tables/medical_claims/ --force
```

## Edit columns

All four commands accept a split directory or JSON file path.

```bash
tablespec column-add tables/medical_claims/ --name status_cd --type VARCHAR --length 10
tablespec column-modify tables/medical_claims/ --name status_cd --length 20
tablespec column-rename tables/medical_claims/ --from status_cd --to claim_status_cd --keep-alias
tablespec column-remove tables/medical_claims/ --name claim_status_cd
```

| Command | Key options |
|---------|-------------|
| `column-add` | `--name`, `--type` (required); `--description`, `--nullable/--not-nullable`, `--length` |
| `column-modify` | `--name` (required); `--type`, `--description`, `--length` |
| `column-rename` | `--from`, `--to` (required); `--keep-alias` records the old name in `aliases` |
| `column-remove` | `--name` (required) |

## Domain types

Domain types attach semantic meaning to columns. Examples include member IDs,
state codes, National Provider Identifiers (NPIs), and email addresses.
tablespec uses domain types for detection, validation, and sample-data
generation.

```bash
tablespec domains-list
tablespec domains-show us_state_code
tablespec domains-infer --column member_id
tablespec domains-set tables/medical_claims/ --column member_id --type member_id
```

| Command | Description |
|---------|-------------|
| `domains-list` | List registered domain types (`--format text\|json`). |
| `domains-show` | Show a domain's full definition: detection rules, validation spec, sample generation (`--format yaml\|json`). |
| `domains-infer` | Infer the domain type for a column from `--column`, optional `--description` and `--samples`, with a confidence score. |
| `domains-set` | Assign a domain type to a column (validated against the registry). |

## Manage expectations

### `validation-sync`

Regenerate deterministic baseline expectations from the current UMF spec and
reconcile them with the existing Great Expectations suite. User customizations
are preserved.

```bash
tablespec validation-sync tables/medical_claims/ --dry-run
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would change without writing. |
| `--clean-outdated` | Remove outdated baseline expectations. |
| `--aggressive` | Upgrade unmarked expectations to baseline. |

### `validation-remove`

Remove expectations matching a type, optionally scoped to a column.

```bash
tablespec validation-remove tables/medical_claims/ --type expect_column_values_to_be_unique
```

| Option | Description |
|--------|-------------|
| `--type`, `-t` | Required. Expectation type to remove. |
| `--column`, `-c` | Column name; removes all matching if omitted. |

### `apply-response`

Apply LLM-generated validation expectations to a UMF table. The input is a
JSON list or an object shaped like `{"expectations": [...]}`. This command
pairs with the prompt generators in the Python API.

```bash
tablespec apply-response tables/medical_claims/ response.json --dry-run
tablespec apply-response tables/medical_claims/ response.json
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would be applied without modifying the UMF. |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Validation error or command failure |
| 2 | Usage error (bad arguments or flags) |
