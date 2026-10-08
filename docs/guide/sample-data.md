# Sample Data Generation

Generate realistic, constraint-aware sample data from UMF specifications. Supports healthcare-specific generators (SSN, NPI, drug codes), foreign key relationship graphs for referential integrity, and CSV/JSON output.

## Usage

```python
from tablespec import SampleDataGenerator, GenerationConfig

config = GenerationConfig(record_count=100, seed=42)
generator = SampleDataGenerator(
    input_dir="tables/",
    output_dir="sample_output/",
    config=config,
)
generator.generate()
# Produces CSV files in sample_output/ with realistic, relationship-aware data
```

## Domain packs and legal sample data

Healthcare remains the default. The legacy file generator accepts
`--domain legal` and `--root-entity-count` (`--num-members` remains an alias).
`GenerationConfig(domain="legal", root_entity_count=25)` selects the same pack
in Python. A `DomainPack` binds a generator factory and a matching
`DomainTypeRegistry` factory; `register_domain_pack(name, pack)` explicitly
registers application packs without replacing built-ins. No entry-point discovery
or global replacement of the healthcare inference registry occurs.

The legal pack fabricates organizations and fee-earners labeled Synthetic,
matters, billing, documents, and short fictional clauses. It provides the domain
types listed in `sample_data/legal.py`, including a small litigation UTBMS task
and activity subset. This is sample content, not legal advice or comprehensive
UTBMS coverage. The code subset follows the [ABA litigation code set](https://www.americanbar.org/groups/litigation/resources/uniform-task-based-management-system/litigation-code-set/). The bounded loader correlates referenced timekeeper levels/rates,
task codes/narratives, and matter open/close dates/time-entry dates regardless of
column order. The legacy file engine correlates fields within each row; use the
bounded loader path for correlations across parent tables.

## Unity Catalog loader

Review all generated DDL and counts locally first:

```bash
tablespec sample-data load --umf examples/legal/umf \
  --target sample_catalog.legal_demo --domain legal --scale demo --dry-run
```

Dry-run generates and verifies the full dataset locally. It does not construct
an SDK client, discover authentication, or issue SQL. JSON UMF files and split
UMF directories are supported. Invalid candidate UMF files fail the load rather
than silently dropping tables. External/cross-pipeline foreign keys are rejected.

For an explicitly authorized load, install `tablespec[databricks]` using the
project's package index, then supply an existing SDK authentication profile and
SQL warehouse identifier:

```bash
tablespec sample-data load --umf path/to/umf \
  --target sample_catalog.legal_demo --domain legal --scale demo \
  --warehouse-id "$WAREHOUSE_ID" --profile "$AUTH_PROFILE"
```

Tablespec accepts profile names, never credential arguments. The SDK resolves
authentication through its existing profile mechanism. No credentials are read
or persisted by tablespec code. Targets require an explicit `catalog.schema`;
every resulting table has a three-level name. Hive metastore targets, paths,
and arbitrary SQL identifiers are rejected. Schema creation is automatic; the
catalog must already exist. All tables use Delta and carry the complete UMF
table and column descriptions as comments.

`SQLSink.execute(statement)` is the injectable port. `WarehouseSQLSink` waits for
statement completion, propagates unsuccessful states, and cancels on timeout.
`SparkSQLSink(existing_session)` executes the same SQL on a caller-supplied
session, including Spark Connect. The CLI also accepts `--backend spark`,
which uses the repository's single Spark-session factory (the active session
on Databricks). Warehouse/profile arguments are required for warehouse loading.
Unit tests use a fake port and never connect to a workspace.

### Replacement and failure behavior

Generation and verification complete in a temporary local SQLite spool before
any sink mutation. Each table loads into a uniquely named staging Delta table
in bounded INSERT batches. A completed staging table is published with
`INSERT OVERWRITE`, preserving the target table and replacing its rows.
Repeated runs with the same specs, scale, seed, and generator version produce
the same dataset, without appending duplicate batches. Tablespec does not retry
ambiguous INSERT calls; it aborts and a complete rerun uses a fresh staging table.

A failed staging batch leaves that target's rows untouched. Staging tables are
removed in `finally`; process termination or loss of connectivity can leave a
staging table requiring operator cleanup. Publication is atomic per table,
not across the dataset. Failure after some tables publish can leave mixed run
versions; rerun the complete load to converge. Do not run concurrent loads into
the same target. Comments are refreshed after publication and are not part of
the data transaction. Existing incompatible table schemas cause SQL failure;
review migrations separately or explicitly use `--drop-existing` to recreate
the named target tables. That option drops only those targets after staging
succeeds; it never drops the schema or unrelated tables.

### Scale configuration and memory

`sample_data/scales.yaml` defines root counts and child means along parent
edges. `small` totals 232 rows across the example's eight tables. `demo`
produces 25 clients, 150 matters, 40 timekeepers, 100,000 time entries, 5,000
invoices, 20,000 documents, plus teams and walls. `large` produces three million
time entries. Parent count overrides propagate to children; explicit child
count overrides take precedence. Repeat `--table-count matters=20` as needed.
Unrecognized root tables use `--root-entity-count` (alias `--num-members`).

Copy the preset structure into a project configuration and pass
`--scale-config path/to/scales.yaml` to customize roots, parent edges, and
`per_parent` means. Counts equal the rounded parent count times the mean;
FK assignments produce a configurable child-count distribution across parents.
Each child edge can specify `distribution: uniform` or `distribution: skewed`
(default). Skewed assignment sends 80% of references to the first 20% of parent
rows; adjust that probability with `--hot-key-ratio`. The remaining references
sample all parents. The Python `plan_counts` API also accepts edge overrides.

Parent rows, generated rows, and uniqueness indexes stay on disk. SQLite's
page cache is limited to approximately 4 MiB. Python holds one generation row
and bounded read/write batches, not a dataset-sized key pool. Temporary local
disk capacity must accommodate the dataset and indexes. `--batch-size` defaults
to 500; the loader also caps each SQL statement at 1,000,000 bytes and rejects
an individually oversized row before publication.

### Verification boundary

The generation report includes table row counts, FK orphan counts, null
violations, and uniqueness violations. A successful run requires zero
violations. The bounded path enforces UMF primary/unique keys, non-nullability,
string lengths, decimal precision/scale, and supported GX expectations for
non-null, uniqueness, value sets, ranges, regex, and type. Generic values use
value-set/range constraints; conflicting legal semantics fail rather than being
silently overwritten. Other expectation types and unsupported generated types
fail explicitly. It does not claim arbitrary GX-suite satisfaction.

See [the legal example](https://github.com/DocumentDrivenDX/tablespec/tree/main/examples/legal)
for the minimal eight-table UMF set. Praxis owns its production example specs;
tablespec owns reusable generators and loading behavior.

Local verification on 2026-10-08 (Python 3.12, macOS): the eight-table large
example generated 3,000,000 time entries and 516,650 related rows in 68.48 seconds.
Peak process RSS grew from 285,884,416 to 292,077,568 bytes; the SQLite spool
occupied 1,551,482,880 bytes. This measures generation, not warehouse throughput.
