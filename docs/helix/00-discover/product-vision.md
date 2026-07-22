---
ddx:
  id: product-vision
---

# Product Vision

## Mission Statement

tablespec makes Universal Metadata Format (UMF) the single, canonical source of truth for table schemas on healthcare data platforms, and acts as the *compiler* that turns one UMF into the full set of committed, reviewable runtime artifacts — direct SQL, dbt projects, Lakeflow Declarative Pipelines (LDP), and Great Expectations suites — so downstream runtimes execute diffable artifacts instead of re-deriving schema at run time.

## Positioning

For **data and data-quality engineers** on healthcare platforms who **maintain table schemas, transforms, and validation across many tools and formats (SQL DDL, PySpark, JSON Schema, Great Expectations, dbt, LDP)**,
**tablespec** is a **schema-compilation library** that **takes one UMF and deterministically compiles it into every committed runtime artifact, then lets the runtime consume only those artifacts**.
Unlike **hand-maintaining each tool's schema and transforms separately (where definitions drift and validation diverges)**, **tablespec** **compiles once from UMF and runs from committed, diffable artifacts — so the transform is reviewable and the runtime carries no library dependency.**

## Vision

When tablespec succeeds, a healthcare data platform has exactly one place to change a table's truth: its UMF. From that UMF, a deterministic compile step emits the complete set of committed runtime artifacts — raw→ingest and gold SQL plans, dbt ingest and gold-DAG projects, LDP projects, and GX validation suites. The runtime never re-derives schema or transforms from UMF; it reads only the committed artifacts. Every change to a transform shows up as a reviewable diff, and the same UMF runs first-class on both classic Spark and Databricks serverless / Spark Connect. Schema drift between tools is structurally impossible because there is only one upstream source and one deterministic compiler.

tablespec also gives teams a concrete definition of done for source-preserving bronze. Raw storage keeps the source bytes and records available for audit and replay. The compiled ingested contract captures the source table's meaning in Databricks / Unity Catalog / Delta-compatible artifacts: the UMF snapshot, typed ingested table definition, validation criteria, relationships, aliases, keys, generated raw→ingest SQL, and downstream manifest entries. That contract is still source-semantic, not silver: it does not perform cross-source conformance, survivorship, entity resolution, dimensional modeling, or business enrichment. It preserves source semantics without preserving avoidable source accidents such as flat-file string typing, ambiguous date encodings, or dump-format quirks.

**North Star**: One UMF compiles, deterministically and losslessly, into every committed runtime artifact a healthcare platform needs — with zero drift between the UMF and what runs.

An optional operational companion — the first-party Databricks App for guidebook browsing, profiling, comparison, and load results — helps platform operators inspect and work with governed schemas in a workspace. It does not replace the library, CLI, or committed-artifact runtime contract; portability of that app across environments is a first-class product requirement (FR-23).

## User Experience

A data engineer onboards a new claims table by editing (or inferring) its UMF. They run the compile step once. tablespec writes a pinned artifact layout: `ingest/<t>.ingest.sql`, `schemas/<t>.ddl.sql` / `.schema.py` / `.schema.json`, `validation/<t>.suite.json`, a single-table dbt ingest project, the multi-table gold dbt DAG, an LDP project, and the single-target gold SQL plan. The engineer reviews the generated transforms as ordinary diffs in code review. The runtime backbone then executes those committed artifacts — on classic Spark in CI, on Sail (local Spark Connect) in the test lane, and on Databricks serverless in production — without importing tablespec at run time. When a column type changes, they edit the UMF, recompile, and the change surfaces as a precise diff across the ingest SQL, the GX suite, and the dbt contract simultaneously.

An operator can also browse the same UMF set as a static HTML guidebook (FEAT-033) and, when the Databricks App is deployed, profile and compare tables against the declared metadata home without editing application source between environments (FEAT-034).

## Target Market

| Attribute | Description |
|-----------|-------------|
| Who | Data engineers and data-quality engineers on healthcare data platforms (Medicaid/MD, Medicare Part D/MP, Medicare/ME) |
| Pain | Schemas, transforms, and validation rules are maintained per-tool (SQL, PySpark, JSON Schema, GX, dbt, LDP) and drift apart; onboarding a table means redundant manual work in each system |
| Current Solution | Hand-authored DDL, PySpark schemas, GX suites, and dbt/LDP transforms maintained independently, reconciled by hand |
| Why They Switch | A single UMF source plus a deterministic compiler eliminates drift, makes transforms diffable, and removes the runtime's dependency on a schema library |

## Key Value Propositions

| Value Proposition | Customer Benefit |
|-------------------|------------------|
| UMF as single source of truth | One authoritative YAML per table; all schema representations derive from it (bidirectional where possible) |
| Source-semantic bronze contract | Raw records remain auditable while `ingested` artifacts become the properly typed, validated, keyed, relationship-aware representation of the source for downstream consumption |
| Compile to committed runtime artifacts | One UMF deterministically emits direct SQL (raw→ingest + gold plans), dbt projects (ingest + gold DAG), LDP projects, and GX suites — all reviewable as diffs |
| Compile-once, run-from-artifacts | Runtimes read committed artifacts, never re-derive from UMF; the transform is diffable and the runtime has no tablespec dependency (realized by the compile orchestrator + bootstrap pipeline — FEAT-026, decision ADR-012) |
| Multi-engine, Connect-safe execution | The same UMF runs first-class on classic Spark and on Databricks serverless / Spark Connect, with engine-correct dispatch and Connect-safe validation |
| Native, dependency-light profiling | Profiling uses standard Spark-SQL aggregations (no JVM, no Deequ) so it works on serverless / Connect and feeds GX expectations directly |
| Healthcare-domain awareness | Per-LOB nullable configuration (MD/MP/ME) and healthcare-specific validation/relationship patterns are first-class |

## Success Definition

| Metric | Target |
|--------|--------|
| Primary KPI | Zero drift between UMF definitions and the committed runtime artifacts that downstream systems execute |
| Compile coverage | One UMF compiles to the full committed artifact set (ingest SQL, DDL, PySpark, JSON Schema, GX suite, dbt ingest + gold DAG, LDP, gold plan) deterministically |
| Multi-engine parity | Identical results across classic Spark, Sail (local Connect), and Databricks serverless on the cross-engine conformance harness (the serverless lane runs in the opt-in tier when workspace credentials are configured — see PRD Success Criteria) |
| Manual-authoring reduction | At least 50% lower hand-authored GX/dbt/SQL transform and validation time per onboarded table, measured on the documented 3-table onboarding sample (see PRD Success Metrics) |
| Runtime independence | Production runtimes execute committed artifacts with no tablespec import at run time |

## Why Now

Databricks serverless and Spark Connect have made the JVM-bound, library-coupled runtime model untenable: code that assumes a classic `SparkContext` (PyDeequ profiling, GX `add_spark`) silently breaks on Connect. At the same time, dbt and Lakeflow Declarative Pipelines have made *committed, reviewable transforms* the expected shape of a data platform. tablespec is positioned to be the compiler that bridges these: one UMF source, a deterministic compile step to committed artifacts, and engine-correct execution on both classic Spark and serverless/Connect. Waiting means continuing to maintain per-tool schemas by hand and shipping runtime code that fails silently on the platforms teams are already migrating to.
