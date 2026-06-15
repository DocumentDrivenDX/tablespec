---
ddx:
  id: ADR-018
---

# ADR-018: Guidebook Lineage Semantics and Flat UMF Discovery

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-15 | Accepted | David Mautz | FEAT-033, ADR-017 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The guidebook renders a directory of UMFs into a navigable HTML site. Two design questions had to be settled to make its lineage view correct and its discovery flexible: (1) what counts as "upstream" vs. "downstream" for a column, given UMF carries both foreign keys and multi-source derivations; and (2) how to find and organize UMFs when standalone tablespec — unlike the upstream pulseflow generator this was ported from — has **no pipeline concept**. |
| Current State | The generator was ported from pulseflow's `tools/guidebook/`, which was coupled to a pipeline→tables hierarchy via a `PipelineDiscovery` class (dependent on `pulseflow_core`, `pipeline.yaml`, and `Phase` layouts) and a `LineageReport` indirection. tablespec instead loads individual UMFs or directories of them (the CLI already discovers via `rglob("table.yaml")` / `rglob("*.umf.json")`). UMF columns carry `relationships.foreign_keys` (entity references) and `derivation.candidates` (value provenance, the same surface ADR-017 makes Excel-authorable and `SQLPlanGenerator` compiles). |
| Requirements | FEAT-033 (Guidebook), PRD FR-22.1–FR-22.4. |
| Decision Drivers | Lineage must read truthfully (a reference is not a value derivation); discovery must work for any UMF set without a pipeline concept; the renderer should read directly from the `UMF`/`UMFColumn` models (no heavyweight report layer); the original pulseflow lineage intent should be preserved where it was sound. |

## Decision

1. **FK is downstream-only; derivation is bidirectional.** A foreign key is an
   *entity reference* and is rendered as a **downstream consumer** on the
   *referenced* table ("who points at this hub?"). A *derivation* is *value
   provenance* and is rendered on the derived column as **upstream sources**
   (with the SQL expression and survivorship) AND on each source column as a
   **downstream consumer** (`via derivation`). The upstream cell is therefore
   built only from derivation candidates, never from outgoing FKs — surfacing a
   table's FK targets as "upstream provenance" would conflate references with
   value lineage and bury the real provenance signal. This preserves the
   original pulseflow lineage intent.
2. **Flat, recursive discovery with a group = parent subfolder.** Discovery
   walks a root directory for split `table.yaml` dirs and `*.umf.json`
   artifacts. Each UMF's **group** is its parent subfolder (empty at the root).
   Output nests as `<group>/<table>.html` when groups exist and is flat
   otherwise; lineage keys are `group.table.column`. A qualified cross-reference
   (`group.table`) links across groups; a bare reference resolves within the
   current group. This replaces pulseflow's `PipelineDiscovery` with no pipeline
   concept, while still reproducing a `pipeline/table.html` layout when the
   input happens to be organized into subfolders.
3. **Render directly from the UMF models.** The renderer consumes
   `UMF`/`UMFColumn` (via a thin per-column view), dropping pulseflow's
   `LineageReport`/`generate_lineage_report` indirection and its regex
   sample-value invention. The guidebook is a pure static renderer over UMF on
   disk — no execution state.

**Key Points**: Duplicate `(group, table)` pairs and UMFs that fail to load are
logged and skipped, never fatal. The interactive lineage graph and git-history
feed from pulseflow are deliberately **not** ported. Derivation data itself is
authorable through Excel via ADR-017, so the guidebook's upstream/SQL view and
the Excel round-trip share one derivation surface.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Make FKs bidirectional (FK targets shown as "upstream" on the source table) | More ERD-like; relationships visible from both ends on every table | Conflates entity references with value provenance; clutters the upstream cell with non-provenance edges and buries real derivation lineage | Rejected: semantically wrong for a *lineage* (provenance) view |
| Port `PipelineDiscovery` (keep the pipeline→tables hierarchy) | Closest parity with pulseflow; cross-pipeline qualifiers map directly | Depends on `pulseflow_core` / `pipeline.yaml` / `Phase`; imposes a pipeline concept tablespec does not have; not flexible for arbitrary UMF sets | Rejected: couples to absent infrastructure |
| Keep the `LineageReport` indirection layer | Mirrors the source; a stable intermediate the renderer reads | Heavyweight (cross-pipeline cache, sample-value invention, markdown export) for no benefit in a pure static renderer; another layer to keep in sync with the UMF model | Rejected: the renderer needs only a thin view of the UMF |
| **FK-downstream-only + flat group discovery + render-from-UMF (selected)** | Truthful lineage; works for any UMF directory with no pipeline concept; reproduces nested layout when subfolders exist; one model surface, no report layer | "group" is a weaker organizing concept than an explicit pipeline; a bare table name duplicated across groups stays ambiguous (as it did upstream) | **Selected: correct lineage semantics and flexible discovery with the least coupling** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Lineage reads truthfully (references vs. provenance kept distinct); the guidebook works for any UMF set — including catalog-bootstrapped UMFs — with no pipeline concept; nested `group/table.html` still appears when input is foldered; the renderer tracks the UMF model directly with no indirection to drift. |
| Negative | A bare table reference that exists in more than one group remains ambiguous (unchanged from the source); FK relationships are visible from the hub side only, not as "upstream" on the referencing table. |
| Neutral | The interactive graph and git-history feed are out of scope; derivation authoring fidelity is owned by ADR-017 (Excel round-trip), which this feature consumes. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Readers expect FK relationships to appear as "upstream" on the referencing table | M | L | Documented in the user guide and this ADR: FK = downstream-on-referenced; upstream is reserved for value provenance |
| Duplicate `(group, table)` silently overwrites a page | L | M | Discovery detects duplicates and skips the later one with a logged warning; covered by a unit test |
| A bare cross-group table reference resolves to the wrong group | L | M | Qualified `group.table` references resolve unambiguously; bare-name ambiguity is the same bounded case as the source generator |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| A referenced table's column lists its FK consumers as downstream (`via fk`); a derived column lists upstream sources + SQL | A guidebook lineage test fails |
| A foldered UMF set nests as `group/table.html`; a flat set renders flat with no per-group index | A discovery/layout test fails |
| A malformed or duplicate UMF is skipped with a warning and the run still completes | A guidebook-generate test fails |

## Supersession

- **Supersedes**: None.
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: The decision governs guidebook lineage semantics and
  UMF discovery; no active-concern relevance.

## References

- FEAT-033 (Guidebook) — FR-22.1–FR-22.4; US-046 (browse a schema as a guidebook)
- ADR-017 (machine-readable Excel Derivations sheet — makes the derivation surface this guidebook renders authorable/round-trippable)
- `src/tablespec/guidebook/` — `discovery.py` (flat discovery + group), `reverse_lineage.py` (derivation + FK inversion), `renderer.py` (render-from-UMF; FK downstream / derivation upstream)
- `src/tablespec/models/umf.py` — `relationships.foreign_keys` (entity references), `UMFColumnDerivation`/`DerivationCandidate` (value provenance)
- Upstream origin: pulseflow `packages/dev/src/pulseflow_dev/tools/guidebook/` (the `PipelineDiscovery` + `LineageReport` design this ADR deliberately departs from)

## Review Checklist

- [x] Context names a specific problem — lineage semantics (FK vs. derivation) and pipeline-free discovery
- [x] Decision statement is actionable (FK downstream-only; flat group discovery; render from UMF)
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-033 and PRD FR-22.1–FR-22.4
