# Phase 1: Frame

Requirements and problem definition for tablespec.

## Project-Level Artifacts

- [PRD](prd.md) - Product Requirements Document
- [Principles](principles.md) - Design principles
- [Concerns](concerns.md) - Active project concerns
- [Feature Registry](feature-registry.md) - Canonical feature index

## Feature Specifications

### Core (original codebase)
- [FEAT-001](features/FEAT-001-umf-models.md) - UMF Models and I/O
- [FEAT-002](features/FEAT-002-schema-generation.md) - Schema Generation
- [FEAT-003](features/FEAT-003-type-mappings.md) - Type System Mappings
- [FEAT-004](features/FEAT-004-gx-integration.md) - Great Expectations Integration
- [FEAT-005](features/FEAT-005-profiling.md) - Profiling Integration
- [FEAT-006](features/FEAT-006-llm-prompts.md) - LLM Prompt Generation
- [FEAT-007](features/FEAT-007-validation.md) - Table Validation

### Extended (post-merge additions)
- [FEAT-008](features/FEAT-008-cli.md) - CLI Interface
- [FEAT-009](features/FEAT-009-excel-conversion.md) - Excel Bidirectional Conversion
- [FEAT-010](features/FEAT-010-change-management.md) - UMF Change Management
- [FEAT-011](features/FEAT-011-sample-data.md) - Sample Data Generation
- [FEAT-012](features/FEAT-012-quality-baselines.md) - Quality Baselines
- [FEAT-013](features/FEAT-013-domain-inference.md) - Domain Type Inference
- [FEAT-014](features/FEAT-014-naming-formatting.md) - Naming and Formatting Utilities
- [FEAT-015](features/FEAT-015-api-docs.md) - Browsable API Documentation
- [FEAT-016](features/FEAT-016-testing-infrastructure.md) - Testing Infrastructure for Agentic Development
- [FEAT-017](features/FEAT-017-validation-pipeline.md) - Validation Pipeline Improvements
- [FEAT-018](features/FEAT-018-gx-extensions.md) - Custom GX Extensions
- [FEAT-019](features/FEAT-019-sql-cte-mode.md) - SQL Generator CTE Mode
- [FEAT-020](features/FEAT-020-domain-improvements.md) - Domain Type System Improvements
- [FEAT-021](features/FEAT-021-loader-validator-improvements.md) - UMF Loader & Validator Improvements
- [FEAT-022](features/FEAT-022-schema-compatibility.md) - Schema Compatibility Checker
- [FEAT-023](features/FEAT-023-authoring-tools.md) - Authoring Tools

### Runtime & Compilation (serverless/Connect)
- [FEAT-024](features/FEAT-024-native-spark-profiler.md) - Native Spark Profiler & Connect-Safe Runtime
- [FEAT-025](features/FEAT-025-connect-safe-gx-validation.md) - Connect-Safe GX Suite Validation
- [FEAT-026](features/FEAT-026-compile-orchestrator-bootstrap.md) - Compile Orchestrator & Bootstrap Pipeline
- [FEAT-027](features/FEAT-027-dbt-emitter.md) - dbt Project Emitter
- [FEAT-028](features/FEAT-028-ldp-sibling-emitter.md) - LDP Sibling Emitter
- [FEAT-029](features/FEAT-029-runtime-platform.md) - Runtime Platform

## User Stories

### FEAT-001: UMF Models and I/O
- [US-001](user-stories/US-001-load-and-validate-umf-schema.md) - Load and Validate a UMF Schema from YAML
- [US-002](user-stories/US-002-construct-umf-programmatically.md) - Construct a UMF Schema Programmatically

### FEAT-002: Schema Generation
- [US-003](user-stories/US-003-generate-sql-ddl-from-umf.md) - Generate SQL DDL from a UMF Schema

### FEAT-003: Type Mappings
- [US-004](user-stories/US-004-convert-types-between-systems.md) - Convert Column Types Between Type Systems

### FEAT-004: GX Integration
- [US-005](user-stories/US-005-generate-gx-baseline-from-umf.md) - Generate a Great Expectations Baseline from UMF
- [US-006](user-stories/US-006-extract-umf-constraints-from-gx-suite.md) - Extract UMF Constraints from an Existing GX Suite

### FEAT-005: Profiling
- [US-007](user-stories/US-007-convert-profiling-results-to-umf.md) - Convert Profiling Results to UMF

### FEAT-006: LLM Prompts
- [US-008](user-stories/US-008-generate-llm-prompts-for-schema-enrichment.md) - Generate LLM Prompts for Schema Enrichment

### FEAT-007: Validation
- [US-009](user-stories/US-009-validate-dataframe-against-umf.md) - Validate a DataFrame Against a UMF Schema
- [US-018](user-stories/US-018-merge-tables.md) - Merge Table Files with Survivorship

### FEAT-008: CLI Interface
- [US-010](user-stories/US-010-convert-umf-via-cli.md) - Convert UMF Formats via CLI

### FEAT-009: Excel Conversion
- [US-011](user-stories/US-011-excel-round-trip.md) - Round-Trip UMF Through Excel

### FEAT-010: UMF Change Management
- [US-012](user-stories/US-012-split-format-loading.md) - Load UMF from Split-Format Directory
- [US-014](user-stories/US-014-generate-changelog.md) - Generate Changelog from Git History
- [US-015](user-stories/US-015-diff-umf-versions.md) - Diff Two UMF Versions
- [US-020](user-stories/US-020-resolve-dependencies.md) - Resolve Pipeline Dependencies

### FEAT-011: Sample Data Generation
- [US-013](user-stories/US-013-generate-sample-data.md) - Generate Sample Data from UMF

### FEAT-012: Quality Baselines
- [US-016](user-stories/US-016-capture-quality-baseline.md) - Capture and Compare Quality Baselines
- [US-019](user-stories/US-019-sync-baselines.md) - Sync Baseline Validations Across Tables

### FEAT-013: Domain Type Inference
- [US-017](user-stories/US-017-infer-domain-types.md) - Infer Domain Types for Columns

### FEAT-014: Naming and Formatting Utilities
- [US-027](user-stories/US-027-normalize-names-and-date-formats.md) - Normalize Names and Date Formats

### FEAT-015: Browsable API Documentation
- [US-028](user-stories/US-028-publish-browsable-api-docs.md) - Publish Browsable API Documentation

### FEAT-016: Testing Infrastructure
- [US-029](user-stories/US-029-maintain-agentic-test-infrastructure.md) - Maintain Agentic Test Infrastructure

### FEAT-017: Validation Pipeline Improvements
- [US-030](user-stories/US-030-run-validation-pipeline-with-blocking-reports.md) - Run Validation Pipeline with Blocking Reports

### FEAT-018: Custom GX Extensions
- [US-031](user-stories/US-031-validate-custom-gx-expectations.md) - Validate Custom GX Expectations

### FEAT-019: SQL Generator CTE Mode
- [US-032](user-stories/US-032-generate-single-statement-sql-plan.md) - Generate a Single-Statement SQL Plan

### FEAT-020: Domain Type System Improvements
- [US-033](user-stories/US-033-improve-domain-type-inference.md) - Improve Domain Type Inference

### FEAT-021: UMF Loader & Validator Improvements
- [US-034](user-stories/US-034-load-and-validate-umf-with-clear-errors.md) - Load and Validate UMF with Clear Errors

### FEAT-022: Schema Compatibility Checker
- [US-035](user-stories/US-035-check-schema-compatibility.md) - Check Schema Compatibility

### FEAT-023: Authoring Tools
- [US-036](user-stories/US-036-author-umf-with-cli-and-llm-assistance.md) - Author UMF with CLI and LLM Assistance

### FEAT-024: Native Spark Profiler
- [US-021](user-stories/US-021-profile-dataframe-natively-on-connect.md) - Profile a DataFrame Natively on Spark Connect

### FEAT-025: Connect-Safe GX Validation
- [US-022](user-stories/US-022-validate-suite-on-connect-without-silent-failure.md) - Validate a Compiled Suite on Spark Connect Without Silent Failure

### FEAT-026: Compile Orchestrator & Bootstrap
- [US-023](user-stories/US-023-bootstrap-runtime-from-umf-set.md) - Bootstrap a Runtime from a UMF Set (Path A / Path B)
- [US-024](user-stories/US-024-runtime-consumes-only-compiled-artifacts.md) - Runtime Consumes Only Compiled Artifacts

### FEAT-027: dbt Project Emitter
- [US-025](user-stories/US-025-emit-dbt-project-from-umf.md) - Emit a dbt Project from UMF

### FEAT-028: LDP Sibling Emitter
- [US-026](user-stories/US-026-emit-ldp-project-from-umf.md) - Emit an LDP Project from a UMF Set

### FEAT-029: Runtime Platform
- [US-037](user-stories/US-037-engine-correct-runtime-dispatch.md) - Engine-Correct Runtime Dispatch

## Status

- Frame phase backfilled from existing codebase and documentation (2026-03-15).
- Updated for post-merge codebase with ~50 new source files across 4 new packages (2026-03-16).
- Index refreshed to cover FEAT-001..FEAT-029 and US-001..US-037 (2026-06-10).
