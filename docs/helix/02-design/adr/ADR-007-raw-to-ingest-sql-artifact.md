---
ddx:
  id: ADR-007
---

# ADR-007: Raw-to-Ingest Transforms as Committed SQL Artifacts

## Status

Accepted — default path for all pipelines going forward. Generalized by
ADR-015 (2026-06-10): the all-STRING raw landing below is the
**delimited-text variant** of the kind-dependent source-shape contract;
typed sources (parquet, JDBC) land native-typed raw with
identity/safe-narrowing casts.

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

This decision also makes the bronze boundary explicit. Raw storage preserves source
bytes/records for audit and replay. The generated raw->ingest artifact preserves source
semantics in a typed, validated, platform-native representation; it is still source-preserving
because it does not perform cross-source conformance, survivorship, entity resolution, or
business enrichment. It deliberately does not preserve avoidable source accidents such as
flat-file string typing or dump-format quirks.

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
- **Negative / follow-up:** `cast_column_sql` covers the common cast paths
  (`cast_column_with_format`). The runtime caster has not yet been refactored to consume
  `cast_column_sql` — until it is, the two are kept in parity by tests.
  - **epoch-ms + Excel-serial — DONE.** `cast_column_sql` now emits the two numeric
    date/time encodings the runtime supported but the SQL seam previously could not: the
    explicit `EPOCH_MS` and `EXCEL_SERIAL` UMF format sentinels render epoch-ms→timestamp
    (gated on the same 12+-digit / scientific detection as
    `cast_timestamp_with_epoch_fallback`) and Excel-serial→date (the `1899-12-30 + N days`
    arithmetic of `convert_excel_serial_to_date`). Both are emitted for the `spark` and
    `duckdb` dialects and are proven byte-identical to the runtime PySpark caster by
    `tests/unit/test_cast_column_edge_format_parity.py` (runtime caster == spark-dialect SQL
    == duckdb-dialect SQL, plus a Sail/Connect lane). The sentinels are EXPLICIT opt-in (never
    inferred from a value), so a 4–6 digit numeric ID is never mis-read as an Excel serial; the
    Excel int-cast uses `try_cast` so dirty rows NULL on strict backends (Connect/Sail) too.
    Parity scope is precise: clean ISO date/timestamp values, ALL detected-epoch (12+-digit
    / scientific) values, and ALL Excel-serial values are byte-identical across the runtime
    caster, spark-dialect SQL, and duckdb-dialect SQL. The one residual divergence is the
    default-parse ELSE branch of an EPOCH_MS column on *dirty, engine-lenient* strings (e.g.
    a bare time-only `"15:06:40"` or whitespace-padded date): Spark `try_to_timestamp` parses
    these (today-relative) while DuckDB `try_cast(... as timestamp)` NULLs them. This is
    inherited parser leniency on non-epoch dirty rows, documented on
    `casting_utils._epoch_ms_cast_sql`, not the epoch/Excel arithmetic. The flexible-format
    coalesce caster remains a follow-up.
  - **Snapshot "latest file" filtering — DESCOPED (not needed).** No consumer requests
    input-file / file-modification "latest file" selection and no UMF field declares it; the
    snapshot mode already drops/reloads via `INSERT OVERWRITE` and incremental dedup-latest
    handles per-key recency. Building file-level latest filtering would add a speculative,
    unconsumed seam, so it is intentionally NOT implemented.
- **Type fidelity:** the typed target DDL uses Spark-correct types (e.g. `DATETIME ->
  TIMESTAMP`), unlike `generate_sql_ddl` which emits a literal `DATETIME`.

## Related

- ADR-002 (GX 1.6 format), ADR-005 (unified expectation model — Bronze.Raw/Ingested stages).
- `src/tablespec/schemas/ingest_generator.py`, `src/tablespec/casting_utils.py`.
