# ADR-007: Raw-to-Ingest Transforms as Committed SQL Artifacts

## Status

Accepted — default path for all pipelines going forward.

## Context

The Bronze.Raw -> Bronze.Ingested transform (type casting, format-aware date/timestamp
parsing, currency/empty-string normalization, dedup, and the write into the typed table)
has historically been expressed as **PySpark Column-API logic** in `casting_utils.py`,
applied row-by-row by a downstream orchestrator (pulseflow's Phase 8 `TypeConverter`) and
mirrored by Great Expectations validation (`ExpectColumnValuesToCastToType`).

This couples every pipeline to:

- a Python/PySpark runtime (the library must be installed and importable on the cluster),
- the Column-API capability-probing path (Spark classic vs Connect differences), and
- a transform that is **not reviewable or runnable on its own** — you cannot read a diff of
  "what the ingest step does" without reading Python.

For Databricks pipelines (Git folders + notebooks, DBR 17.x / Spark 4.0) the ingest step is
naturally pure SQL. We already commit generated SQL for Gold tables (`SQLPlanGenerator`);
the raw->ingest step should be no different.

## Decision

**The canonical raw->ingest transform is a committed, generated SQL artifact**, produced from
the UMF spec and run independently of this library. Python's role is to *generate* the
artifact, not to wrap it at runtime.

- `casting_utils.cast_column_sql()` is the canonical cast expression (plain Spark SQL). It
  shares `convert_umf_format_to_spark()` with the runtime caster `cast_column_with_format()`,
  so date/timestamp formats are guaranteed identical.
- `schemas/ingest_generator.generate_ingest_sql(umf)` emits the full artifact
  (Databricks/Delta dialect): a `raw_<table>` landing table (all `STRING` + ingest metadata),
  a typed `ingested_<table>` target table, and a cast + write transform that branches on
  `ingestion.mode` and `primary_key`:
    - incremental + primary_key  -> dedup-latest then `MERGE` (upsert)
    - incremental, no primary_key -> blind `INSERT INTO` (with a warning comment)
    - snapshot                    -> `INSERT OVERWRITE` (drop/reload)
- Surfaced as `tablespec generate <umf> -f ingest` and exported from the public API
  (`tablespec.generate_ingest_sql`).
- Golden tests under `tests/golden/ingest_sql/` make every change to the transform a
  reviewable diff against checked-in `.expected.sql`.

### Going forward

1. **All pipelines** generate and commit the raw->ingest `.sql` artifact (like Gold), and the
   warehouse runs the SQL. No `pip install tablespec[spark]` on the cluster for ingest.
2. **pulseflow's `TypeConverter`** is migrated to execute the generated SQL (against a temp
   view / Delta table) instead of applying Column-API casts.
3. **Single source of truth** is preserved: the runtime caster and GX validation converge on
   `cast_column_sql` (e.g. via `selectExpr`), so "validation tests exactly what ingestion
   does" continues to hold — now with the additional guarantee that the committed SQL is
   exactly what runs.

## Consequences

- **Positive:** ingest logic is reviewable and independently runnable; no library runtime on
  the cluster; one canonical cast; diff-based review via golden files; Databricks-native.
- **Negative / follow-up:** `cast_column_sql` currently covers the common cast paths
  (`cast_column_with_format`); the richer fallback casters (flexible-format coalesce,
  epoch-ms, Excel-serial) and snapshot "latest file" filtering are follow-ups. The runtime
  caster has not yet been refactored to consume `cast_column_sql` — until it is, the two are
  kept in parity by tests.
- **Type fidelity:** the typed target DDL uses Spark-correct types (e.g. `DATETIME ->
  TIMESTAMP`), unlike `generate_sql_ddl` which emits a literal `DATETIME`.

## Related

- ADR-002 (GX 1.6 format), ADR-005 (unified expectation model — Bronze.Raw/Ingested stages).
- `src/tablespec/schemas/ingest_generator.py`, `src/tablespec/casting_utils.py`.
