# Guidebook

The guidebook generator renders a directory of UMFs into a navigable static
site — one page per table — so engineers and analysts can browse a schema, its
columns, and where every column's data ultimately comes from, without reading
YAML.

The site is plain HTML plus a small vanilla-JavaScript/CSS bundle in `assets/`
(no frameworks, no network requests), so it works opened from disk, served by a
plain static server, or hosted anywhere.

## What it renders

The left pane lists groups, a group's tables, or a table's columns (with a
filter and an "up one level" link); breadcrumbs show where you are; `/` or
Ctrl/⌘-K searches every table and column.

- **Table — Overview**: description, type, primary key, base table and
  strategy, final filter, source location and file format (for source tables),
  the tables it reads from and is used by, joins (foreign keys), and table-level
  rules.
- **Table — Sources**: every source table the table ultimately reads, with the
  columns it contributes and which columns they feed — as a list or a diagram.
- **Column — Details**: type, format, length, nullability, key, provenance, and
  sample values.
- **Column — Lineage**: the source tables the column ultimately comes from
  (traced through every intermediate generated table), with their location, and
  a path diagram; click a step to see how it is derived.
- **Column — Derivation**: each derivation candidate in priority order with its
  source, join/row filter, SQL expression, and reason, plus survivorship.
- **Column — Used by**: downstream columns that read this column; foreign-key
  consumers are marked `via fk` (a foreign key is an entity reference, so it is
  shown only downstream — ADR-018).
- **Column — Validation**: per-column expectations.

The URL hash keeps the selection (`orders.html#col=customer_name&tab=lineage`),
so links and the browser's back button work; old `#col-<name>` anchors still
open the column.

## Generate from the CLI

```bash
# Point it at a directory of UMFs
# (split table.yaml dirs, *.umf.json, and/or *.umf.yaml)
tablespec guidebook ./tables -o ./guidebook

# Then open ./guidebook/index.html, or serve it:
python -m http.server -d ./guidebook
```

Options:

- `--output` / `-o` — output directory (default `./guidebook`).
- `--group` / `-g` — render only one group (subfolder); leaves the home and group pages untouched.

## Trace lineage from the CLI

```bash
# Every column of a table (use group.table for tables in subfolders)
tablespec lineage ./tables member_quality_summary

# One column, as JSON
tablespec lineage ./tables member_quality_summary -c pcp_name -f json

# One table as a single self-contained HTML page
tablespec lineage ./tables member_quality_summary -f html -o mqs.html
```

Lineage is design-time: it follows the UMF derivations the SQL plan generator
compiles (base-table and union strategies, candidate priority, expression
references) and stops at tables whose `table_type` is not `generated`. Join keys
and filters are shown on each step but not followed.

## Generate from Python

```python
from pathlib import Path
from tablespec import generate_guidebook

written = generate_guidebook(root=Path("tables"), output_dir=Path("guidebook"))
print(f"Wrote {len(written)} files")

# Self-contained pages (CSS/JS inlined; no cross-page links or search), e.g.
# for embedding a single page in an iframe:
generate_guidebook(root=Path("tables"), output_dir=Path("embed"), self_contained=True)
```

The lineage engine is also usable directly:

```python
from tablespec.lineage import DiscoveredUMFProvider, LineageBuilder

graph = LineageBuilder(DiscoveredUMFProvider(Path("tables"))).trace_table("", "orders")
for leaf in graph.leaf_summaries["orders.customer_name"]:
    print(leaf.column_id, leaf.source_system)
```

## Discovery and layout

Discovery is **flat and recursive**. Three artifact shapes are found and
rendered:

- a split-format UMF (a directory containing `table.yaml`),
- a `*.umf.json` artifact,
- a `*.umf.yaml` artifact — the whole-document form the compile pipeline
  (`bootstrap_from_tables`) emits, so the guidebook renders that output directly.

When a table exists in more than one shape, candidate order is split → JSON →
YAML, so the richer format wins deterministically and the duplicate is skipped
with a warning.

A UMF's parent subfolder becomes its **group**:

- When UMFs live in subfolders, output nests as `<group>/<table>.html` and the
  home page lists each group.
- When every UMF sits at the root, output is flat and the home page lists all
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
raw tables plus a computed `member_quality_summary` report). It shows FK
consumers on the hub tables, and on the report each column's source tables,
derivation SQL, and survivorship. Regenerate
its guidebook with:

```bash
tablespec guidebook examples/synthea/umfs -o examples/synthea/guidebook
```
