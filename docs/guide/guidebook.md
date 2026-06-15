# Guidebook

The guidebook generator renders a directory of UMFs into a navigable,
self-contained HTML site — one page per table — so engineers and analysts can
browse a schema, its columns, and its lineage without reading YAML.

Each page is self-contained (inline CSS, no JS frameworks, no network requests),
so the output works opened from disk, served by a plain static server, or hosted
anywhere.

## What it renders

- **Per-column metadata** — data type, length, format, description, sample values.
- **Foreign-key lineage** — a referenced (hub) table lists every downstream
  table/column that points at it (`via fk`).
- **Derivation lineage** — a derived column shows its **upstream sources**, the
  **SQL expression** for each derivation candidate (with priority + join-filter
  for multi-candidate columns), and **survivorship** logic; the source columns
  show the derived column as a downstream consumer (`via derivation`).
- **Validation rules** — per-column expectations pulled from the UMF.
- **Indexes + search** — a top-level index (grouped by subfolder when present,
  flat otherwise) and a JSON search index covering every table and column.

## Generate from the CLI

```bash
# Point it at a directory of UMFs (split table.yaml dirs and/or *.umf.json)
tablespec guidebook ./tables -o ./guidebook

# Then open ./guidebook/index.html, or serve it:
python -m http.server -d ./guidebook
```

Options:

- `--output` / `-o` — output directory (default `./guidebook`).
- `--group` / `-g` — render only one group (subfolder); leaves indexes untouched.

## Generate from Python

```python
from pathlib import Path
from tablespec import generate_guidebook

written = generate_guidebook(root=Path("tables"), output_dir=Path("guidebook"))
print(f"Wrote {len(written)} files")
```

## Discovery and layout

Discovery is **flat and recursive**: every split-format UMF (a directory with a
`table.yaml`) and every `*.umf.json` under the root is found and rendered. A
UMF's parent subfolder becomes its **group**:

- When UMFs live in subfolders, output nests as `<group>/<table>.html` and the
  top index lists each group.
- When every UMF sits at the root, output is flat and the top index lists all
  tables directly.

Duplicate `(group, table)` pairs would collide on the same output file; the
first wins and later duplicates are logged and skipped. A UMF that fails to load
is logged and skipped without aborting the run.

Cross-table references resolve by group: a bare `candidate.table` (or FK
`references_table`) resolves within the current group, while a qualified
`group.table` reference links across groups.

## Guidebook a Databricks catalog (two-step)

The guidebook consumes UMFs on disk, so first generate UMFs from the catalog,
then render them:

```python
from pathlib import Path
from tablespec import bootstrap_from_tables, generate_guidebook

# 1. Reflect catalog tables into UMFs (writes the artifact tree, incl. UMFs)
bootstrap_from_tables(spark, ["member", "claims"], "/tmp/catalog-umfs", profile=True)

# 2. Render the guidebook over the generated UMFs
generate_guidebook(root=Path("/tmp/catalog-umfs"), output_dir=Path("guidebook"))
```

`JdbcToUmfMapper` / `SparkToUmfMapper` (in `tablespec[spark]`) are the
lower-level entry points if you want to control UMF generation directly before
rendering.

## Worked example

`examples/synthea/` is a runnable demo over the Synthea synthetic EHR schema (10
raw tables plus a computed `member_quality_summary` report). It shows FK lineage
on the hub tables and derivation / SQL / survivorship on the report. Regenerate
its guidebook with:

```bash
tablespec guidebook examples/synthea/umfs -o examples/synthea/guidebook
```
