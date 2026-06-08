---
ddx:
  id: FEAT-008
---

# FEAT-008: CLI Interface

**Status**: Implemented
**Priority**: P0
**Feature ID**: FEAT-008
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: CLI Interface
**Covered PRD Requirements**: FR-8.1, FR-8.2, FR-8.3, FR-8.4, FR-8.5, FR-8.6
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Typer-based CLI (`tablespec` command) for schema management, conversion, and validation workflows with Rich output formatting.
Canonical authoring inputs are split-format UMF directories and JSON artifacts; single-file YAML UMF documents are legacy migration inputs only.

## Commands

- **`convert`** - Convert UMF between formats (JSON, split, Excel). Auto-detects input format.
- **`validate`** - Validate a UMF schema with optional pipeline context
- **`info`** - Display summary of a UMF schema (table name, column count, types)
- **`batch-convert`** - Convert all UMF files in a directory to a target format
- **`changelog`** - Generate changelog from git history for a table directory
- **`sync`** - Synchronize baseline validations across table definitions

## Planned Commands

- **`generate`** - Generate SQL DDL, PySpark schema, or JSON Schema from UMF. Supports `--format sql|pyspark|json` and stdout output for piping into CI scripts.

## Dependencies

- typer (CLI framework)
- rich (terminal formatting)
- Conditional: validator module for validate/convert/info commands
## User Stories

- [US-010 — Convert UMF Formats via CLI](../user-stories/US-010-convert-umf-via-cli.md)

## Source

- `src/tablespec/cli.py`
