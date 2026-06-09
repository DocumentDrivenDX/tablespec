---
ddx:
  id: prd
  kind: product
---

# Product Requirements Document: tablespec

**Version**: 3.0
**Status**: Evolved to govern committed-artifact compilation and Connect-safe multi-engine execution
**Last Updated**: 2026-06-06

## Summary

tablespec is a Python library that makes Universal Metadata Format (UMF) the single source of truth for table schemas on healthcare data platforms, and acts as the compiler that turns one UMF into the full set of committed, reviewable runtime artifacts — direct SQL (raw→ingest + gold plans), dbt projects (ingest + gold DAG), Lakeflow Declarative Pipelines (LDP), and Great Expectations suites. Downstream runtimes consume only those committed artifacts (never re-deriving from UMF at run time), and the same UMF runs first-class on both classic Spark and Databricks serverless / Spark Connect. Top success metrics: zero drift between UMF and committed artifacts, multi-engine result parity on the conformance harness, and reduced manual transform/validation authoring per onboarded table.

## Problem and Goals

### Problem

Healthcare data platforms work with table schemas across many tools and formats (SQL DDL, PySpark, JSON Schema, Great Expectations, dbt, LDP). Without a single authoritative schema format and a deterministic compile step, definitions drift between tools, validation rules diverge, transforms are not diffable, and onboarding a table requires redundant manual work in each system. Compounding this, the JVM-bound runtime assumptions of legacy tooling (PyDeequ profiling, GX `add_spark`) silently break on Databricks serverless / Spark Connect, where no classic `SparkContext` exists.

### Goals

1. Establish UMF as the single source of truth for table schema definitions.
2. Compile one UMF deterministically into the full set of committed runtime artifacts (direct SQL, dbt projects, LDP, GX suites), with the runtime consuming only those artifacts.
3. Run the same UMF first-class on both classic Spark and Databricks serverless / Spark Connect, with engine-correct dispatch and Connect-safe validation.
4. Profile data with a native, dependency-light Spark-SQL profiler that works on serverless / Connect and feeds GX expectations directly.
5. Keep schema generation, transforms, and baseline validation deterministic and lossless so committed artifacts are reviewable as diffs.

### Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| UMF→artifact drift | Zero | Recompile + diff committed artifacts against UMF in CI |
| Compile coverage | Full artifact set emitted per UMF | `tablespec.e2e.compile` manifest completeness check |
| Multi-engine parity | Identical results across classic Spark / Sail / Databricks serverless | Cross-engine conformance harness (`tests/conformance/`) |
| Runtime independence | No tablespec import at run time | Backbone executes committed artifacts only (`tablespec.e2e.backbone`) |
| Manual-authoring reduction | Reduced transform/validation authoring time per table | Time-to-onboard tracking |

### Non-Goals

- Database connectivity or interactive query execution as a product surface (the runtime executes committed artifacts; tablespec does not become an ETL engine).
- GUI or web interface.
- Real-time schema synchronization (compile is an explicit step, not a live watcher).
- Shipping dbt or pysail as user-facing runtime dependencies (they are dev-group / test-only tooling).

Deferred items are tracked in DDx beads. Use `ddx bead ready --json` for
execution-ready work and `ddx bead status --json` for tracker health.

## Users and Scope

### Primary Persona: Data Engineer

**Role**: Builds and maintains ETL pipelines with PySpark, SQL, dbt, and LDP.
**Goals**: Onboard tables from one UMF; review transforms as diffs; run the same definition on classic Spark and serverless.
**Pain Points**: Per-tool schemas and transforms drift; runtime code that works locally fails silently on Spark Connect / serverless.

### Secondary Persona: Data Quality Engineer

**Role**: Creates and manages Great Expectations validation suites.
**Goals**: Generate baseline + profiling + AI expectations from UMF; run them correctly on both classic Spark and Connect.
**Pain Points**: GX `add_spark` silently returns false negatives on Connect; suites diverge from schema truth.

### Tertiary Persona: Platform Team

**Role**: Standardizes schema definitions across Medicaid (MD), Medicare Part D (MP), and Medicare (ME) lines of business.
**Goals**: One authoritative format; diffable transforms; zero drift across tools and engines.

## Requirements

Each requirement traces to the Product Vision and is specific enough to drive feature specs, designs, tests, and implementation without embedding detailed design here.

### Must Have (P0)

1. UMF as single source of truth with type-safe models and I/O.
2. Deterministic compile of one UMF to the full committed artifact set, consumed only as artifacts at run time.
3. Native, Connect-safe Spark profiling feeding GX expectations.
4. Connect-safe validation execution on both classic Spark and Spark Connect / serverless.
5. Multi-target emission (direct SQL, dbt, LDP) on a shared target-agnostic core seam.

### Should Have (P1)

1. Cross-engine conformance parity across classic Spark, Sail, and Databricks serverless.
2. CLI and Excel/split-format workflows for domain-expert collaboration.

### Nice to Have (P2)

1. Expanded sample-data, quality-baseline, and domain-type-inference coverage.

## Functional Requirements

Functional requirements are grouped under canonical `### Subsystem:` headings.
Each `FR-n` carries a stable ID and belongs to exactly one subsystem. IDs survive
edits; do not renumber on edit.

### Subsystem: UMF Model and I/O

**FR-1** requirement family.

- **FR-1.1** — Pydantic models for UMF format with runtime validation
- **FR-1.2** — Support 10 data types: VARCHAR, CHAR, TEXT, INTEGER, DECIMAL, FLOAT, DATE, DATETIME, TIMESTAMP, BOOLEAN
- **FR-1.3** — Per-LOB nullable configuration (MD, MP, ME)
- **FR-1.4** — Validation rules at table and column level
- **FR-1.5** — Foreign key relationships with confidence scoring
- **FR-1.6** — Index definitions
- **FR-1.7** — YAML serialization/deserialization with Pydantic validation
- **FR-1.8** — Column name validation (alphanumeric + underscore, max 128 chars)
- **FR-1.9** — Unique column name enforcement
- **FR-1.10** — UMF metadata with pipeline phase tracking (1-7)

### Subsystem: Schema Generation

**FR-2** requirement family.

- **FR-2.1** — SQL DDL generation with NOT NULL, column comments, table comments, and suggested indexes
- **FR-2.2** — PySpark StructType code generation with correct type imports
- **FR-2.3** — JSON Schema (draft-07) generation with type mapping, maxLength, and examples

### Subsystem: Type Mappings

**FR-3** requirement family.

- **FR-3.1** — UMF to PySpark type mapping (all types plus BIGINT, SMALLINT, TINYINT, DOUBLE, STRING, TIMESTAMP)
- **FR-3.2** — UMF to JSON Schema type mapping
- **FR-3.3** — UMF to Great Expectations Spark type mapping
- **FR-3.4** — Case-insensitive type resolution
- **FR-3.5** — Safe defaults (unknown types map to StringType/string)

### Subsystem: Great Expectations Integration

**FR-4** requirement family.

- **FR-4.1** — Baseline expectation generation from UMF metadata (column existence, types, nullability, length, date format)
- **FR-4.2** — Structural expectations (column count, column order)
- **FR-4.3** — Expectation suite composition (baseline + profiling + AI-generated)
- **FR-4.4** — Constraint extraction from existing GX suites (value sets, regex patterns, strftime formats)
- **FR-4.5** — GX schema validation against JSON schema and GX library
- **FR-4.6** — Expectation suite processing with baseline merging and deduplication
- **FR-4.7** — Support for GX 1.6+ format (not legacy)

### Subsystem: Profiling Integration

**FR-5** requirement family.

- **FR-5.1** — **Native Spark-SQL profiler (default).** Profile a DataFrame using only standard Spark SQL aggregations (min, max, avg, stddev, approx_count_distinct, percentile_approx, skewness, kurtosis), with no JVM and no Deequ, so profiling runs on Databricks serverless / Spark Connect. Engine-correct `functions` dispatch is selected from the DataFrame's own engine, not a process-global flag.
- **FR-5.2** — **Profile → GX expectations.** `ProfileToGxMapper` builds GX expectations directly from a native profile at a configurable strictness, feeding suite composition (FR-4.3).
- **FR-5.3** — Profiling metadata (tool, version, timestamp, sample size).
- **FR-5.4** — Nullable inference from completeness metrics.
- **FR-5.5** — **Deequ mapper removed; no Deequ on Connect/serverless.** The PyDeequ-based `DeequToUmfMapper` (`profiling/deequ_mapper.py`) has been **removed** (commit `ad5a4d9`); it assumed a classic `SparkContext` and may not be assumed available on Connect/serverless. The Spark-schema `SparkToUmfMapper` (schema → UMF) is retained and is Connect-safe (it reflects the DataFrame *schema*, not data), but it is a schema mapper, not the profiling mechanism — the native profiler (FR-5.1) is the default for data profiling.

### Subsystem: LLM Prompt Generation

**FR-6** requirement family.

- **FR-6.1** — Documentation enrichment prompts
- **FR-6.2** — Table-level validation rule prompts (multi-column expectations)
- **FR-6.3** — Column-level validation rule prompts (single-column expectations)
- **FR-6.4** — Foreign key relationship discovery prompts with cardinality estimation
- **FR-6.5** — Data survivorship mapping prompts
- **FR-6.6** — Prompt hash tracking for deduplication
- **FR-6.7** — Healthcare domain knowledge in prompts (member/provider/claim IDs, drug codes)

### Subsystem: Table Validation

**FR-7** requirement family.

- **FR-7.1** — DataFrame validation against UMF specifications (requires PySpark).
- **FR-7.2** — Schema validation (missing/extra columns).
- **FR-7.3** — Data type validation.
- **FR-7.4** — LOB-specific nullable validation.
- **FR-7.5** — Business rule validation (uniqueness, format, value constraints).
- **FR-7.6** — Structured validation error output with VALIDATION_ERROR_SCHEMA.
- **FR-7.7** — **Connect-safe suite execution with per-expectation routing.** Execute a compiled GX suite in a single batch pass; route each expectation by DataFrame engine — Connect DataFrames to a native DataFrame-API executor, classic Spark to GX `add_spark` unchanged. This is required because GX 1.x `add_spark` / `SparkDFExecutionEngine` asserts an active `SparkContext` that does not exist on Connect, so data-scanning expectations otherwise silently return `success=False`/`result={}`.
- **FR-7.8** — **Staged raw/ingested execution.** A compiled suite co-mingles raw (string) and ingested (typed) expectations; the executor stages them against the correct DataFrame (raw vs. typed) at execute time.

### Subsystem: Compile Orchestration & Bootstrap

**FR-18** requirement family.

- **FR-18.1** — **Compile orchestrator.** A single orchestrator (`tablespec.e2e.compile`) takes a list of UMF models and drives every compile seam, persisting one committed artifact each: ingest SQL, DDL, PySpark schema, JSON schema, compiled GX suite, single-table dbt ingest project, multi-table gold dbt DAG project, LDP project, and the single-target gold SQL plan. *Governed by FEAT-026; decision recorded in ADR-012.*
- **FR-18.2** — **Pinned manifest layout.** Compiled artifacts are written under a pinned layout and described by a `CompiledArtifacts` manifest that the runtime can resolve deterministically.
- **FR-18.3** — **Runtime consumes only committed artifacts.** The runtime backbone (`tablespec.e2e.backbone`) executes the committed artifacts and must not re-derive schema/transforms from UMF or import tablespec at run time. *Governed by FEAT-026 (US-024); decision recorded in ADR-012.*
- **FR-18.4** — **Path-agnostic bootstrap (Path A / Path B).** Two bootstrap entry points produce the UMF list the compiler consumes — Path A (inferred from sample tables, `scripts/bootstrap_from_tables.py`) and Path B (loaded from existing specs, `scripts/bootstrap_from_specs.py`); compile is path-agnostic.
- **FR-18.5** — **Bootstrap test matrix.** The bootstrap pipeline is exercised across the DuckDB / Spark / Sail engine matrix.

### Subsystem: Multi-Target Emission

**FR-19** requirement family.

- **FR-19.1** — **Shared target-agnostic core seam.** Direct-SQL, dbt, and LDP emitters are siblings on a framework-agnostic core (`tablespec.core` — the renderer Protocol + logical-plan IR); no emitter imports another, and importing the core never requires dbt/LDP runtime packages.
- **FR-19.2** — **dbt emitter.** Emit a single-table ingest project and a multi-table gold dbt DAG project, including model contracts from schema facts, relationships + accepted_values schema tests, `state:modified` CI selection from UMF diff, and sample-data → dbt seeds.
- **FR-19.3** — **LDP sibling emitter.** Emit an LDP (Lakeflow Declarative Pipelines) project as a committed artifact and as a conformance engine tier, proving the target-agnostic core seam with a second backend.
- **FR-19.4** — **Raw→ingest committed SQL.** Emit the canonical raw→ingest transform as committed generated SQL (raw DDL + typed DDL + transform); Python generates the artifact, it does not wrap the transform at run time.

### Subsystem: Runtime Platform

**FR-20** requirement family.

- **FR-20.1** — **Per-session capability probing.** Detect per-session Spark capabilities that vary across builds (e.g. `try_to_timestamp` with a format on classic Spark 4.0 vs. some Connect builds) by probing a tiny expression, cached per session.
- **FR-20.2** — **Engine-correct functions dispatch.** Select the `functions` module / Column engine from the DataFrame in hand, never from a process-global `is_remote()`, so expressions stay session-correct when classic and Connect sessions coexist (the local Sail test lane) and behave identically in production.
- **FR-20.3** — **First-class serverless / Connect target.** Databricks serverless / Spark Connect (env-v3, Python 3.12) and classic Spark are both first-class execution targets; no decision may assume a JVM `SparkContext`.
- **FR-20.4** — **Connect-safe validation path.** Validation routing (FR-7.7) is the Runtime-Platform contract applied to GX execution.

### Subsystem: CLI Interface

**FR-8** requirement family.

- **FR-8.1** — Typer-based CLI (`tablespec` command) with Rich output formatting
- **FR-8.2** — `convert` command for format conversion (JSON, split, Excel)
- **FR-8.3** — `validate` command for UMF validation with pipeline context
- **FR-8.4** — `info` command for schema summary display
- **FR-8.5** — `batch-convert` command for directory-wide format conversion
- **FR-8.6** — `generate` command for SQL DDL, PySpark schema, JSON Schema, and ingest SQL output (note: `generate` emits only sql/pyspark/json/ingest; the full committed artifact set is produced by the compile orchestrator, FR-18.1)

### Subsystem: Excel Bidirectional Conversion

**FR-9** requirement family.

- **FR-9.1** — UMF to Excel export with data validation dropdowns and formatting
- **FR-9.2** — Excel to UMF import with strict validation
- **FR-9.3** — Helper columns (validation status, error messages) for domain experts
- **FR-9.4** — Round-trip fidelity between Excel and UMF formats

### Subsystem: Split-Format UMF

**FR-10** requirement family.

- **FR-10.1** — Directory-based UMF storage (`table.yaml` + `columns/*.yaml`)
- **FR-10.2** — `UMFLoader` with automatic format detection (split vs JSON)
- **FR-10.3** — Bidirectional conversion between split and JSON formats
- **FR-10.4** — Git-friendly structure for per-column change tracking

### Subsystem: Schema Change Management

**FR-11** requirement family.

- **FR-11.1** — UMF diffing (`UMFDiff`) detecting column, validation, metadata, and relationship changes
- **FR-11.2** — Atomic change application (`UMFChangeApplier`) for per-change commits
- **FR-11.3** — Git-based changelog generation from commit history
- **FR-11.4** — YAML diff parsing for detailed change detection
- **FR-11.5** — Changelog models with structured change entries and types

### Subsystem: Sample Data Generation

**FR-12** requirement family.

- **FR-12.1** — Healthcare-specific sample data from UMF specifications
- **FR-12.2** — Constraint-aware generation (value sets, regex patterns, date formats)
- **FR-12.3** — Foreign key relationship graph for referential integrity
- **FR-12.4** — Domain type-aware generators (SSN, NPI, phone, state codes)
- **FR-12.5** — CSV and JSON output with configurable row counts
- **FR-12.6** — Filename pattern generation from UMF file format specs

### Subsystem: Quality Baselines

**FR-13** requirement family.

- **FR-13.1** — Capture baseline metrics from DataFrames (row counts, distributions, statistics)
- **FR-13.2** — Baseline storage and retrieval
- **FR-13.3** — Comparison against previous baselines with drift detection
- **FR-13.4** — Jensen-Shannon divergence for distribution comparison
- **FR-13.5** — Baseline sync across table definitions (requires PySpark)

### Subsystem: Domain Type Inference

**FR-14** requirement family.

- **FR-14.1** — Automatic domain type detection from column names and descriptions
- **FR-14.2** — YAML-based domain type registry (us_state_code, email, phone, etc.)
- **FR-14.3** — Pattern matching and sample value validation
- **FR-14.4** — Integration with sample data generation and validation

### Subsystem: Table Merge

**FR-15** requirement family.

- **FR-15.1** — Spark-based merge of multiple table files with UMF metadata (requires PySpark)
- **FR-15.2** — Survivorship rules from UMF specifications
- **FR-15.3** — Configurable deduplication and conflict resolution

### Subsystem: Naming Utilities

**FR-16** requirement family.

- **FR-16.1** — `to_spark_identifier()` for canonical snake_case conversion
- **FR-16.2** — `position_sort_key()` for Excel-style column ordering
- **FR-16.3** — Naming validation against UMF conventions

### Subsystem: Date Format System

**FR-17** requirement family.

- **FR-17.1** — Supported date/datetime format definitions with UMF notation
- **FR-17.2** — Format validation and strftime conversion
- **FR-17.3** — Consistent format handling across sample data, validation, and type conversion

## Acceptance Test Sketches

| Requirement | Scenario | Input | Expected Output |
|-------------|----------|-------|-----------------|
| FR-18.1/18.3 (FEAT-026, US-023/US-024, ADR-012) | Compile then run from artifacts | A list of UMF models | Full committed artifact set persisted under the pinned layout; backbone executes them with no tablespec import |
| FR-5.1 | Native profiling on Connect | A Spark Connect DataFrame | Profile computed via Spark-SQL aggregations only; no JVM/Deequ; succeeds on serverless |
| FR-7.7 | Connect-safe validation | A compiled suite + a Connect DataFrame | Data-scanning expectations route to the native executor and return real results (not silent `success=False`) |
| FR-19.1/19.3 | Sibling emitter on core seam | One UMF | dbt and LDP projects both emitted; importing core does not require dbt/LDP packages |
| FR-20.2 | Engine-correct dispatch | A process with both a classic and a Connect session | Column expressions resolve from the DataFrame's own engine and do not raise `'Column' object is not callable` |

## Technical Context

- **Language/Runtime**: Python 3.12+
- **Key Libraries**: Pydantic v2+, Great Expectations 1.6+, PySpark (optional `[spark]` extra), typer + rich (CLI), openpyxl (Excel), ruamel.yaml (split-format YAML), gitpython (changelog)
- **Dev/Test-only tooling**: dbt-core / dbt-duckdb and pysail live in the **dev group** (not user extras); pysail backs the Sail local Spark-Connect test lane; DuckDB used in the bootstrap/conformance matrix
- **Platform Targets**: Classic Spark **and** Databricks serverless / Spark Connect (env-v3, Python 3.12) are both first-class; local Sail (Spark Connect) and DuckDB for tests; no decision may assume a JVM `SparkContext`
- **APIs**: UMF JSON schemas under `src/tablespec/schemas/*.schema.json`

## Constraints, Assumptions, Dependencies

### Constraints

- **Technical**: Core library must import and function without PySpark; Spark-dependent features require the `[spark]` extra. No runtime may assume a classic `SparkContext` (Connect/serverless safety).
- **Business**: Maintained for internal healthcare data platform tables (MD/MP/ME).
- **Legal/Compliance**: Apache 2.0 license; healthcare data handled per platform policy.

### Assumptions

- Downstream runtimes execute committed artifacts and do not import tablespec at run time.
- dbt and pysail are present only in dev/test environments, never as a user runtime dependency.

### Dependencies

- Great Expectations 1.6+ for validation; PySpark for Spark features; dbt-duckdb + pysail for the test matrix.

## Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| GX silently mis-validates on Connect | Med | High | Per-expectation routing to a native DataFrame-API executor (FR-7.7); conformance harness asserts real results |
| Functions dispatch leaks classic Columns into a Connect plan | Med | High | Select functions module from the DataFrame engine (FR-20.2); Sail local-Connect test lane reproduces the coexistence case |
| Committed artifacts drift from UMF | Low | High | Recompile + diff in CI; runtime consumes only artifacts |
| dbt/pysail leak into user runtime surface | Low | Med | Keep them dev-group only; encapsulation test forbids core→dbt import |

## Open Questions

- [x] Should the compile-orchestrator + runtime-consumes-only-artifacts decision get its own ADR? — **Resolved**: recorded in ADR-012 (governed by FEAT-026).
- [x] Should the Connect-safe validation / capability-dispatch decisions (FR-20 / FR-7.7) be confirmed with the architecture owner? — **Resolved**: the first-class Connect/serverless runtime model is recorded in ADR-010 and the per-expectation native-executor routing in ADR-011 (governed by FEAT-024 / FEAT-025).
- [x] Should the LDP sibling emitter be lifted from a design note to a governing ADR/FEAT now that it is wired into compile and conformance? — **Resolved**: lifted to FEAT-028 (LDP sibling emitter) on the shared core seam governed by ADR-013; the design note `docs/helix/02-design/ldp-sibling-emitter.md` is retained as the detailed solution design.

## Success Criteria

- One UMF compiles deterministically to the full committed artifact set; the runtime executes those artifacts with no tablespec dependency.
- Profiling and validation run correctly on both classic Spark and Databricks serverless / Spark Connect.
- Cross-engine conformance parity holds across classic Spark, Sail, and Databricks serverless.
- Zero drift between UMF definitions and the committed artifacts downstream systems execute.

## Out of Scope

- Database connectivity or interactive query execution as a product surface.
- GUI or web interface.
- Real-time schema synchronization.

**Note**: Data-processing capabilities (merge, sample data, quality baselines, profiling, validation) are available via the `[spark]` extra but are scoped to UMF-driven, committed-artifact workflows, not general-purpose ETL. dbt and pysail are dev-group / test-only tooling and are not user-facing runtime dependencies.
