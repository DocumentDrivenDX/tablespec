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
(default). Skewed assignment uses the power-law parameter described below; uniform assignment
samples all eligible parents equally. The Python `plan_counts` API also accepts
edge overrides.

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

Historical verification of commit 6b72759 on 2026-10-08 (Python 3.12, macOS): the eight-table large
example generated 3,000,000 time entries and 516,650 related rows in 68.48 seconds.
Peak process RSS grew from 285,884,416 to 292,077,568 bytes; the SQLite spool
occupied 1,551,482,880 bytes. This measures generation, not warehouse throughput.

### Legal tabular fixtures and entitlement checks

The legal pack generates relational tables and tabular ground truth. Ontology
modeling belongs in truss and ashlar and is outside tablespec's sample-data scope.
The bounded loader recognizes the example table/column names to coordinate
staffing; custom names require a domain planner rather than implicit inference.

Teams and walls are generated before entries. Both tables enforce unique
`(matter_id, timekeeper_id)` pairs. Team and wall sets are disjoint; entries draw
only from their matter's team. Every matter has a partner and a non-partner member,
at least one entry, and every client has a matter. Walls reference available,
synthetic timekeepers excluded from the team. Impossible count overrides fail
before any target writes. Preset row counts are unchanged, including 150 demo
walls (the former duplicate pairs reduced their distinct count to 125).

`--skew-exponent` defaults to 0.8 (range 0–0.95). For parent rank r, weights are
proportional to the integral of x^-exponent over [r,r+1). This truncated power law
is sampled without retaining a dataset-sized weight array; zero is uniform.
Coverage rows come first. Staff selection uses rank^-exponent among eligible
members; one in four entries uses a partner, avoiding small-scale partner
monopolies. The legacy `--hot-key-ratio` remains accepted for compatibility but
does not control this bounded generator. Legal coverage and staffing rules also
apply when a configured edge requests uniform sampling.

Organizations and invented person names are labeled Synthetic. UTBMS codes are
an illustrative litigation L100–L500 and transactional P-series **subset**;
this is not the complete UTBMS taxonomy. The project codes follow the
[UTBMS 2007 project set](https://utbms.com/wp-content/uploads/2023/07/UTBMS-Project-Billing-Codes-2007-Rev.pdf). Narratives vary by task, activity,
section and revision; 15% are block billed and 3% deliberately vague. Both flags
are ground truth. `hours` ranges from 0.1 to 8.0; `amount` equals hours times the
referenced timekeeper's rate. Document bodies use type-specific short clauses.
`nda_issues` is an optional ground-truth column: empty, `long_term`, `residuals`,
or `missing_governing_law`. Approximately 8% of NDAs contain one seeded issue;
other document types never receive NDA issue labels.

Matter durations use a triangular distribution with a 180-day mode and default
30–1095-day bounds, adjustable with `--matter-duration-min-days` and
`--matter-duration-max-days`. The mode is clamped to configured bounds. Fifteen
percent of matters remain open when `close_date` permits null; entries in open
matters stop at the deterministic reference date. Strict range limits,
one-to-one FK uniqueness, and final matter date correlations are enforced.

Invoices add `client_id`, `invoice_date`, `period_start`, `period_end`, and
`total_amount`. These are **sample billing windows**, not a partition into issued
bills: windows can overlap and can contain no entries. Each total is the exact
integer-cent sum of that matter's entry amounts inside its inclusive window.
Future issue dates have draft status; paid status requires an issue date no later
than the reference date, and overdue requires more than 30 days since issue.

### Bulk loading and read-back verification

The default remains bounded INSERT VALUES for small/demo. Explicit `--bulk`
requires `--backend warehouse` and `--volume /Volumes/catalog/schema/volume/path`:

```bash
tablespec sample-data load --umf examples/legal/umf --domain legal --scale large \
  --target sample_catalog.legal_demo --warehouse-id "$WAREHOUSE_ID" \
  --profile "$AUTH_PROFILE" --bulk \
  --volume /Volumes/sample_catalog/legal_demo/sample_files/staging
```

The volume must already exist and be writable by the profile. Tablespec writes
bounded UTF-8 CSV chunks locally, uploads them through the SDK Files API into an
invocation-owned folder, then issues one COPY INTO per table with explicit type
casts, multiline CSV parsing and a null marker. It uses the same staging and
per-table atomic overwrite as INSERT loading. Uploaded files are removed on
success or failure; empty owned directories can remain. No DBFS path is used.
Bulk transports remain injectable for offline tests. Implementation follows the
[Files API](https://databricks-sdk-py.readthedocs.io/en/stable/workspace/files/files.html)
and [COPY INTO](https://docs.databricks.com/aws/en/sql/language-manual/delta-copy-into)
interfaces; no live bulk throughput claim is made.

After either loading path, the CLI reads row counts, FK orphan counts, and all
legal entitlement/coverage checks through the same sink and prints PASSED or
fails the run. `--verify-only` performs those checks against existing targets,
using the same UMF directory, scale and table overrides, without generation or
writes. It cannot combine with dry-run, bulk or drop-existing. The dry-run keeps
its JSON-report/DDL/count shape and includes the local legal verification results.
Verification is an audit after publication, not a cross-table transaction.

Local follow-up verification (Python 3.12, macOS, seed 42) generated the unchanged
large preset with all ten relational audits at zero in 146.23 seconds. Peak RSS
increased from 284,917,760 to 295,845,888 bytes; spool size was 2,210,091,008 bytes.
This measures generation and local audits, not live warehouse throughput.

| Seed 42 metric | Small before → after | Demo before → after |
|---|---|---|
| Off-team entries | 25 → 0 | 40,329 → 0 |
| Walled entries | 110 → 0 | 23,527 → 0 |
| Team/wall pair overlap | 2 → 0 | 68 → 0 |
| Duplicate team pairs | 13 → 0 | 231 → 0 |
| Duplicate wall pairs | 4 → 0 | 25 → 0 |
| Matter top-1 entry share | 81.48% → 32.59% | 2.869% → 8.553% |
| Matter Gini | 0.723 → 0.260 | 0.646 → 0.485 |
| Timekeeper top-1 entry share | 88.89% → 35.56% | 10.642% → 16.237% |
| Timekeeper Gini | 0.646 → 0.139 | 0.645 → 0.581 |

Before metrics count represented keys; coverage now guarantees every matter.
Small samples have mild staff skew because required roles constrain participation.
Tests check seeds 7, 42 and 101 at small/demo: top-1 below 50%/25%, Gini above
0.04/0.3 and below 0.85. Every generated run independently audits the invariants;
these measured shape bounds qualify the tested seeds, not arbitrary overrides.

Bulk CSV string fields use a reversible leading `~` transport prefix, removed by
the COPY projection. This preserves empty strings separately from the `\N` null
marker, including text beginning with that marker or prefix; multiline body text
round-trips unchanged. The optional SDK minimum is 0.47.0, verified to provide
volume-directory creation in addition to file upload/delete.
