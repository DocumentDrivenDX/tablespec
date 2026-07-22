---
ddx:
  id: feature-registry
---

# Feature Registry

**Status**: Active
**Last Updated**: 2026-07-22

## Active Features

| ID | Name | Description | Status | Priority | Owner | Source | Updated |
|----|------|-------------|--------|----------|-------|--------|---------|
| FEAT-001 | [UMF Models and I/O](features/FEAT-001-umf-models.md) | Type-safe Pydantic models for UMF plus YAML serialization and deserialization. | Built | P0 | Platform / Data Engineering | PRD: UMF Model and I/O (FR-1.1–FR-1.10) | 2026-06-11 |
| FEAT-002 | [Schema Generation](features/FEAT-002-schema-generation.md) | Generate schema definitions in multiple output formats from UMF metadata. | Built | P0 | Platform / Data Engineering | PRD: Schema Generation (FR-2.1–FR-2.3) | 2026-06-11 |
| FEAT-003 | [Type System Mappings](features/FEAT-003-type-mappings.md) | Central type conversion hub between UMF, PySpark, JSON Schema, and Great Expectations type systems. | Built | P0 | Platform / Data Engineering | PRD: Type Mappings (FR-3.1–FR-3.5) | 2026-06-11 |
| FEAT-004 | [Great Expectations Integration](features/FEAT-004-gx-integration.md) | Bidirectional GX integration: baseline generation, constraint extraction, schema validation, suite processing. | Built | P0 | Data-Quality Platform | PRD: Great Expectations Integration (FR-4.1–FR-4.7) | 2026-06-11 |
| FEAT-005 | [Profiling Integration (Schema Mapping + Legacy Path)](features/FEAT-005-profiling.md) | Map a Spark DataFrame's schema into UMF; legacy Deequ-style profile-to-UMF path retained as compatibility-only. | Built | P1 | Data Platform | PRD: Profiling Integration (FR-5.3, FR-5.4, FR-5.5) | 2026-06-11 |
| FEAT-006 | [LLM Prompt Generation](features/FEAT-006-llm-prompts.md) | Structured prompts for LLM-based schema enrichment: documentation, validation, relationships, survivorship. | Built | P1 | Data-Quality Platform | PRD: LLM Prompt Generation (FR-6.1–FR-6.7) | 2026-06-11 |
| FEAT-007 | [Table Validation](features/FEAT-007-validation.md) | Validate Spark DataFrames against UMF specs and UMF files against JSON schema; Connect-safe suite execution; includes table merge slice. | Built | P0 | Data-Quality Platform | PRD: Table Validation; Table Merge (FR-7.1–FR-7.8, FR-15.1–FR-15.3, with FR-20.4) | 2026-06-11 |
| FEAT-008 | [CLI Interface](features/FEAT-008-cli.md) | Typer-based `tablespec` CLI for schema management, conversion, and validation workflows with Rich output. | Built | P0 | Platform / Data Engineering | PRD: CLI Interface (FR-8.1–FR-8.6) | 2026-06-11 |
| FEAT-009 | [Excel Bidirectional Conversion](features/FEAT-009-excel-conversion.md) | Round-trip conversion between Excel workbooks and UMF schemas for non-technical domain expert collaboration, including lossless column-derivation round-trip (ADR-017). | Built | P1 | Data Stewardship | PRD: Excel Bidirectional Conversion (FR-9.1–FR-9.4) | 2026-06-15 |
| FEAT-010 | [UMF Change Management](features/FEAT-010-change-management.md) | Split-format UMF storage, schema diffing, atomic change application, and git-based changelog generation. | Built | P0 | Platform / Data Engineering | PRD: Split-Format UMF; Schema Change Management (FR-10.1–FR-10.4, FR-11.1–FR-11.5) | 2026-06-11 |
| FEAT-011 | [Sample Data Generation](features/FEAT-011-sample-data.md) | Generate realistic healthcare-specific sample data from UMF specs, respecting constraints, foreign keys, and domain types. | Built | P1 | Data-Quality Platform | PRD: Sample Data Generation (FR-12.1–FR-12.6) | 2026-06-11 |
| FEAT-012 | [Quality Baselines](features/FEAT-012-quality-baselines.md) | Capture, store, and compare quality baselines from DataFrames for drift detection; requires PySpark. | Built | P1 | Data-Quality Platform | PRD: Quality Baselines (FR-13.1–FR-13.5) | 2026-06-11 |
| FEAT-013 | [Domain Type Inference](features/FEAT-013-domain-inference.md) | Automatic detection of domain types from column names, descriptions, and sample values. | Built | P1 | Data Platform | PRD: Domain Type Inference (FR-14.1–FR-14.4) | 2026-06-11 |
| FEAT-014 | [Naming and Formatting Utilities](features/FEAT-014-naming-formatting.md) | Naming conventions, date format definitions, and YAML formatting utilities. | Built | P2 | Platform / Data Engineering | PRD: Naming Utilities; Date Format System (FR-16.1–FR-16.3, FR-17.1–FR-17.3) | 2026-06-11 |
| FEAT-015 | [Browsable API Documentation](features/FEAT-015-api-docs.md) | Auto-generated API documentation site (MkDocs + mkdocstrings) from docstrings and Pydantic Field descriptions. | Built | P1 | Platform / Data Engineering | Vision/Principles (meta-feature; documents the FR-1.x surface) | 2026-06-11 |
| FEAT-016 | [Testing Infrastructure for Agentic Development](features/FEAT-016-testing-infrastructure.md) | Testing infrastructure for fast iteration, property-based testing, and test-first development workflows. | Built | P0 | Engineering Productivity | Vision/Principles (meta-feature; evidence tier for FR-20.3) | 2026-06-11 |
| FEAT-017 | [Validation Pipeline Improvements](features/FEAT-017-validation-pipeline.md) | Fix structural validation pipeline issues: redundant expectations, missing execution paths, blocking behavior, reporting. | Built | P0 | Data-Quality Platform | PRD: Great Expectations Integration; Table Validation; Quality Baselines (FR-4.3, FR-7.5, FR-7.6, FR-13.3) | 2026-06-11 |
| FEAT-018 | [Custom GX Extensions](features/FEAT-018-gx-extensions.md) | Custom Great Expectations expectation classes that bridge tablespec domain concepts into GX execution. | Built | P0 | Data-Quality Platform | PRD: Table Validation (FR-7.5) | 2026-06-11 |
| FEAT-019 | [SQL Generator CTE Mode](features/FEAT-019-sql-cte-mode.md) | `mode` parameter on `SQLPlanGenerator` producing a single `WITH...SELECT` CTE statement instead of sequential temp views. | Built | P1 | Platform / Compilation | PRD: Multi-Target Emission (FR-19.4) | 2026-06-11 |
| FEAT-020 | [Domain Type System Improvements](features/FEAT-020-domain-improvements.md) | Domain inference improvements: better matching accuracy, richer results, codebase-wide consistency. | Built | P1 | Data Platform | PRD: Domain Type Inference (FR-14.1–FR-14.4) | 2026-06-11 |
| FEAT-021 | [UMF Loader & Validator Improvements](features/FEAT-021-loader-validator-improvements.md) | Improved error reporting and validation coverage in the UMF loading and validation pipeline. | Built | P1 | Platform / Data Engineering | PRD: UMF Model and I/O; Split-Format UMF (FR-1.7, FR-10.2, FR-10.3) | 2026-06-11 |
| FEAT-022 | [Schema Compatibility Checker](features/FEAT-022-schema-compatibility.md) | Analyze two UMF versions for backward/forward compatibility, reporting breaking changes with explanations. | Built | P1 | Platform / Data Engineering | PRD: Schema Change Management (FR-11.6) | 2026-06-11 |
| FEAT-023 | [Authoring Tools](features/FEAT-023-authoring-tools.md) | CLI commands, LLM integration, validation preview, and interactive TUI for authoring and managing UMF schemas. | Built | P1 | Platform / Data Engineering | PRD: CLI Interface; LLM Prompt Generation; Domain Type Inference (FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4) | 2026-06-11 |
| FEAT-024 | [Native Spark Profiler & Connect-Safe Runtime](features/FEAT-024-native-spark-profiler.md) | JVM-free, Connect-safe Spark-SQL profiling feeding GX suite composition; replaces the PyDeequ path (ADR-009). | Built | P0 | Data Platform | PRD: Profiling Integration (FR-5.1–FR-5.4) | 2026-06-10 |
| FEAT-025 | [Connect-Safe GX Suite Validation](features/FEAT-025-connect-safe-gx-validation.md) | Compiled GX suites execute with correct verdicts on Spark Connect and Databricks serverless as well as classic Spark. | Built | P0 | Data-Quality Platform | PRD: Table Validation (FR-7.7, FR-7.8, with FR-20.4) | 2026-06-10 |
| FEAT-026 | [Compile Orchestrator & Bootstrap Pipeline](features/FEAT-026-compile-orchestrator-bootstrap.md) | Compile a UMF set into the full set of committed runtime artifacts, with bootstrap Paths A/B producing the UMF set. | Built | P0 | Platform / Data Engineering | PRD: Compile Orchestration & Bootstrap (FR-18.1–FR-18.5) | 2026-06-10 |
| FEAT-027 | [dbt Project Emitter](features/FEAT-027-dbt-emitter.md) | Deterministically emit a complete dbt project (models, contracts, tests, scaffolding) from UMF on the shared emission core seam. | Built | P0 | Platform / Compile Team | PRD: Multi-Target Emission (FR-19.2, FR-19.1) | 2026-06-10 |
| FEAT-028 | [LDP Sibling Emitter](features/FEAT-028-ldp-sibling-emitter.md) | Emit a Lakeflow Declarative Pipelines project from a UMF set as a sibling backend on the shared target-agnostic core. | Built | P1 | Platform / Compilation | PRD: Multi-Target Emission (FR-19.3, FR-19.1) | 2026-06-10 |
| FEAT-029 | [Runtime Platform](features/FEAT-029-runtime-platform.md) | Connect-safe session capability probing and engine-correct `functions` dispatch. | Built | P0 | Data Platform | PRD: Runtime Platform (FR-20.1, FR-20.2, FR-20.3) | 2026-06-10 |
| FEAT-030 | [Product Microsite](features/FEAT-030-product-microsite.md) | Hugo/Hextra product microsite with reader-mode IA, source-semantic bronze explanation, demos, and Pages deployment that preserves `/simple/`. | Built | P1 | Platform / Developer Experience | Vision/Principles (meta-feature; governed by ADR-014) | 2026-07-22 |
| FEAT-031 | [Multi-Source Ingestion](features/FEAT-031-multi-source-ingestion.md) | Discriminated `source:` contract (delimited/parquet/jdbc/json) with kind-dependent raw typing, ingestion reader seam, JDBC compiled read specs, and database discovery; Northwind end-to-end is the acceptance goal. DUMP/PARQ/JDBC shipped; JSON compile/backbone residual + story floor remain. | Specified | P1 | Platform / Data Engineering | PRD: Source Acquisition (FR-21.1–FR-21.7); ADR-015 | 2026-07-22 |
| FEAT-032 | [Embeddings & Document Corpus](features/FEAT-032-embeddings-and-document-corpus.md) | Dimensioned EMBEDDING type compiling to ARRAY<FLOAT>, GX dimensionality validation, and the governed document-corpus contract; SEC 10-K demo is the acceptance goal. Type core + CORP example shipped; DEMO residual open. | In Build | P1 | Platform / Data Engineering | PRD: UMF Model and I/O (FR-1.11); ADR-016 | 2026-07-22 |
| FEAT-033 | [Guidebook](features/FEAT-033-guidebook.md) | Render a directory of UMFs into a navigable, self-contained HTML guidebook — one page per table — with column metadata, FK + derivation lineage, group/flat indexes, and search; CLI + `generate_guidebook` API. | Built | P1 | Platform / Developer Experience | PRD: Guidebook (FR-22.1–FR-22.4); ADR-018 | 2026-07-22 |
| FEAT-034 | [App Deployment & Configuration](features/FEAT-034-app-deployment-configuration.md) | Deploy the guidebook + profiling app into any Databricks environment: metadata location as declared input, idempotent provisioning of schema/volume/governance tables, and fail-fast startup validation. Desired state; implementation gaps tracked in alignment beads. | Specified | P1 | Platform / Developer Experience | PRD: App Deployment & Configuration (FR-23.1–FR-23.6) | 2026-07-22 |

## Status Definitions

- **Draft**: Requirements being gathered
- **Specified**: Feature spec complete (Frame done)
- **Designed**: Technical design complete (Design done)
- **In Test**: Tests being written
- **In Build**: Implementation in progress
- **Built**: Implementation complete
- **Deployed**: Released to production
- **Deprecated**: Scheduled for removal
- **Cancelled**: Will not be pursued

This repository's feature specifications record the **spec-lifecycle** status
(**Approved** / **Specified** / **Draft** per the feature-specification template
enum). **Delivery stage** is tracked only in this registry
(Draft / Specified / Designed / In Test / In Build / Built / Deployed / …).
Spec-lifecycle status does not imply delivery **Built**: a feature's spec may be
final while delivery is still Specified or In Build when residual work remains
(FEAT-032 is Approved / In Build; FEAT-031 and FEAT-034 are Specified on both
axes). Legacy FEAT-001–029 are Built; FEAT-030 and
FEAT-033 are Built; FEAT-032 type core is shipped with CORP/DEMO residual.

## Dependencies

Only dependencies explicitly recorded in the feature specification headers are
listed here.

| Feature | Depends On | Type | Notes |
|---------|------------|------|-------|
| FEAT-005 | FEAT-024 | Required | Native Connect-safe profiling is governed by FEAT-024; FEAT-005 retains only schema mapping and the legacy compatibility path. |
| FEAT-025 | FEAT-024 | Required | Reuses the Connect-safe runtime substrate (engine-correct dispatch, serverless session acquisition) established by FEAT-024. |
| FEAT-028 | FEAT-027 | Shared seam | Built on the shared target-agnostic core seam (FR-19.1), co-owned with the dbt emitter and governed at the seam by ADR-013. |
| FEAT-030 | FEAT-015 | Documentation integration | The microsite may link or embed API reference output, but API reference generation remains governed by FEAT-015. |

## Trace Links

| Feature | Spec | Stories | Designs | Tests | Release |
|---------|------|---------|---------|-------|---------|
| FEAT-001 | [features/FEAT-001-umf-models.md](features/FEAT-001-umf-models.md) | — | — | — | — |
| FEAT-002 | [features/FEAT-002-schema-generation.md](features/FEAT-002-schema-generation.md) | — | — | — | — |
| FEAT-003 | [features/FEAT-003-type-mappings.md](features/FEAT-003-type-mappings.md) | — | — | — | — |
| FEAT-004 | [features/FEAT-004-gx-integration.md](features/FEAT-004-gx-integration.md) | — | — | — | — |
| FEAT-005 | [features/FEAT-005-profiling.md](features/FEAT-005-profiling.md) | — | — | — | — |
| FEAT-006 | [features/FEAT-006-llm-prompts.md](features/FEAT-006-llm-prompts.md) | — | — | — | — |
| FEAT-007 | [features/FEAT-007-validation.md](features/FEAT-007-validation.md) | — | — | — | — |
| FEAT-008 | [features/FEAT-008-cli.md](features/FEAT-008-cli.md) | — | — | — | — |
| FEAT-009 | [features/FEAT-009-excel-conversion.md](features/FEAT-009-excel-conversion.md) | — | — | — | — |
| FEAT-010 | [features/FEAT-010-change-management.md](features/FEAT-010-change-management.md) | — | — | — | — |
| FEAT-011 | [features/FEAT-011-sample-data.md](features/FEAT-011-sample-data.md) | — | — | — | — |
| FEAT-012 | [features/FEAT-012-quality-baselines.md](features/FEAT-012-quality-baselines.md) | — | — | — | — |
| FEAT-013 | [features/FEAT-013-domain-inference.md](features/FEAT-013-domain-inference.md) | — | — | — | — |
| FEAT-014 | [features/FEAT-014-naming-formatting.md](features/FEAT-014-naming-formatting.md) | — | — | — | — |
| FEAT-015 | [features/FEAT-015-api-docs.md](features/FEAT-015-api-docs.md) | — | — | — | — |
| FEAT-016 | [features/FEAT-016-testing-infrastructure.md](features/FEAT-016-testing-infrastructure.md) | — | — | — | — |
| FEAT-017 | [features/FEAT-017-validation-pipeline.md](features/FEAT-017-validation-pipeline.md) | — | — | — | — |
| FEAT-018 | [features/FEAT-018-gx-extensions.md](features/FEAT-018-gx-extensions.md) | — | — | — | — |
| FEAT-019 | [features/FEAT-019-sql-cte-mode.md](features/FEAT-019-sql-cte-mode.md) | — | — | — | — |
| FEAT-020 | [features/FEAT-020-domain-improvements.md](features/FEAT-020-domain-improvements.md) | — | — | — | — |
| FEAT-021 | [features/FEAT-021-loader-validator-improvements.md](features/FEAT-021-loader-validator-improvements.md) | — | — | — | — |
| FEAT-022 | [features/FEAT-022-schema-compatibility.md](features/FEAT-022-schema-compatibility.md) | — | — | — | — |
| FEAT-023 | [features/FEAT-023-authoring-tools.md](features/FEAT-023-authoring-tools.md) | — | — | — | — |
| FEAT-024 | [features/FEAT-024-native-spark-profiler.md](features/FEAT-024-native-spark-profiler.md) | — | — | — | — |
| FEAT-025 | [features/FEAT-025-connect-safe-gx-validation.md](features/FEAT-025-connect-safe-gx-validation.md) | — | — | — | — |
| FEAT-026 | [features/FEAT-026-compile-orchestrator-bootstrap.md](features/FEAT-026-compile-orchestrator-bootstrap.md) | — | — | — | — |
| FEAT-027 | [features/FEAT-027-dbt-emitter.md](features/FEAT-027-dbt-emitter.md) | — | — | — | — |
| FEAT-028 | [features/FEAT-028-ldp-sibling-emitter.md](features/FEAT-028-ldp-sibling-emitter.md) | — | — | — | — |
| FEAT-029 | [features/FEAT-029-runtime-platform.md](features/FEAT-029-runtime-platform.md) | — | — | — | — |
| FEAT-030 | [features/FEAT-030-product-microsite.md](features/FEAT-030-product-microsite.md) | [user-stories/US-038-publish-product-microsite.md](user-stories/US-038-publish-product-microsite.md) | [../02-design/adr/ADR-014-product-microsite-pages-architecture.md](../02-design/adr/ADR-014-product-microsite-pages-architecture.md) | — | — |
| FEAT-031 | [features/FEAT-031-multi-source-ingestion.md](features/FEAT-031-multi-source-ingestion.md) | [user-stories/US-039-northwind-end-to-end.md](user-stories/US-039-northwind-end-to-end.md) | [../02-design/adr/ADR-015-source-shape-contract.md](../02-design/adr/ADR-015-source-shape-contract.md) | — | — |
| FEAT-032 | [features/FEAT-032-embeddings-and-document-corpus.md](features/FEAT-032-embeddings-and-document-corpus.md) | [user-stories/US-045-sec-10k-corpus-and-facts.md](user-stories/US-045-sec-10k-corpus-and-facts.md) | [../02-design/adr/ADR-016-embedding-type-array-float.md](../02-design/adr/ADR-016-embedding-type-array-float.md) | — | — |
| FEAT-033 | [features/FEAT-033-guidebook.md](features/FEAT-033-guidebook.md) | [user-stories/US-046-browse-schema-guidebook.md](user-stories/US-046-browse-schema-guidebook.md) | [../02-design/adr/ADR-018-guidebook-lineage-semantics.md](../02-design/adr/ADR-018-guidebook-lineage-semantics.md) | — | — |
| FEAT-034 | [features/FEAT-034-app-deployment-configuration.md](features/FEAT-034-app-deployment-configuration.md) | [user-stories/US-047-deploy-app-new-environment.md](user-stories/US-047-deploy-app-new-environment.md), [user-stories/US-048-provision-metadata-home.md](user-stories/US-048-provision-metadata-home.md), [user-stories/US-049-diagnose-misconfigured-deployment.md](user-stories/US-049-diagnose-misconfigured-deployment.md) | [../02-design/adr/ADR-019-app-configuration-precedence-and-provisioning-authority.md](../02-design/adr/ADR-019-app-configuration-precedence-and-provisioning-authority.md) | — | — |

"—" means the link is not tracked at the registry level; per-feature stories,
designs, and tests are recorded inside each feature specification (and in
`user-stories/`).

## Feature Categories

### UMF Core and Change Management
- FEAT-001: UMF Models and I/O
- FEAT-010: UMF Change Management
- FEAT-014: Naming and Formatting Utilities
- FEAT-021: UMF Loader & Validator Improvements
- FEAT-022: Schema Compatibility Checker

### Schema Generation, Compilation, and Emission
- FEAT-002: Schema Generation
- FEAT-003: Type System Mappings
- FEAT-019: SQL Generator CTE Mode
- FEAT-026: Compile Orchestrator & Bootstrap Pipeline
- FEAT-027: dbt Project Emitter
- FEAT-028: LDP Sibling Emitter

### Data Quality and Validation
- FEAT-004: Great Expectations Integration
- FEAT-007: Table Validation
- FEAT-012: Quality Baselines
- FEAT-017: Validation Pipeline Improvements
- FEAT-018: Custom GX Extensions
- FEAT-025: Connect-Safe GX Suite Validation

### Profiling and Runtime Platform
- FEAT-005: Profiling Integration (Schema Mapping + Legacy Path)
- FEAT-024: Native Spark Profiler & Connect-Safe Runtime
- FEAT-029: Runtime Platform

### Authoring and Enrichment
- FEAT-006: LLM Prompt Generation
- FEAT-008: CLI Interface
- FEAT-009: Excel Bidirectional Conversion
- FEAT-011: Sample Data Generation
- FEAT-013: Domain Type Inference
- FEAT-020: Domain Type System Improvements
- FEAT-023: Authoring Tools
- FEAT-031: Multi-Source Ingestion (source-shape contract, JDBC discovery)
- FEAT-032: Embeddings & Document Corpus (EMBEDDING type, SEC 10-K demo)

### Documentation and Testing
- FEAT-015: Browsable API Documentation
- FEAT-016: Testing Infrastructure for Agentic Development
- FEAT-030: Product Microsite

## ID Rules

1. Sequential numbering: FEAT-XXX (zero-padded 3 digits)
2. Never reuse IDs, even for cancelled features
3. Do not encode category or priority into the ID
4. Keep full behavior in Feature Specifications, not in this registry

## Deprecated/Cancelled

| ID | Name | Status | Reason | Date |
|----|------|--------|--------|------|
| None | None | None | None | None |
