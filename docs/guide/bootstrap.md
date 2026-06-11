# Bootstrap from Spark Tables

Use the public bootstrap facade when you already have an existing Spark table
and want the full compiled artifact tree in one call.

This is a development/bootstrap step. It produces the committed artifact tree
that production will later install and run from via the manifest; production
does not re-run the bootstrap orchestration from source checkout code.

The bootstrap path is tablespec's practical definition of done for ingested
bronze. Raw source records remain auditable upstream; the compiled artifact tree
captures the source table's semantics as typed columns, validation criteria,
relationships, aliases, keys, raw-to-ingest SQL, validation suites, and manifest
entries. Silver-layer work such as cross-source conformance, survivorship, entity
resolution, enrichment, and dimensional modeling remains downstream.

```python
from tablespec import bootstrap_from_tables

artifacts = bootstrap_from_tables(
    spark,
    ["member"],
    out_dir="/tmp/tablespec-bootstrap",
    profile=True,
    dialect="databricks",
)

print(artifacts.manifest_path)
print(artifacts.table("member").suite_json)
```

What the facade does:

- reflects each table schema into UMF
- when `profile=True`, profiles the table data natively and turns the profile
  into GX validation expectations
- compiles and persists the UMF snapshot, validation suite, dbt projects, LDP
  project, and manifest

The profiler enriches validation. It does not create UMF. Schema reflection does
that first step, and the facade handles the compile step for you.

Databricks-facing compile UX accepts `dialect="databricks"` for the Spark-family
SQL this facade emits. Internal emitters may normalize to `spark` when the
rendered SQL is identical.

The returned `CompiledArtifacts` manifest is the production handoff: it points to
the compiled `manifest.json`, the JSON pipeline artifacts (`validation/*.suite.json`
and friends), and the rest of the pinned tree that a production job installs and
loads from disk.

When you only want the schema-only baseline suite, pass `profile=False`.
