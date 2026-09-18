---
ddx:
  id: ADR-020
---

# ADR-020: Domains as Bounded Contexts (domain.yaml, exports, suppliers, glossary)

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-09-15 | Accepted | Erik LaBianca | FEAT-035, ADR-018, ADR-013 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | tablespec had three names for the same organizing slot and no owner for any of them. The core registry called the qualifier in `ns.table` a *namespace*, the guidebook called the same directory a *group* (ADR-018), and the foreign-key model called it `references_pipeline`. None of them carried an owner, a published surface, or a vocabulary. Cross-directory references were routed by string prefix and never validated against anything. A `pipeline.yaml` model existed but had no consumer in the library. |
| Current State | `PipelineMetadata` (`models/pipeline.py`) and `DependencyResolver` are dead code; the resolver's own error text promises an `exports` field that does not exist. `ForeignKey.cross_pipeline` and `references_pipeline` are read by the registry, the resolver, the guidebook, and Excel round-trip, so they cannot be removed. Validation sees only sibling tables in one directory (`validator.py`), so no rule can span directories. Nested models silently drop unknown keys (`ForeignKey` had no `model_config`). |
| Requirements | FEAT-035; PRD FR-24.1–FR-24.5. |
| Decision Drivers | One name for the unit; a declared published surface so cross-domain references can be checked, not merely routed; vocabulary that data engineers new to tablespec can look up (DDD strategic patterns); no change to emitted artifacts or routing (ADR-013, concerns register: no hardcoded catalogs); no collision with the existing line-of-business "context" axis (`nullable` keys, `context_column`). |

## Decision

1. **The unit is a *domain*, declared by `domain.yaml`.** A domain is a
   directory of UMF tables with a `domain.yaml` at its root. Its `name` must
   equal the directory name. That one name is simultaneously the guidebook
   group (ADR-018 decision 2 is kept, not replaced: a domain directory *is* a
   group), the qualifier in `domain.table` references, and the value of
   `ForeignKey.references_domain`. "Namespace", "group", and "pipeline" are
   retired as *concepts*; the code paths that read them keep working because
   the domain name flows into the same fields.
2. **Exports are the published language; an exported table is an aggregate
   root.** `domain.yaml -> exports` lists the only tables another domain may
   reference, and every exported table must declare a `primary_key`. A
   cross-domain foreign key must target an exported table's primary-key
   column. Non-exported tables are internal to the domain.
3. **Suppliers are the context map.** `domain.yaml -> suppliers` names the
   domains this one consumes from, each with a DDD `pattern`
   (`customer_supplier`, `conformist`, `anti_corruption`, `shared_kernel`,
   `partnership`, `open_host`, `separate_ways`) and the `consumes` tables. Only
   the consumer declares the edge. The words are **supplier** and
   **consumer**; the guidebook's *upstream/downstream* stay reserved for value
   provenance (ADR-018 decision 1).
4. **Glossary terms are a new field, not a new meaning for `canonical_name`.**
   `domain.yaml -> glossary` names a term file; `UMF.term` and
   `UMFColumn.term` resolve against it. `canonical_name` keeps its source-spec
   meaning (it is a CSV header, an IR relation name, and an Excel key).
5. **Foreign keys gain `references_domain` and `integration`, and forbid
   extras.** `references_pipeline` is kept as a legacy alias, reconciled in
   one direction only: a key that uses `references_domain` also gets
   `references_pipeline` and `cross_pipeline=True` so every existing reader
   treats it as cross-domain; a key that uses only the legacy spelling is
   left exactly as authored, so existing specs load, save, and compile
   unchanged. `target_domain` reads either spelling; disagreement between the
   two is an error. `ForeignKey` now has `extra="forbid"` so an unknown key
   fails on load instead of vanishing on save.
6. **Domains do not drive routing.** No emitter reads `domain.yaml` to choose
   a catalog or schema. ADR-013's name-to-node seam and the "no hardcoded
   catalogs" concern stand unchanged.
7. **Validation spans domains through one entry point, with no mode.**
   `tablespec validate <path>` validates every table beneath the path at any
   depth, and applies the cross-domain rules (`DOM-EXPORT`, `DOM-SUPPLIER`,
   `DOM-XREF`, `DOM-TERM`, and the advisory `DOM-DRIFT`) whenever a
   `domain.yaml` applies to the path: the path is a domain, is inside one, or
   has domains beneath it. Sibling domains are always loaded from the
   directory that holds them, because a consumer's supplier lives next to it,
   not beneath it; findings are then narrowed to what the path covers. A
   first implementation switched `validate` into a separate mode when
   `domain.yaml` sat at or directly under the path. That made a metadata file
   decide whether tables were validated at all, and reported a lone domain's
   suppliers as "not found". It was removed before release.

**Key Points**: `domain_type` on a column is read as a value-object type scoped
to a domain; the global registry is unchanged in this decision (per-domain
registries are a follow-up). The `pipeline.yaml` model is left in place and
untouched; nothing new reads it.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Name the unit *context* (`context.yaml`, "bounded context") | Matches DDD literature exactly | "Context" already means line of business in this codebase: `nullable` keys are "context keys", `context_column` names the column holding them, `ForeignKey.domain_context` is prose. Two opposite meanings of one word in the same YAML | Rejected: collides with a shipped axis; "domain" is the word Erik chose for the DDD grouping (2026-09-15) |
| Revive `pipeline.yaml` and add `exports` to it | Model and loader already exist; resolver text promises `exports` | "Pipeline" has four unreconciled meanings (a Lakeflow project, a phase counter, a dependency unit, an emitted artifact); ADR-018 records that tablespec has no pipeline concept; the model has no `model_config` so extras are dropped | Rejected: keeps the name that caused the confusion; `references_pipeline` survives only as an alias |
| Route catalog/schema from the domain (dbt `models:` config, LDP catalog) | One declaration drives placement | Contradicts ADR-013 and the "no hardcoded catalogs in emitted artifacts" concern; makes compile output depend on a non-UMF file | Rejected |
| Redefine `canonical_name` as the glossary key | No new field | `canonical_name` is a seed CSV header, an ingest header matcher, an IR relation name, and a required Excel field; a glossary rule would change physical output | Rejected: new `term` field instead |
| **domain.yaml with exports, suppliers, glossary; FK `references_domain` + `integration`; validate-in-place (selected)** | One name for the unit; published surface is checkable; no routing change; legacy fields keep working | New file shape to learn; nested-domain layouts are not supported | **Selected** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Cross-domain references are validated against a declared surface instead of routed by string prefix. Owners and vocabulary live next to the tables. The guidebook gains a domain map page from the same declarations. Unknown foreign-key keys fail loudly. |
| Negative | Existing multi-directory corpora get no new checks until they add `domain.yaml`; a corpus with nested domain directories must flatten to one level. A spec with an unknown key on a foreign key, previously dropped in silence, now fails to load. |
| Neutral | `PipelineMetadata` and `DependencyResolver` remain as-is (dead but harmless). Domain-scoped `domain_type` registries, the compatibility report filtered to exports, and the line-of-business axis rename are follow-up beads. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| A team writes `references_pipeline` and `references_domain` with different values | L | M | The model validator rejects disagreement with a clear message |
| A domain map page is mistaken for lineage | L | L | Supplier/consumer wording; the page states the direction; ADR-018's upstream/downstream stay on table pages only |
| `extra="forbid"` on `ForeignKey` breaks a spec with a stray key | L | M | The full unit, golden, and conformance suites passed unchanged; the failure is loud and names the key |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| A two-domain corpus with a declared supplier and an exported, keyed table validates clean; removing the export, the supplier, or the primary key each yields exactly one `DOM-*` finding | `tests/unit/test_domain_validator.py` fails |
| `tablespec validate <root>` exits 1 on a `DOM-XREF` error and 0 on a clean corpus | `tests/unit/test_cli_validate_domains.py` fails |
| The guidebook writes `domains.html` and links it from the top index when domains exist, and does not otherwise | `tests/unit/test_guidebook_domain_map.py` fails |
| The checked-in `umf.schema.json` equals `UMF.model_json_schema()` | `tests/unit/test_umf_schema_json_sync.py` fails |

## Supersession

- **Supersedes**: None. ADR-018 decision 2 (group = parent subfolder) is
  retained; this ADR gives that subfolder an owner and a contract when it
  carries a `domain.yaml`.
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden; the
  "no hardcoded catalogs in emitted artifacts" concern is explicitly preserved
  (decision 6).
- **No concern impact**: Governs metadata declaration and validation only.

## References

- FEAT-035 (Domains) — FR-24.1–FR-24.5; US-051
- Solution design: `docs/helix/02-design/domains-solution-design.md` (SD-035)
- ADR-018 (guidebook lineage semantics; group discovery retained)
- ADR-013 (target-agnostic core seam; routing unchanged)
- `src/tablespec/models/domain.py`, `src/tablespec/domains.py`,
  `src/tablespec/domain_validator.py`, `src/tablespec/guidebook/domain_map.py`

## Review Checklist

- [x] Context names a specific problem — three names for one slot, no published surface, no cross-directory validation
- [x] Decision statement is actionable (seven numbered decisions with file and field names)
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete
- [x] ADR consistent with FEAT-035 and PRD FR-24.1–FR-24.5
