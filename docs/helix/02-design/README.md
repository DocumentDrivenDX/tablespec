# Phase 2: Design

Architecture and design decisions for tablespec.

## Project-Level Artifacts

- [Architecture](architecture.md) - System architecture

## Architecture Decision Records

- [ADR-001: DATE Type Maps to StringType (YYYYMMDD Strings)](adr/ADR-001-date-as-yyyymmdd-string.md) - DATE columns are stored as YYYYMMDD strings in PySpark/GX, not native date types, reflecting healthcare data conventions.
- [ADR-002: Only GX 1.6+ Format Is Supported](adr/ADR-002-gx-16-format-only.md) - Legacy Great Expectations format is explicitly rejected; only the modern 1.6+ format with `name`/`type` fields is accepted.
- [ADR-003: PySpark Is an Optional Dependency](adr/ADR-003-optional-pyspark-dependency.md) - PySpark is isolated to `profiling/spark_mapper.py` and `validation/table_validator.py`, installable via `tablespec[spark]`.
- [ADR-008: dbt Adoption Architecture](adr/ADR-008-dbt-adoption-architecture.md) - Per-subsystem dbt-candidate map, the `tablespec.core`/`tablespec.dbt` encapsulation seam, the optional-`[dbt]` opt-in mechanism, and a value-to-effort adoption roadmap.

## Status

Design phase backfilled from existing codebase and documentation (2026-03-15).
