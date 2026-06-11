---
ddx:
  id: FEAT-010
---

# FEAT-010: UMF Change Management

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-010
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: Split-Format UMF; Schema Change Management
**Covered PRD Requirements**: FR-10.1, FR-10.2, FR-10.3, FR-10.4, FR-11.1, FR-11.2, FR-11.3, FR-11.4, FR-11.5
**Cross-Subsystem Rationale**: Cross-subsystem workflow: git-friendly split storage, diffing, applying, dependency checks, and changelog generation are one schema-change workflow.

## Description

Split-format UMF storage, schema diffing, atomic change application, and git-based changelog generation.

## Components

### UMF Loader (`umf_loader.py`)
- `UMFLoader` - Load UMF from split (directory) or JSON format with auto-detection
- `UMFFormat` enum: SPLIT (default, git-friendly) and JSON (artifact standard)
- Legacy single-file YAML UMF documents are migration-only and are not auto-detected
- Bidirectional conversion between formats

### UMF Diff (`umf_diff.py`)
- `UMFDiff` - Compare two UMF versions
- Detects: column added/removed/modified, validation rule changes, metadata changes, relationship changes
- Change types: `UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`

### Change Applier (`umf_change_applier.py`)
- `apply_column_change()`, `apply_metadata_change()`, `apply_validation_change()`
- Returns modified deep copies for immutable change tracking

### Changelog Generator (`changelog_generator.py`)
- `ChangelogGenerator` - Git history-based changelog for table directories
- `YAMLDiffParser` - Detailed YAML diff parsing from git commits
- Structured output via `ChangeEntry` and `ChangeDetail` models

## Dependencies

- ruamel.yaml (split-format YAML)
- gitpython (changelog generation)
## User Stories

- [US-012 — Load UMF from Split-Format Directory](../user-stories/US-012-split-format-loading.md)
- [US-014 — Generate Changelog from Git History](../user-stories/US-014-generate-changelog.md)
- [US-015 — Diff Two UMF Versions](../user-stories/US-015-diff-umf-versions.md)
- [US-020 — Resolve Pipeline Dependencies](../user-stories/US-020-resolve-dependencies.md)

## Source

- `src/tablespec/umf_loader.py`
- `src/tablespec/umf_diff.py`
- `src/tablespec/umf_change_applier.py`
- `src/tablespec/changelog_generator.py`
- `src/tablespec/changelog_diff_parser.py`
- `src/tablespec/changelog_formatter.py`
- `src/tablespec/models/changelog.py`
