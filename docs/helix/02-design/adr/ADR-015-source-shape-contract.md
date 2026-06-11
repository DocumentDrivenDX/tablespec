---
ddx:
  id: ADR-015
---

# ADR-015: Discriminated Source-Shape Contract with Kind-Dependent Raw Typing

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-10 | Accepted | Erik LaBianca | FEAT-031, ADR-007, ADR-001, ADR-013 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | UMF can only describe one source shape: a delimited text file (`FileFormatSpec`, `src/tablespec/models/umf.py:128-155`). Planned ingestion work must also cover database dump files (multi-char line terminators, `\N` null escapes, footers), parquet, and JDBC-sourced tables — and the existing all-STRING raw landing (ADR-007) plus the date-as-yyyymmdd-string convention (ADR-001) silently assume text-landed sources. Forcing typed sources (parquet, JDBC) through the string-everything contract is lossy; feeding a typed DATE column to the string-parse cast path (`try_to_timestamp`) would silently NULL every value. |
| Current State | `file_format: FileFormatSpec` is the only source descriptor (`umf.py:128-155`); its `skip_rows` field is declared but consumed by no reader (`umf.py:141-143`). The raw→ingest cast layer has one cast truth (`build_ingest_select` / `cast_column_sql`, `src/tablespec/schemas/ingest_generator.py:76-178`, `src/tablespec/casting_utils.py:571`) that assumes string-typed raw input. Raw-stage expectation suites emit string checks — length/regex/strftime/castability (`src/tablespec/gx_baseline.py:345-479,638-648`) — routed data-driven by stage (`umf.py:94-112`). A live bug demonstrates the gap: the e2e backbone hardcoded a comma-CSV reader and ignored `FileFormatSpec` entirely (`src/tablespec/e2e/backbone.py:229-243` pre-fix), while `merge.py:84-105` already showed the correct UMF→reader-options pattern. |
| Requirements | PRD FR-21.1–FR-21.6 (Source Acquisition subsystem). PRD Non-Goal: "Database connectivity ... as a product surface" — preserved, reworded as a compile-time framing. FEAT-031 (multi-source ingestion). |
| Decision Drivers | One cast truth across source kinds (ADR-013 seam discipline); honesty in naming (a JDBC table is not a "file format"); no lossy stringification of already-typed data; credentials must never enter UMF or compiled artifacts; existing UMFs must keep compiling byte-identically. |

## Decision

We will add a **discriminated `source:` block** to UMF with
`kind: delimited | parquet | jdbc`, and make the raw-landing contract
**kind-dependent**:

1. **`source:` block** — today's `FileFormatSpec` (`umf.py:128-155`) becomes
   the body of the `delimited` variant; `file_format:` is kept as a
   back-compat alias during migration, resolved via a non-persisting
   accessor (`UMF.effective_source()`) so legacy UMFs round-trip
   byte-identically. The `delimited` variant also covers database dump
   files via new options: multi-character line terminators, `\N`-style
   null escapes, footer handling, and honoring the
   already-declared-but-unconsumed `skip_rows` (`umf.py:141-143`).
2. **Kind-dependent raw typing** — text-landed sources (delimited, dumps)
   keep the all-STRING raw landing (ADR-007 unchanged for them); typed
   sources (parquet, jdbc) land **native-typed** raw. The one cast truth
   (`build_ingest_select` / `cast_column_sql`,
   `ingest_generator.py:76-178`, `casting_utils.py:571`) grows an
   identity/safe-narrowing mode for typed raw — a typed DATE column is NEVER
   fed to `try_to_timestamp` (it would silently NULL all values).
3. **Kind-dependent raw suites** — string checks
   (length/regex/strftime/castability, `gx_baseline.py:345-479,638-648`)
   apply only to all-STRING raw; typed raw gets schema-type expectations
   instead. Stage routing stays data-driven (`umf.py:94-112`,
   `ExpectationMeta.stage`).
4. **JDBC is compiled artifacts ONLY** — tablespec compiles a JDBC read spec
   that may carry explicit connection parameters (`url`, `dbtable`/`query`,
   `driver`, `fetch_size`, optional partition column/bounds) but whose
   credentials exist ONLY as named secret references (a Databricks secret
   scope reference or an environment-variable name — e.g.
   `password_secret_ref`); a literal credential field fails model
   validation. tablespec never opens a connection at compile time; the
   runtime/backbone resolves secrets and performs the read. This rewords
   but preserves the PRD Non-Goal "Database connectivity ... as a product
   surface".
5. **Readers live behind one seam** — the `tablespec.ingestion` package
   (`SourceReader` protocol + `get_reader(spec)` factory) dispatching on
   source kind. The seam was already *named* in code: `merge.py:24-37`
   imported `tablespec.ingestion.constants` and
   `tablespec.ingestion.raw_ingester` behind try/except fallbacks before
   the package existed. Phase 1 built it by extracting the existing CSV
   read logic (`merge.py:84-107`) verbatim.
6. **Discovery rides Spark's JDBC connector** — `JdbcToUmfMapper` connects
   ONLY through `spark.read.format("jdbc")` (`option("query", ...)` for
   `INFORMATION_SCHEMA` metadata; the reflected DataFrame schema for column
   types, reused via the existing `SparkToUmfMapper`). tablespec gains no
   direct database-driver dependency (no pyodbc/JayDeBeApi) and never
   connects to anything itself, even at discovery time
   (operator-confirmed 2026-06-10).

**Key Points**: Implementation sequencing (operator-revised 2026-06-10,
superseding the initial dumps-first order): **ingestion seam + `source:`
model first** (carries the fix for the live backbone bug —
`e2e/backbone.py:229-243` hardcoded comma-CSV and ignored `FileFormatSpec`;
`merge.py:84-105` was the correct pattern to generalize), **then the JDBC
vertical** (reader + `JdbcToUmfMapper` discovery, FR-21.6), driven by a
concrete consumer: the entropy-exchange `mssql_import` bundle
(entropy-exchange PR #66) landing a SQL Server database restored on a
Databricks driver node, with the Northwind end-to-end scenario (US-039) as
the acceptance goal — **then dump dialects and parquet** | ADR-001
(date-as-yyyymmdd-string) is scoped by this decision to text-landed sources
only; typed sources map DATE natively | ADR-007's all-STRING raw becomes the
delimited-text variant of the generalized contract and stays Accepted.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Extend `file_format` with a `format:` field (no new block) | Smallest schema diff; no alias needed | `file_format: jdbc` is dishonest naming — a JDBC table has no file format — and collides with dbt's target-side `file_format` config, inviting confusion at the emitter seam; flat fields can't carry per-kind required options | Rejected: dishonest naming and a dbt collision, with no discriminated validation |
| Stringify-everything raw (force parquet/JDBC through all-STRING raw) | One raw contract; ADR-007 untouched; cast layer unchanged | Lossy (decimal precision, temporal fidelity); round-trips typed values through string render + re-parse, creating exactly the avoidable accident the vision forbids — e.g. a typed DATE re-parsed via `try_to_timestamp` silently NULLs | Rejected: creates the avoidable accident the vision forbids and is lossy |
| Runtime federation for JDBC (tablespec opens connections and reads) | Self-contained demos; no runtime dependency on a backbone | Erodes the PRD Non-Goal "Database connectivity ... as a product surface"; pulls credential handling into a compile-time tool; couples the compiler to driver runtimes | Rejected for Non-Goal erosion |
| Direct database drivers for discovery (pyodbc / JayDeBeApi in tablespec) | `INFORMATION_SCHEMA` access without a Spark session | New driver dependencies and credential handling inside tablespec; a second type-mapping seam alongside Spark's dialects; breaks "tablespec never connects" even at discovery time | Rejected (operator-confirmed 2026-06-10): discovery rides Spark's JDBC connector — `INFORMATION_SCHEMA` via `option("query", ...)`, column types from the reflected DataFrame schema reused through the existing `SparkToUmfMapper` |
| **Discriminated `source:` block + kind-dependent raw typing + compiled-only JDBC (selected)** | Honest per-kind schema with discriminated validation; typed data stays typed; one cast truth extended (identity/safe-narrowing), not forked; credentials stay out of compile scope; back-compat accessor keeps existing UMFs byte-identical | Two raw-typing regimes to test (string and typed suites); migration period carries the alias; emitters must consult source kind | **Selected: only option that is honest in naming, lossless for typed sources, and preserves both ADR-007 (for text) and the JDBC Non-Goal** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | One UMF describes delimited files, dumps, parquet, and JDBC tables with kind-checked options; typed sources keep native fidelity end-to-end; the cast layer stays single-sourced (identity/safe-narrowing mode, not a fork); raw suites stop asserting string facts about non-string data; the seam phase fixed the live backbone reader bug; credentials remain structurally impossible in UMF. |
| Negative | The raw contract is no longer uniform — every consumer of "raw is all STRING" must branch on source kind; the conformance corpus must grow dump and parquet fixture tiers; the `file_format` alias must be maintained until migration completes. |
| Neutral | ADR-007 remains Accepted, narrowed to the delimited-text variant; ADR-001 remains Accepted, scoped to text-landed sources; JDBC reads move no closer to the product surface — the runtime/backbone owns connectivity as before. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Typed DATE routed through the string-parse cast path, silently NULLing all values | M | H | Identity/safe-narrowing mode in the one cast truth (`ingest_generator.py:76-178`, `casting_utils.py:571`) selected by source kind; a dedicated negative test asserts zero silent NULL-out on typed raw |
| `file_format` alias and `source:` block drift apart during migration | M | M | Alias resolved through one accessor (`UMF.effective_source()`); byte-identical recompile of all existing UMFs is a release gate |
| String-suite expectations applied to typed raw (guaranteed failures) or vice versa | M | M | Suite generation branches on declared raw typing, not on heuristics; conformance fixtures cover both regimes (`gx_baseline.py:345-479` checks only emitted for all-STRING raw) |
| Named JDBC connection or secret reference unresolvable at runtime | M | M | Compiled read spec carries names only; the runtime fails closed with an actionable error naming the missing reference — never a silent skip |
| Spark JDBC dialect maps a source type imperfectly (e.g. SQL Server `datetimeoffset`) | M | M | Discovery reuses Spark's dialect mapping deliberately (one type-mapping seam); imperfect mappings surface in the discovered UMF for review before compile — discovery output is a reviewable spec, not a blind copy |
| Dump footer rows counted as data | L | M | Footer handling is a first-class `delimited` option with fixture coverage in the dump tier |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Every existing UMF (with only `file_format:`, no `source:`) recompiles byte-identically | Any golden-artifact diff on an unmodified UMF |
| Northwind end-to-end (US-039) passes: discover → validate → xlsx → sample data → validation report | Any US-039 AC failing on the Docker lane |
| Conformance corpus gains dump and parquet fixture tiers, both green | A source kind ships without a fixture tier |
| Negative test proves zero silent NULL-out when typed DATE/TIMESTAMP raw passes the cast layer | Any typed column observed NULLing through ingest |
| `e2e/backbone.py` reads via UMF-derived options (the `merge.py:84-105` pattern) when a source is declared | The backbone reader and the merge reader diverge again |

## Supersession

- **Supersedes**: None. This ADR **generalizes ADR-007** — ADR-007 stays
  **Accepted** as the delimited-text variant of the kind-dependent raw
  contract (all-STRING raw applies to text-landed sources only). It also
  **scopes ADR-001** (date-as-yyyymmdd-string) to text-landed sources;
  typed sources (parquet, jdbc) map DATE natively.
- **Superseded by**: None

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: This ADR governs the UMF source contract and the
  raw-landing typing regime; no active-concern relevance.

## References

- PRD Subsystem "Source Acquisition" — FR-21.1–FR-21.6; PRD Non-Goal
  "Database connectivity ... as a product surface" (preserved, reworded as
  compile-time framing)
- FEAT-031 (Multi-Source Ingestion), US-039 (Northwind end-to-end
  acceptance goal)
- ADR-007 (raw→ingest SQL artifact — generalized, stays Accepted), ADR-001
  (date-as-yyyymmdd-string — scoped to text-landed sources), ADR-013
  (target-agnostic core seam the cast extension must respect)
- `src/tablespec/models/umf.py:128-155` (`FileFormatSpec`, becomes the
  `delimited` variant body), `umf.py:141-143` (`skip_rows` declared,
  unconsumed pre-fix), `umf.py:94-112` (data-driven stage routing)
- `src/tablespec/schemas/ingest_generator.py:76-178`
  (`build_ingest_select` — the one cast truth),
  `src/tablespec/casting_utils.py:571` (`cast_column_sql`)
- `src/tablespec/gx_baseline.py:345-479,638-648` (string-raw checks:
  length/regex/strftime/castability)
- `src/tablespec/e2e/backbone.py` (pre-fix live bug: hardcoded comma-CSV,
  `FileFormatSpec` ignored), `src/tablespec/merge.py:84-105` (the correct
  UMF→reader-options pattern), `merge.py:24-37` (the dangling
  `tablespec.ingestion` imports — the seam named before it was built)
- DDx epic `tablespec-ef91646f` (ingestion source abstraction; phased plan
  + acceptance), entropy-exchange PR #66 `posts/databricks/mssql_import/`
  (the consumer: SQL Server `.bak` restored on a Databricks driver node,
  hand-rolled today, to be replaced by discover→read→ingest)

## Review Checklist

- [x] Context names a specific problem — one source shape, lossy/string-only raw contract, live backbone reader bug
- [x] Decision statement is actionable ("we will add a discriminated `source:` block ... kind-dependent raw typing")
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-031 and PRD FR-21.1–FR-21.6
