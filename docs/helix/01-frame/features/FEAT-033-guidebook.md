---
ddx:
  id: FEAT-033
  links:
    - ADR-018
    - ADR-020
    - US-046
---

# Feature Specification: FEAT-033 — Guidebook

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-033
**Owner**: Platform / Developer Experience
**Covered PRD Subsystem(s)**: Guidebook
**Covered PRD Requirements**: FR-22.1, FR-22.2, FR-22.3, FR-22.4, FR-22.5
**Cross-Subsystem Rationale**: None — single subsystem.

## Overview

Render a directory of UMFs into a navigable static "guidebook" site — one page
per table — so engineers and analysts can browse a schema, its columns, and
where every column's data ultimately comes from, without reading YAML.

## Ideal Future State

A data engineer points `tablespec guidebook` (or `generate_guidebook`) at any
directory of UMFs and gets a browsable site: each table page shows column
metadata, the source tables each column ultimately reads (with their location
and the derivation path), derivation candidates with their SQL and
survivorship, foreign-key and derivation consumers, and validation rules; the
site has group/flat navigation and offline search; and it works from disk or
any static host. The capability is governed here so downstream specs,
tests, and agents share one contract.

## Problem Statement

- **Current situation**: UMFs are git-friendly YAML/JSON. Understanding a
  multi-table schema and its lineage meant reading many files by hand.
- **Pain points**: No browsable, link-followable view of a schema; lineage
  (which tables reference or derive from which) was implicit in the YAML.
- **Desired outcome**: A self-contained HTML guidebook generated from any UMF
  directory, surfacing per-column metadata and bidirectional lineage, usable
  offline and hostable anywhere.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Discovery | Which UMFs go in the guidebook and how are they grouped? | Flatly and recursively discover split `table.yaml` dirs and `*.umf.json` artifacts under a root; group output by parent subfolder when present, flat otherwise; skip duplicate/malformed UMFs with a logged warning. |
| Rendering | What does a table page show? | One page per table in a static site (vanilla JS/CSS as local assets, no frameworks, no network) with column metadata, plus home/group pages and client search over a bundled catalog; optionally self-contained single pages. |
| Lineage | How do tables relate, and where does a column's data come from? | Foreign keys render as downstream consumers on the referenced table; derivations render as upstream sources (with SQL expression + survivorship) on the derived column; each column is traced transitively to the source tables it ultimately reads (ADR-020). |
| Entry points | How do I run it? | `tablespec guidebook` CLI command and `generate_guidebook` Python API. |

## Requirements

### Functional Requirements by Area

#### Discovery

F033-DISC-01. The feature SHALL discover UMFs recursively under a root directory, accepting split-format directories (containing `table.yaml`) and `*.umf.json` artifacts, and SHALL group each UMF's output by its parent subfolder (flat when all UMFs sit at the root).
F033-DISC-02. The feature SHALL skip a duplicate `(group, table)` pair or a UMF that fails to load with a logged warning, without aborting the run.

#### Rendering

F033-REND-01. The feature SHALL render one page per table as a static site (vanilla JavaScript and CSS shipped as local assets; no JS frameworks, no network requests) presenting per-column metadata (type, length, format, description, sample values) and validation rules, and SHALL optionally emit self-contained single pages.
F033-REND-02. The feature SHALL emit a home page (grouped or flat), per-group pages when groups exist, and a bundled catalog enabling client-side search over tables and columns.

#### Lineage

F033-LIN-01. The feature SHALL render foreign keys as downstream consumers on the referenced table.
F033-LIN-02. The feature SHALL render column derivations as upstream sources on the derived column, including the SQL expression (with priority and join filter for multi-candidate columns) and survivorship logic (ADR-018).
F033-LIN-03. The feature SHALL trace each column transitively through generated tables to the source tables it ultimately reads, with each source's location and the derivation path, mirroring `SQLPlanGenerator` semantics (ADR-020).

#### Entry points

F033-ENTRY-01. The feature SHALL expose generation through the `tablespec guidebook` CLI command and the `generate_guidebook` Python API, and lineage through the `tablespec lineage` CLI command.

### Non-Functional Requirements

- **Performance**: No feature-specific runtime target; generation is offline static rendering.
- **Security**: Output makes no network requests; the feature SHALL not introduce external-service calls or new data exposure beyond reading the UMFs it is pointed at.
- **Scalability**: One bad UMF SHALL NOT abort a multi-table run (per F033-DISC-02).
- **Reliability**: The guidebook is regenerable and deterministic from a fixed UMF set plus an optional caller-supplied timestamp/SHA.

### Existing Scope Evidence

#### Components

##### Discovery (`tablespec/guidebook/discovery.py`)
- Flat recursive discovery; `(group, table)` identity; duplicate/malformed skip with warning

##### Column lineage (`tablespec/lineage/`)
- `LineageBuilder` traces derivations through generated tables to source tables (`builder.py`), resolving expression references (`expressions.py`) over a discovery-backed provider with source locations (`providers.py`)

##### Page payloads (`tablespec/guidebook/payloads.py`, `models.py`)
- Table/column payloads built directly from the `UMF`/`UMFColumn` models plus the lineage graph; derivation + foreign-key "used by" inversion; the navigation/search catalog

##### Site rendering (`tablespec/guidebook/render.py`, `assets/`)
- HTML shells with inline JSON payloads; shared `site.js`/`site.css` (navigation, tabs, search, lineage diagrams); self-contained mode

##### Orchestrator + entry points (`tablespec/guidebook/generator.py`, `cli.py`, `__init__.py`)
- `generate` orchestrator; `tablespec guidebook` and `tablespec lineage` CLI commands; `generate_guidebook` public export

## User Stories

- [US-046 — Browse a Schema as a Guidebook](../user-stories/US-046-browse-schema-guidebook.md)

## Edge Cases and Error Handling

- **Malformed or duplicate UMF**: logged and skipped; the run continues (F033-DISC-02).
- **Flat vs grouped layout**: when every UMF is at the root, output is flat and per-group indexes are omitted.
- **Missing story coverage**: requirement-level behavior changes update the story rather than adding acceptance criteria to this feature spec (ADR-009).

## Success Metrics

- 100% of cited source paths continue to exist or are replaced in the same change that moves them.
- A guidebook regenerates from a fixed UMF directory deterministically (modulo an optional caller-supplied timestamp).
- Documentation conformance checks pass for the required HELIX feature-specification sections.

## Constraints and Assumptions

- The guidebook is a non-Spark feature; it reads UMFs already on disk.
- Generating UMFs from a Databricks catalog is a documented two-step flow (bootstrap/discover UMFs, then run the guidebook) reusing existing features, not new behavior in this feature.
- Exact CLI/API surface is owned by the implementation; this spec records the product-level capability boundary.

## Dependencies

- **Other features**: FEAT-001 (UMF models / loader) for reading UMFs; consumes the same `derivation`/relationship surface that FEAT-009 round-trips and `SQLPlanGenerator` compiles.
- **External services**: None. New runtime dependency: `sqlparse` (SQL formatting).
- **PRD requirements**: FR-22.1, FR-22.2, FR-22.3, FR-22.4

### Existing Dependency Evidence

- sqlparse
- `tablespec.umf_loader` (UMF discovery/load)

### Source Evidence

- `src/tablespec/guidebook/` (`discovery.py`, `generator.py`, `payloads.py`, `models.py`, `render.py`, `prose.py`, `sql_format.py`, `assets/site.js`, `assets/site.css`, `__init__.py`)
- `src/tablespec/lineage/` (`builder.py`, `expressions.py`, `models.py`, `providers.py`, `__init__.py`)
- `src/tablespec/cli.py` (`guidebook` and `lineage` commands), `src/tablespec/__init__.py` (`generate_guidebook` export)
- `tests/unit/test_guidebook_discovery.py`, `test_guidebook_generate.py`, `test_guidebook_payloads.py`, `test_guidebook_render.py`, `test_guidebook_synthea.py`, `test_guidebook_prose.py`, `test_guidebook_sql_format.py`, `test_lineage_builder.py`, `test_lineage_expressions.py`, `test_lineage_providers.py`
- `examples/synthea/` (worked example: specs → UMFs → guidebook)

### Design Decisions

- ADR-018 (guidebook lineage semantics: FK downstream-only vs. derivation bidirectional; flat-discovery + group model). Cross-references ADR-017 (the Excel derivation round-trip that makes derivation data authorable).
- ADR-020 (interactive static site and transitive column lineage; supersedes ADR-018's JavaScript-free rendering shape).

## Out of Scope

- A git-history "recently changed" feed and PDF export (present in the upstream pulseflow generator; deliberately not ported).
- Runtime lineage evidence (which files or rows were actually loaded); lineage is design-time, from UMF.
- Generating UMFs from a live catalog as part of this feature (documented two-step flow using existing features).
- Defining exact CLI flags / API signatures inline (owned by implementation / contract artifacts).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements are listed when known.
- [x] Functional areas are subordinate parts of this feature's capability.
- [x] Overview and requirements are source-backed by cited evidence.
- [x] Acceptance criteria remain in the user story, not this feature spec.
- [x] Dependencies and source evidence reference existing artifacts.
- [x] Design decisions link to the governing ADR.
