---
ddx:
  id: FEAT-031
---

# Feature Specification: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)

**Feature ID**: FEAT-031
**Status**: Specified (seam phase implemented 2026-06-10; JDBC/dump/parquet phases planned)
**Priority**: P1
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Source Acquisition
**Covered PRD Requirements**: FR-21.1–FR-21.6
**Cross-Subsystem Rationale**: None — single subsystem (Source Acquisition).
This feature owns the discriminated `source:` contract that ADR-015 records;
the emitters (FEAT-026/027/028) and the raw-suite generator consume it.

> **Phase status.** The ingestion seam + `source:` model (SRC-01..05,
> DUMP-05) shipped 2026-06-10 (bead `tablespec-4bea5c6c`). The JDBC
> vertical (JDBC-/DISC-), dump dialect options (DUMP-01..04), and parquet
> typed-raw (PARQ-/SUITE-) requirements describe the TARGET state in SHALL
> form and are not yet implemented.

## Overview

This feature implements PRD FR-21.1–FR-21.6: extend UMF with a
discriminated `source:` block (`kind: delimited | parquet | jdbc`), make
the raw-landing contract kind-dependent (all-STRING raw for text-landed
sources, native-typed raw for parquet/JDBC), extend the single cast truth
with an identity/safe-narrowing mode for typed raw, type the raw-stage
expectation suites accordingly, compile JDBC sources as read-spec
artifacts with secret-referenced credentials, and discover UMF specs from
a live database's `INFORMATION_SCHEMA` (`JdbcToUmfMapper`). It is the
feature-side owner of ADR-015.

Implementation is sequenced (operator-revised 2026-06-10): **ingestion
seam + `source:` model → JDBC vertical → dump dialects → parquet**. The
seam phase carried the fix for a live bug (the e2e backbone hardcoded a
comma-CSV reader and ignored `FileFormatSpec` entirely,
`src/tablespec/e2e/backbone.py` pre-fix). The JDBC vertical is driven by a
concrete consumer — the entropy-exchange `mssql_import` bundle
(entropy-exchange PR #66): an entire SQL Server database restored from a
`.bak` on a Databricks driver node, today hand-rolled (table enumeration,
column sanitization, blind writes — no specs, no validation, no
merge/dedup), to be replaced by discover → read → spec-driven ingest. The
**acceptance goal** is the Northwind end-to-end scenario (US-039).

## Ideal Future State

An engineer declares where a table's data comes from — a pipe-delimited
file, a database dump with footers and `\N` nulls, a parquet drop, or a
JDBC-readable table — in one discriminated `source:` block, and every
downstream artifact (raw DDL, ingest SQL, expectation suites, backbone
reader options, emitter projects) is compiled from that declaration.
Text-landed data keeps the proven all-STRING raw landing; already-typed
data lands typed and is never round-tripped through string parsing — a
typed DATE column can never be silently NULLed by a string-parse cast.
JDBC sources compile to a read spec whose credentials are secret
references only; tablespec never opens a database connection — all
connectivity is Spark's JDBC connector, executed by the runtime. Pointing
tablespec at a whole database yields one validated UMF per table.
Existing UMFs that declare only `file_format:` compile byte-identically.

## Problem Statement

- **Current situation**: UMF could describe exactly one source shape — a
  delimited text file via `file_format: FileFormatSpec`
  (`src/tablespec/models/umf.py:128-155`). Its `skip_rows` field is
  declared but consumed by no reader. The raw→ingest cast layer assumes
  string-typed raw input (`build_ingest_select` / `cast_column_sql`,
  `src/tablespec/schemas/ingest_generator.py:76-178`,
  `src/tablespec/casting_utils.py:571`), and raw-stage suites assert
  string facts — length/regex/strftime/castability
  (`src/tablespec/gx_baseline.py:345-479,638-648`).
- **Pain points**: Database dumps (multi-char line terminators, `\N` null
  escapes, footer rows) cannot be declared; parquet and JDBC sources had
  no representation at all; forcing typed data through all-STRING raw is
  lossy, and feeding a typed DATE to the string-parse path
  (`try_to_timestamp`) silently NULLs every value. A live bug showed the
  consumption gap: the e2e backbone hardcoded comma-CSV and ignored
  `FileFormatSpec` (fixed in the seam phase) even though the correct
  UMF→reader-options pattern already existed (`src/tablespec/merge.py`).
  The mssql consumer hand-rolls everything tablespec exists to govern.
- **Desired outcome**: One kind-discriminated source contract driving
  readers, casts, suites, and emitters, per ADR-015 — with zero regression
  for existing delimited UMFs, and database onboarding that starts from
  discovered, validated specs.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Source declaration | "How do I tell tablespec where this table's data comes from?" | Discriminated `source:` block (delimited / parquet / jdbc) with per-kind validated options; `file_format:` back-compat alias |
| Ingestion reader seam | "Where does read logic live so every consumer behaves the same?" | `tablespec.ingestion` package: `SourceReader` protocol + `get_reader(spec)` factory; merge and backbone read through it |
| Dump-dialect text landing | "Can I ingest this database dump file as-is?" | Delimited-variant options for multi-char line terminators, `\N` null escapes, footers, and honored `skip_rows`; readers derive options from UMF |
| Typed-raw parquet | "My data is already typed — why stringify it?" | Native-typed raw landing for parquet; identity/safe-narrowing mode in the one cast truth |
| JDBC compiled read spec | "How do I ingest from a database without handing tablespec credentials?" | Compile a read-spec artifact with credentials only as named secret references; runtime resolves secrets and performs the read |
| Database discovery | "Can I point tablespec at a database and get specs for every table?" | `JdbcToUmfMapper`: `INFORMATION_SCHEMA` → one validated UMF per table (columns, types, nullability, PKs, FKs) |
| Raw-suite typing | "Why is a regex check running against a DATE column?" | Raw-stage suites branch on raw typing: string checks for all-STRING raw, schema-type expectations for typed raw |

## Requirements

### Functional Requirements by Area

#### Source declaration (FR-21.1) — implemented 2026-06-10

SRC-01. UMF SHALL carry a discriminated `source:` block with
`kind: delimited | parquet | jdbc`; unknown kinds SHALL be rejected at
load with an actionable error.
SRC-02. The `delimited` variant body SHALL be today's `FileFormatSpec`
fields; `file_format:` SHALL be kept as a back-compat alias during
migration, resolved through a non-persisting accessor
(`UMF.effective_source()`).
SRC-03. A UMF declaring only `file_format:` and no `source:` block SHALL
compile byte-identically to its pre-FEAT-031 artifacts (zero golden
diffs), and SHALL round-trip byte-identically through load→save.
SRC-04. Each source kind SHALL carry a defined raw-typing regime:
`delimited` → all-STRING raw (ADR-007 unchanged for text-landed sources);
`parquet` and `jdbc` → native-typed raw (ADR-015).
SRC-05. Read logic SHALL live behind the `tablespec.ingestion` package:
a `SourceReader` protocol (`read(spec, spark) -> DataFrame`) and a
`get_reader(spec)` factory dispatching on source kind. The first reader
(`CsvReader`) is the read logic extracted from `merge.py`, and the
package implements the imports `merge.py` declared behind try/except
fallbacks before the package existed
(`tablespec.ingestion.constants.normalize_spark_encoding`,
`tablespec.ingestion.raw_ingester.{build_column_lookup, map_headers}`).

#### Dump-dialect text landing (FR-21.2)

DUMP-01. The `delimited` variant SHALL support multi-character line
terminators.
DUMP-02. The `delimited` variant SHALL support `\N`-style null escapes in
addition to the plain `null_value` token.
DUMP-03. The `delimited` variant SHALL support footer handling: declared
footer rows SHALL be excluded from landed data, never counted as records.
DUMP-04. Compiled readers SHALL honor `skip_rows` (declared in the model
since before this feature, consumed by no reader pre-FEAT-031).
DUMP-05 (implemented 2026-06-10). The e2e backbone reader SHALL derive
reader options from the declared `source:`/`file_format` when present,
via the ingestion package; when no source is declared the pre-existing
comma-CSV behavior is preserved exactly (conformance-corpus dependency).

#### Typed-raw parquet (FR-21.3)

PARQ-01. Parquet sources SHALL land native-typed raw — no stringification
of already-typed columns.
PARQ-02. The one cast truth (`build_ingest_select` / `cast_column_sql`)
SHALL grow an identity/safe-narrowing mode for typed raw. A typed DATE or
TIMESTAMP column SHALL NEVER be routed through `try_to_timestamp` or any
string-parse path (which would silently NULL all values); permitted
operations are identity pass-through and explicitly safe narrowing.
PARQ-03. ADR-001's date-as-yyyymmdd-string convention SHALL apply only to
text-landed sources; parquet DATE columns map natively (ADR-015 scoping).

#### JDBC compiled read spec (FR-21.4)

JDBC-01 (model implemented 2026-06-10; compile/read planned). The `jdbc`
source variant SHALL carry connection parameters — `url`, `dbtable` or
`query` (mutually exclusive), `driver`, optional `fetch_size` and
partition column/bounds for parallel reads — with credentials ONLY as
named secret references (a Databricks secret scope reference or
environment-variable name, e.g. `password_secret_ref`). A literal
credential field (e.g. `password`) SHALL raise a model `ValidationError`;
credentials SHALL never appear in UMF or in any compiled artifact.
JDBC-02. tablespec SHALL NOT open a database connection at compile time;
the runtime/backbone resolves secret references and performs the read
(`spark.read.format("jdbc")` with options derived from the spec). This
rewords but preserves the PRD Non-Goal "Database connectivity ... as a
product surface".
JDBC-03. JDBC sources SHALL land native-typed raw under the same
identity/safe-narrowing cast contract as parquet (PARQ-02).
JDBC-04. A connection or secret reference the runtime cannot resolve SHALL
fail closed with an actionable error naming the missing reference — never
a silent skip or empty read.
JDBC-05. Source identifiers SHALL be sanitized to canonical column names
deterministically: lowercase, non-alphanumerics → underscore, repeated
underscores collapsed (the rules proven in the entropy-exchange
`mssql_import` bundle), with bracket/backtick quoting handled at the read
boundary and the original source identifier preserved in the spec.

#### Database discovery (FR-21.6)

DISC-01. A `JdbcToUmfMapper` SHALL read a live database's
`INFORMATION_SCHEMA` — columns, types, nullability, primary keys, foreign
keys — and emit one UMF per table. It SHALL connect ONLY through Spark's
JDBC connector (`spark.read.format("jdbc")` with `option("query", ...)`
for metadata queries; the reflected DataFrame schema for column types) and
SHALL reuse the existing `SparkToUmfMapper`
(`src/tablespec/profiling/spark_mapper.py`) for type mapping — tablespec
gains NO direct database-driver dependency (no pyodbc/JayDeBeApi), and
never connects to anything itself, even at discovery time
(operator-confirmed 2026-06-10).
DISC-02. Mapper-generated UMFs SHALL pass `tablespec validate`
unmodified, and SHALL carry a `source:` block of kind `jdbc` whose
credentials are secret references only (JDBC-01).
DISC-03. Discovery SHALL be the spec-producing front of the ingestion
flow: discover UMFs → land raw via the reader seam → standard spec-driven
ingest transforms — replacing blind bulk copies (the consumer's
hand-rolled `03_etl.py` loop) with validated, spec-driven ingestion.

#### Raw-suite typing (FR-21.5)

SUITE-01. Raw-stage expectation suites SHALL vary by raw typing: string
checks — length/regex/strftime/castability (emitted unconditionally for
raw pre-FEAT-031, `gx_baseline.py:345-479,638-648`) — SHALL apply only to
all-STRING raw.
SUITE-02. Typed raw SHALL receive schema-type expectations (declared
type/nullability conformance) instead of string-shape checks.
SUITE-03. Stage routing SHALL remain data-driven via the existing
expectation-stage classification (`umf.py:94-112`,
`ExpectationMeta.stage`); raw-typing selection extends it, not replaces it.

### Non-Functional Requirements

- **Back-compat**: Recompiling every existing UMF in the conformance corpus
  SHALL produce byte-identical artifacts (SRC-03 corpus-wide). Evidence:
  golden-artifact diff gate in CI (green on the seam phase, 2026-06-10).
- **Type fidelity**: Zero silent NULL-out on typed raw — a negative test
  SHALL feed typed DATE/TIMESTAMP raw through the cast layer and assert no
  value is NULLed by parsing (PARQ-02).
- **Determinism**: Compiled read specs and dump-dialect reader options
  SHALL be deterministic functions of the UMF (no environment-dependent
  output), consistent with the committed-artifact model (ADR-012).
- **Security**: No credential material in any tablespec input or output;
  the JDBC read spec carries secret references only (JDBC-01).
- **No new connectivity dependencies**: zero direct database-driver
  imports in `src/tablespec` (DISC-01) — enforceable by grep/import test.

## User Stories

- [US-039 — Northwind End-to-End on Databricks](../user-stories/US-039-northwind-end-to-end.md)
  — the acceptance-goal story for the JDBC vertical: load the Northwind
  database, discover UMF specs, export a schema xlsx, validate, generate
  sample data, and produce a validation report.

Per-phase stories will be authored at execution start, in sequencing order:
US-040 (ingestion seam + `source:` model — implemented; story to backfill
ACs), US-041 (JDBC reader + discovery slices under US-039's goal), US-042
(dump-dialect text landing), US-043 (typed-raw parquet).

## Edge Cases and Error Handling

- **Typed DATE through string-parse corruption**: a typed DATE column
  reaching `try_to_timestamp` would silently NULL all values; the
  identity/safe-narrowing mode (PARQ-02) plus a dedicated negative test
  make this path unreachable for typed raw.
- **Mixed-typing UMF sets in one compile**: a compile run containing both
  delimited (all-STRING raw) and parquet/JDBC (typed raw) tables SHALL
  produce per-table correct casts and suites; no global raw-typing flag.
- **Connection/secret reference unresolvable at runtime**: fail closed
  with an actionable error naming the reference (JDBC-04); never an empty
  read.
- **Dump footer rows counted as data**: footer handling (DUMP-03) excludes
  them; fixture coverage in the dump conformance tier.
- **Back-compat**: a UMF with only `file_format:` and no `source:` block
  compiles and round-trips byte-identically (SRC-03) — the alias is
  resolved through one accessor, never persisted.
- **Imperfect dialect type mapping** (e.g. SQL Server `datetimeoffset`):
  the discovered UMF surfaces the mapped type for review — discovery
  output is a reviewable spec, not a blind copy.

## Success Metrics

- **Northwind end-to-end (the acceptance goal, US-039)**: on Databricks,
  load the Northwind database, discover one UMF per table, export a schema
  xlsx, validate the specs, generate sample data, and produce a validation
  report — every step spec-driven, no hand-rolled enumeration or writes.
- Byte-identical recompile for all existing UMFs (zero regression) —
  golden-artifact diff gate green across the corpus (verified green on the
  seam phase, 2026-06-10).
- Conformance corpus gains dump and parquet fixture tiers, both green.
- Zero silent NULL-out on typed raw, proven by a negative test that feeds
  typed DATE/TIMESTAMP raw through the cast layer.
- Pre-existing tests pass unchanged after the `CsvReader` extraction
  (SRC-05's no-behavior-change proof; verified 2026-06-10).

## Constraints and Assumptions

- ADR-015 fixes the design: discriminated `source:` block, kind-dependent
  raw typing, identity/safe-narrowing extension of the one cast truth,
  compiled-only JDBC via Spark's connector, Spark-only discovery. This
  spec does not relitigate those decisions.
- Implementation sequencing (operator-revised 2026-06-10): ingestion seam +
  `source:` model (done) → JDBC vertical (toward US-039) → dump dialects →
  parquet.
- SQL Server install/restore on the Databricks driver node stays with the
  consumer bundle (entropy-exchange `mssql_import` owns that
  Databricks-runtime plumbing); tablespec owns discover → read → ingest.
- The cast extension lives inside the existing target-agnostic core seam
  (ADR-013) — emitters consume it; no emitter forks cast logic.
- The profiler is already type-flexible and is assumed to need no
  contract change for typed raw (per-type profiling phases,
  `src/tablespec/profiling/native_profiler.py:296-301`).
- ADR-007 remains Accepted for text-landed sources; ADR-001 is scoped to
  text-landed sources (ADR-015 Supersession section).

## Dependencies

- **ADRs**: ADR-015 (source-shape contract — the governing decision),
  ADR-007 (all-STRING raw, generalized to the delimited variant), ADR-001
  (date-as-yyyymmdd-string, scoped to text-landed sources).
- **Other features**: FEAT-026 (compile orchestrator — artifact set gains
  the read spec), FEAT-027 (dbt emitter) and FEAT-028 (LDP emitter) —
  emitter touchpoints for kind-dependent casts; FEAT-024 (native profiler —
  already type-flexible); FEAT-005 (`SparkToUmfMapper`, reused by
  discovery); FEAT-009/FEAT-011/FEAT-021/FEAT-007/FEAT-017/FEAT-029
  (shipped features US-039 composes).
- **PRD requirements**: FR-21.1–FR-21.6 (Source Acquisition).
- **Work queue**: epic `tablespec-ef91646f` with children
  `tablespec-4bea5c6c` (seam+model, done), `tablespec-4b65c810` (JDBC
  reader + discovery), `tablespec-8980c812` (US-039 acceptance),
  `tablespec-df8bc351` (dumps), `tablespec-61da147e` (parquet).

## Out of Scope

- Runtime federation / live JDBC execution by tablespec — tablespec
  compiles read specs only; the runtime/backbone owns connectivity.
- Direct database drivers (pyodbc/JayDeBeApi) anywhere in tablespec.
- Real-time CDC ingestion.
- Non-Spark JDBC runtimes.
- SQL Server installation/restore mechanics (consumer-owned).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements (`FR-n`) are listed; single
  subsystem, no cross-subsystem rationale needed
- [x] Functional areas are subordinate parts of this one capability
- [x] Overview connects this feature to specific PRD requirements
  (FR-21.1–FR-21.6)
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is broken
- [x] Every functional requirement is testable
- [ ] Acceptance criteria are defined in user stories — US-039 authored;
  US-040..043 planned per phase
- [x] Non-functional requirements have specific targets
- [x] Edge cases cover realistic failure scenarios
- [x] Success metrics are specific to this feature
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes things someone might reasonably assume are in
  scope
- [x] Implementation status is honestly per-phase (seam done; JDBC, dumps,
  parquet planned); no phantom completion claims
- [x] Feature is consistent with governing ADR-015 and the PRD Non-Goal on
  database connectivity
- [x] No `[NEEDS CLARIFICATION]` markers remain
