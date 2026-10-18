---
ddx:
  id: ADR-020
  links:
    - ADR-018
    - FEAT-033
    - US-046
---

# ADR-020: Interactive Guidebook with Transitive Column Lineage

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-09-29 | Accepted | David Mautz | FEAT-033, US-046, ADR-018 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The guidebook (ADR-018) shows only **one hop** of lineage: a derived column lists the candidate tables it reads, and a source column lists who reads it. The question users actually ask — "which source tables (and files, folders, or connections) does this report column ultimately come from?" — requires following derivations through every intermediate generated table, which the static per-table pages cannot answer. The long single-scroll pages (overview, columns table, then one engineering section per column) also make individual columns hard to find and compare. |
| Current State | `src/tablespec/guidebook/` renders one HTML page per table from the UMF models with inline CSS and no JavaScript (FR-22.2), plus indexes and a `search_index.json` that no page uses. |
| Requirements | FEAT-033 (Guidebook), PRD FR-22.1–FR-22.4, US-046. |
| Decision Drivers | Answer "where does this column ultimately come from" from UMF alone; keep the guidebook a static, offline, host-anywhere artifact; keep ADR-018's lineage semantics; mirror what `SQLPlanGenerator` actually compiles so lineage cannot drift from the SQL; one tool rather than a guidebook plus a separate lineage viewer. |

## Decision

1. **A design-time column-lineage engine** (`src/tablespec/lineage/`). A
   `LineageBuilder` walks each column's derivation candidates, recursively,
   through generated tables to **source tables** (any `table_type` other than
   `generated`), mirroring `SQLPlanGenerator`'s final-assembly semantics:
   `primary_key` / `base_column` read the base view (every `source_tables`
   entry for `union_sources`); candidates are followed in priority order with
   an `expression` winning over `column`; `union_branches` /
   `aggregate_source` project each column through its own candidates;
   `union_value` candidates are literals; `unpivot` value columns fan out to
   `unpivot_columns`; the base table is inferred the same way (hub score, then
   outgoing relationships, then first contributing table). Join keys and
   filters are recorded on edges but not followed. Each leaf carries its
   source location from `umf.effective_source()` (delimited folder / path,
   parquet or JSON path, JDBC URL + table) — the "source system". UMFs are read
   through a small provider protocol, defaulting to guidebook discovery
   (`DiscoveredUMFProvider`), so ids stay `group.table.column` (ADR-018).
2. **The guidebook becomes an interactive static site.** Every page is a thin
   shell: its payload is inline JSON, and shared vanilla JavaScript/CSS
   (`assets/site.js`, `assets/site.css`) plus `assets/catalog.js` render it.
   There are **no JS frameworks and no network requests**; assets load by
   relative `<script src>` so the site still works from `file://` or any static
   host. Page paths are unchanged (`index.html`, `<group>/index.html`,
   `<group>/<table>.html`); old `#col-<name>` anchors still open the column.
   `generate(..., self_contained=True)` inlines the assets into every page for
   single-page embedding (e.g. a srcdoc iframe).
3. **Navigation.** A left pane lists groups, tables, or a table's columns (with
   a filter and an up-one-level link); breadcrumbs show where you are; client
   search (`/` or Ctrl/⌘-K) covers every table and column. A table has
   *Overview* and *Sources* (list or diagram of every source table) tabs; a
   column has *Details*, *Lineage* (ultimate sources + path diagram),
   *Derivation* (candidates, filters, SQL, reasons, survivorship), *Used by*,
   and *Validation* tabs. State lives in the URL hash
   (`#col=<name>&tab=<tab>`). `search_index.json` is replaced by
   `assets/catalog.js`.
4. **ADR-018 semantics are kept.** FK stays downstream-only: a referenced
   column's *Used by* lists FK consumers marked `via fk` alongside derivation
   consumers; outgoing FKs appear only as *Joins* on the table overview, never
   as lineage sources. Discovery, grouping, and bare vs. qualified reference
   resolution are unchanged.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep static no-JS pages and add a "full lineage" section per column | No JavaScript | Transitive lineage for every column of every table multiplies page size; no diagram; still long scrolling pages | Rejected: does not scale and does not fix navigation |
| A separate lineage viewer next to the guidebook | Guidebook unchanged | Two tools with overlapping content and navigation; users must switch between them | Rejected: duplicate surfaces |
| A JS framework / graph library from a CDN | Rich widgets for less code | Violates offline / no-network; adds build tooling or third-party runtime | Rejected: the site must stay self-contained |
| Parse the compiled SQL (sqlglot) instead of UMF | Exact for the emitted SQL | Needs a compiled plan per table and dialect; loses UMF-level context (priority, reasons, filters) | Rejected: UMF derivations are the authored source of truth |
| **UMF lineage engine + vanilla-JS static site (selected)** | Answers the ultimate-source question; one tool; offline; lineage mirrors the SQL generator; ADR-018 semantics preserved | Pages need JavaScript; the engine must track `SQLPlanGenerator` semantics | **Selected** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Every column shows its ultimate source tables and locations and the path to them; tables show every source they depend on; columns are one click apart; search works offline; the lineage engine is reusable (`tablespec lineage` CLI, JSON output). |
| Negative | Pages render with JavaScript (a `<noscript>` note is shown otherwise); `search_index.json` is no longer emitted; lineage is design-time only (no runtime evidence of which files were loaded). |
| Neutral | Page paths and the `generate_guidebook` signature are unchanged; `self_contained` is an additive option. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Lineage drifts from `SQLPlanGenerator` as strategies evolve | M | M | Builder rules are documented against the generator; unit tests per strategy and a Synthea smoke test compare against the compiled plan's base table and sources |
| Expression tokenizing mis-reads an identifier | L | L | References are kept only when they resolve to a real UMF column; unresolved references surface as warnings on the page |
| Very large corpora produce a large `catalog.js` | L | L | Catalog holds names, types, and truncated descriptions only; per-table payloads stay inline in their own page |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| A derived column's lineage lists the source tables the compiled SQL reads | A lineage or Synthea smoke test fails |
| FK consumers appear as `via fk` in *Used by*, never as lineage sources | A guidebook generate test fails |
| Generated pages load no remote resources and work from `file://` | A render test finds a remote `src`/`href` |

## Supersession

- **Supersedes**: ADR-018 decision 3's rendering shape (static, JavaScript-free
  per-table HTML) and its out-of-scope interactive lineage view. ADR-018's
  decisions 1 (FK downstream-only; derivation bidirectional) and 2 (flat group
  discovery) remain in force.
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: The decision governs guidebook rendering and
  design-time lineage; no active-concern relevance.

## References

- FEAT-033 (Guidebook) — FR-22.1–FR-22.4; US-046
- ADR-018 (guidebook lineage semantics and flat discovery)
- `src/tablespec/lineage/` — `builder.py` (traversal), `expressions.py` (expression references), `providers.py` (discovery-backed provider, source location)
- `src/tablespec/guidebook/` — `generator.py`, `payloads.py`, `render.py`, `models.py`, `assets/`
- `src/tablespec/schemas/sql_generator.py`, `schemas/relationship_resolver.py` — the semantics the lineage builder mirrors

## Review Checklist

- [x] Context names a specific problem — one-hop lineage and hard-to-navigate pages
- [x] Decision statement is actionable (lineage engine; vanilla-JS static site; navigation; ADR-018 kept)
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-033 and PRD FR-22.1–FR-22.5
