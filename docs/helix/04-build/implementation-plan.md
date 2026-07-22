---
ddx:
  id: implementation-plan
---

# Implementation Plan: tablespec

**Version**: 3.0
**Status**: Updated for the committed-artifact compiler + Connect-safe multi-engine runtime
**Last Updated**: 2026-06-12

This is the live build plan. `implementation-plan-v2.md` is the retired replacement note and points back here.

**Requirements**: [../01-frame/prd.md](../01-frame/prd.md)
**Architecture**: [../02-design/architecture.md](../02-design/architecture.md)
**Test Plan**: [../03-test/test-plan.md](../03-test/test-plan.md)

## Scope

This document covers the repo-level build surface for tablespec: packaging, formatter/linter/type-check gates, test execution, artifact handoff validation, and the source-module ordering that supports those workflows. It is a maintenance and sequencing guide for the shipped codebase, not a replacement for the PRD, feature specs, ADRs, or deployment checklist.

The prior March 2026 phase narrative is preserved in [implementation-plan-v2.md](implementation-plan-v2.md) as a tombstone. Keep this file focused on current build practice and current source-tree shape.

## Implementation Slices

1. Tooling and packaging: `uv`, Hatchling, Ruff, Pyright, pre-commit, and the build/install entrypoints in `Makefile` and `pyproject.toml`.
2. Compiler/runtime backbone: the core UMF model surface, type mapping, schema generation, validation, session discovery, and Spark session factory.
3. Emission and interoperability: dbt, LDP, Excel, changelog, bootstrap, merge, and compatibility surfaces that translate UMF into committed artifacts or external representations.
4. Analysis and synthesis: profiling, sample data, inference, expectation helpers, and prompt generation that feed the governed runtime.
5. Operator-facing utilities: CLI, TUI, formatting, naming, and change-management helpers that support repeatable maintenance work.

## Issue Decomposition

Use DDx beads for every change that crosses a boundary in this plan. Keep one bead per independently verifiable change: docs-only refresh, source inventory drift, build-tooling changes, runtime-surface changes, and test alignment should not be merged into a single catch-all issue unless they are inseparable.

When a change reveals follow-up work, create a new bead linked to the parent instead of extending the parent bead with unrelated scope. For build-plan work, the minimum useful split is usually documentation, source-tree update, and verification.

For live tracking, use `ddx bead ready --json`, `ddx bead status --json`, and `ddx bead show <id> --json` rather than snapshotting active work into this plan.

## Risks and Rollbacks

The main risk is drift: a plan that names modules or dates that no longer match `src/tablespec` is worse than no plan at all. The second risk is naming confusion between the live plan and the `-v2` tombstone; keep that distinction explicit in the file body and in tests.

Rollback for this document is simple: revert the doc change and keep `implementation-plan-v2.md` untouched. If the source tree changes, refresh this appendix in the same commit so the inventory does not become stale again.

## Appendix: Library Module Map (existing surface)

The inventory below mirrors the top-level `src/tablespec` surface exactly. Package rows stand in for their `__init__.py` namespace, and module rows are the leaf modules at the package root.

### Packages

| Path | Role |
| --- | --- |
| `authoring/` | Mutation preview and apply helpers. |
| `core/` | IR, registry, relations, schema-facts, and selection helpers. |
| `dbt/` | dbt project emitters, routing, registry, renderer, contracts, and selection helpers. |
| `e2e/` | Compile/bootstrap/manifest/runtime backbones for shipped artifacts. |
| `formatting/` | YAML formatter support. |
| `guidebook/` | Static HTML guidebook generation: UMF discovery, lineage, search index, and rendering. |
| `inference/` | Domain-type inference surface. |
| `ingestion/` | Raw/JDBC ingestion helpers and constants. |
| `ldp/` | LDP sibling emitter surface. |
| `models/` | UMF, quality, pipeline, and changelog models. |
| `profiling/` | Native and Spark profiling helpers. |
| `prompts/` | Prompt-generation helpers for authoring and validation. |
| `quality/` | Baseline storage, execution, and support services. |
| `sample_data/` | Sample data generation and validation helpers. |
| `schemas/` | SQL, dbt, ingest, and schema-generation helpers plus schema artifacts. |
| `validation/` | GX and native validation executors and reporting. |

### Modules

| Path | Role |
| --- | --- |
| `bootstrap.py` | Bootstrap committed artifacts from tables. |
| `canonical.py` | Canonical ordering and normalization helpers. |
| `casting_utils.py` | Connect-aware casting helpers. |
| `changelog_diff_parser.py` | Parse changelog diffs. |
| `changelog_formatter.py` | Format changelog output. |
| `changelog_generator.py` | Generate changelog content. |
| `cli.py` | Command-line entrypoint. |
| `compatibility.py` | Compatibility checks and reporting. |
| `completeness_validator.py` | Completeness validation. |
| `date_formats.py` | Date-format definitions and conversion helpers. |
| `dependency_resolver.py` | Dependency resolution for the runtime pipeline. |
| `dialects.py` | SQL dialect helpers. |
| `excel_converter.py` | Excel round-trip conversion. |
| `excel_import_git.py` | Git-aware Excel import. |
| `expectation_migration.py` | Expectation migration helpers. |
| `expectation_utils.py` | Expectation utility helpers. |
| `format_utils.py` | Formatting utilities. |
| `gx_baseline.py` | Baseline expectation generation. |
| `gx_constraint_extractor.py` | Constraint extraction from GX suites. |
| `gx_schema_validator.py` | GX schema validation. |
| `gx_wrapper.py` | GX wrapper utilities. |
| `merge.py` | Spark-based merge implementation. |
| `naming.py` | Naming utilities. |
| `naming_validator.py` | Naming validation. |
| `output_formatting.py` | Output formatting helpers. |
| `relationship_validator.py` | Relationship validation. |
| `session.py` | Spark-session discovery and capability probing. |
| `spark_factory.py` | Spark session factory and Delta bootstrap. |
| `survivorship_display.py` | Survivorship display helpers. |
| `sync_baseline.py` | Baseline synchronization. |
| `tui.py` | Terminal UI. |
| `type_lattice.py` | Type lattice helpers. |
| `type_mappings.py` | Type conversion hub. |
| `umf_change_applier.py` | Atomic UMF change application. |
| `umf_diff.py` | UMF version comparison. |
| `umf_loader.py` | UMF loading and format detection. |
| `umf_validator.py` | UMF validation. |
| `validator.py` | Validation orchestration. |
