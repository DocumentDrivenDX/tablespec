---
ddx:
  id: US-039
---

# US-039: Northwind End-to-End on Databricks

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: SRC-01, SRC-05, JDBC-01–JDBC-05, DISC-01–DISC-03
**PRD Requirements**: FR-21.1, FR-21.4, FR-21.6
**Priority**: P1
**Status**: Approved (Docker lane green 2026-06-11, commit 224a8af; databricks_e2e lane wired and skip-gated pending a workspace-reachable Northwind — consumer-owned)

## Story

**As a** data engineer on a Databricks workspace with a SQL Server database
reachable via Spark JDBC (e.g. Northwind restored on the driver node)
**I want** to point tablespec at the database and get validated UMF specs,
a reviewable schema workbook, generated sample data, and a validation
report — without hand-rolling table enumeration, column sanitization, or
writes
**So that** onboarding an entire database is spec-driven from the first
minute, instead of a blind bulk copy that acquires specs later (or never).

## Context

This is the acceptance-goal story for FEAT-031's JDBC vertical (ADR-015).
The consumer scenario is the entropy-exchange `mssql_import` bundle: a SQL
Server `.bak` restored on a Databricks driver node, today landed by a
hand-rolled loop with no specs, no validation, and no merge/dedup. The
goal scenario uses Northwind because it exercises the hard parts cheaply:
`Order Details` (identifier with a space → sanitization, JDBC-05),
`Orders.CustomerID → Customers.CustomerID` (FK discovery, DISC-01), and a
mix of types (money, datetime, nvarchar, image) that stresses Spark's
JDBC dialect mapping. All connectivity is Spark's JDBC connector —
tablespec opens no connection itself, even for discovery
(operator-confirmed 2026-06-10).

Downstream steps reuse shipped features: schema xlsx via FEAT-009
(`tablespec export-excel`), spec validation via FEAT-021
(`tablespec validate`), sample data via FEAT-011, and the validation
report via FEAT-007/FEAT-017's staged execution and reporting.

## Walkthrough

1. The engineer restores/loads Northwind so it is reachable via Spark JDBC
   (consumer-owned precondition; the bundle keeps owning install/restore).
2. They run discovery against the database with a JDBC source spec whose
   credentials are secret references only. tablespec enumerates tables and
   reads `INFORMATION_SCHEMA` metadata through `spark.read.format("jdbc")`,
   emitting one UMF per table with columns, types, nullability, PKs, and
   FKs, with identifiers sanitized to canonical names.
3. They run `tablespec validate` over the discovered UMFs — every spec
   passes unmodified.
4. They export the schema workbook (`tablespec export-excel`) for review
   by domain experts.
5. They generate sample data from the discovered specs (FK-aware, so
   generated `orders` rows reference generated `customers` keys).
6. They land the real tables through the reader seam and run staged
   validation, producing a validation report per table.

## Acceptance Criteria

- [x] **US-039-AC1 (discovery)** — Given Northwind reachable via Spark
  JDBC and a `source: {kind: jdbc}` spec whose credentials are secret
  references, when discovery runs, then one UMF per table is emitted with
  columns, UMF-mapped types, nullability, primary keys, and foreign keys
  (including `orders.customer_id → customers.customer_id`), and no
  credential material appears in any emitted UMF.
- [x] **US-039-AC2 (sanitization)** — Given the `Order Details` table,
  when discovery emits its UMF, then the table and column identifiers are
  canonical (`order_details`; lowercase, non-alphanumerics → underscore,
  repeats collapsed) and the original source identifier is preserved in
  the spec for the read boundary.
- [x] **US-039-AC3 (spec validity)** — Given the discovered UMF set, when
  `tablespec validate` runs over each spec, then every spec passes with
  zero errors and zero manual edits.
- [x] **US-039-AC4 (schema workbook)** — Given the discovered UMF set,
  when `tablespec export-excel` runs, then a workbook is produced with one
  sheet per table whose rows match the UMF columns/types, and a re-import
  round-trips without loss (FEAT-009 contract).
- [x] **US-039-AC5 (sample data)** — Given the discovered UMF set, when
  sample data generation runs, then data is produced for every table and
  FK-aware generation holds (every generated `orders.customer_id` exists
  among generated `customers.customer_id` values).
- [x] **US-039-AC6 (validation report)** — Given the landed Northwind
  tables, when staged validation executes against the compiled suites,
  then a validation report is produced per table with real per-expectation
  results (no silent `success=False` stubs), and typed columns are never
  routed through string-parse casts (zero silent NULL-out).

**Evidence (Docker lane, 2026-06-11)**: `uv run pytest
tests/integration/test_jdbc_discovery.py tests/integration/test_northwind_e2e.py -q`
→ 14 passed, 1 skipped (the skip is the gated databricks_e2e lane). AC4
passes on the converter's own contract; carrying `source:` and discovered
`foreign_keys` through the workbook is follow-up `tablespec-036d3e9d`. AC6
uses a test-local report bridge; shipping it is `tablespec-72c03317`.

## Edge Cases

- A SQL Server type Spark's dialect maps imperfectly (e.g.
  `datetimeoffset`): the discovered UMF surfaces the mapped type for
  review — discovery output is a reviewable spec, not a blind copy.
- An unresolvable secret reference fails closed with an error naming the
  missing reference (JDBC-04) before any read is attempted.
- A table with no primary key (e.g. a view or log table) discovers
  cleanly with no PK rather than failing.

## Test Scenarios

- Local lane: a Docker-gated SQL Server container loaded with Northwind;
  the suite SKIPS (not fails) when Docker is absent — mirroring the
  consumer bundle's gating. Concrete assertions: 13 base tables
  discovered; `order_details` FK set includes `order_id → orders.order_id`
  and `product_id → products.product_id`; `customers.customer_id` typed
  CHAR(5) NOT NULL.
- Databricks lane: opt-in `databricks_e2e` tier runs the full US-039 flow
  on a workspace when credentials are configured.

## Dependencies

- **Feature Spec**: FEAT-031 (SRC-05 reader seam, JDBC-01..05, DISC-01..03)
- **Decisions**: ADR-015 (source-shape contract; Spark-only connectivity)
- **Shipped features reused**: FEAT-009 (Excel), FEAT-011 (sample data),
  FEAT-021 (spec validation), FEAT-007/FEAT-017 (staged validation +
  report), FEAT-029 (session acquisition on Databricks)
- **Consumer**: entropy-exchange `mssql_import` (owns SQL Server
  install/restore on the driver node)
- **Work queue**: beads `tablespec-4b65c810` (reader + discovery) →
  `tablespec-8980c812` (this story's acceptance run)

## Out of Scope

- SQL Server installation/restore mechanics (consumer-owned).
- Real-time sync or CDC from the source database.
- Non-Spark connectivity of any kind.
