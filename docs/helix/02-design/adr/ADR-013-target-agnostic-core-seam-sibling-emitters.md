---
ddx:
  id: ADR-013
---

# ADR-013: Target-Agnostic Core Seam with Sibling Emitters
<!-- Filename: ADR-013-target-agnostic-core-seam-sibling-emitters.md — uppercase ADR, zero-padded 3-digit, one decision per file. -->


| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Platform / Compilation | FEAT-028, FEAT-027, ADR-007, ADR-008 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The compiler must emit several structurally different runtime backends (direct SQL, dbt, LDP) from one UMF without re-implementing the cast layer, the dependency IR, or the reference-rewriting per backend, and without the backends taking dependencies on each other. |
| Current State | ADR-007 made raw→ingest a generated SQL artifact; ADR-008 isolated the dbt path behind a framework-agnostic `tablespec.core` (logical-plan IR + `TableRenderer` Protocol) consumed by both the direct and dbt paths, with `tests/test_core_encapsulation.py` forbidding a `core → dbt` import. A second backend (LDP, `tablespec.ldp`) has now shipped against that same seam (`src/tablespec/ldp/project.py:1`), but the seam itself was governed only implicitly inside ADR-008 and a prototype design note. |
| Requirements | FR-19.1 (shared target-agnostic core seam: no emitter imports another, importing core never requires dbt/LDP runtime packages); FR-19.3 (LDP emitted as a committed artifact AND a conformance tier, proving the seam with a second backend). |
| Decision Drivers | One cast truth across backends; provable target-agnosticism (a genuinely different execution model dropping onto the same core); fail-closed reference resolution; dbt/LDP runtimes strictly optional so importing the core stays dependency-light. |

## Decision

We will formalize a **shared target-agnostic CORE seam** under `tablespec.core`
(the logical-plan IR / `NodeRegistry`, the `TableRenderer` Protocol, the
dialect-free schema facts, and `build_ingest_select` / `cast_column_sql`) and
build every runtime backend as an **independent sibling emitter** that consumes
ONLY that seam. The direct-SQL path, the dbt emitter (`tablespec.dbt`), and the
LDP emitter (`tablespec.ldp`) are siblings: each maps the same IR + casts to its
own target text and none imports another. The LDP emitter is the proof obligation
for the seam — a backend whose execution model (declared datasets, platform-owned
DAG, `APPLY CHANGES`, inline `EXPECT`) is fundamentally unlike dbt's ordered run,
yet drops onto the core without forking the cast layer or the ref-rewriting.

**Key Points**: One cast truth (`build_ingest_select` / `cast_column_sql`) shared by every backend, proven by cross-engine duckdb parity (`tests/conformance/test_ldp_tiers.py:97`) | Reference resolution is semantic (name → IR node → target literal) and fails closed on an unknown relation (`src/tablespec/ldp/renderer.py:80`) | Backends are import-isolated: `core` never imports an emitter and emitters never import each other (`tests/test_core_encapsulation.py`); the LDP/dbt runtimes are never imported to *generate*

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Per-backend cast + ref logic (no shared core) | Each backend fully self-contained | Cast logic forked N ways, guaranteed to drift; no proof of target-agnosticism; the "single source of truth" vision breaks at the transform layer | Rejected: re-introduces the per-tool drift the product exists to eliminate |
| dbt-only emitter, defer other targets | Smaller surface | Leaves Databricks/LDP teams hand-authoring streaming/APPLY CHANGES declarations from the same schema; never validates the seam is actually generic (one backend can't prove genericity) | Rejected: FR-19.3 requires LDP, and one backend cannot prove the seam is target-agnostic |
| Shared core with a renderer that string-rewrites SQL refs | Simple to bolt on | Substituting SQL aliases is brittle and can produce phantom refs; cannot fail closed reliably | Rejected: the renderer maps relation *names* to IR nodes, not strings |
| **Shared target-agnostic core seam with sibling emitters (selected)** | One cast truth, provable genericity via a second structurally-different backend, fail-closed semantic refs, runtimes stay optional | A new backend must conform to the seam (the IR + `TableRenderer` Protocol), which constrains how exotic a target's reference model can be; honest gaps (LDP uniqueness/FK) must be surfaced not faked | **Selected: it is the only option that keeps one cast truth across backends AND demonstrably proves the seam is target-agnostic** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | One cast/IR truth feeds direct SQL, dbt, and LDP; adding a backend is a thin emitter over the existing seam; the LDP backend proves genericity (different execution model, same core); references fail closed; dbt/LDP runtimes are never imported to generate, so importing core stays dependency-light. |
| Negative | A target whose reference model cannot be expressed as name→IR-node→literal does not fit the seam without extending it. Rules a target cannot express row-locally (LDP uniqueness / FK) must be surfaced as honest comments, accepting weaker enforcement on that backend. |
| Neutral | LDP runs ONLY on Databricks, so its end-to-end execution is a Databricks-only conformance tier (out of CI); the structure-local and cast-parity tiers run JVM-free locally. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Cast layer silently forks in a new emitter | M | H | Cross-engine duckdb parity asserts the emitter's cast body equals the shared `select_block` (`tests/conformance/test_ldp_tiers.py:85`); encapsulation test forbids re-implementing casts outside core |
| A backend imports a sibling (creating a dependency cycle) | M | M | `tests/test_core_encapsulation.py` asserts no cross-backend and no `core → emitter` import; the LDP renderer takes the registry by a structural Protocol, not a dbt import (`src/tablespec/ldp/renderer.py:44`) |
| A target's honest gap is faked as a constraint | L | M | `derive_comments` emits uniqueness/FK as comments stating where enforcement actually comes from, never as a `CONSTRAINT` (`src/tablespec/ldp/expectations.py:229`) |
| Unknown relation emitted as a phantom dataset | L | H | `LdpRefRenderer.render` raises `UnknownDatasetError` (fail closed) (`src/tablespec/ldp/renderer.py:80`) |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Every backend's cast body equals the shared `build_ingest_select` output on all conformance cases | A conformance parity case fails, or a new emitter duplicates cast logic |
| No `core → emitter` and no cross-backend import (encapsulation suite green) | A new emitter needs a sibling's internals — re-evaluate the seam boundary |
| A second structurally-different backend (LDP) compiles from the same inputs as dbt | A proposed target cannot be expressed via name→IR-node→literal references |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: This ADR governs an internal architecture seam; no
  active-concern relevance.

## References

- PRD Subsystem "Multi-Target Emission" — FR-19.1 (shared target-agnostic core
  seam), FR-19.3 (LDP sibling emitter)
- Product Vision — "Multi-target emission (direct SQL, dbt, LDP) on a shared
  target-agnostic core seam"
- ADR-007 (raw→ingest SQL artifact), ADR-008 (dbt adoption architecture)
- FEAT-028 (LDP sibling emitter), FEAT-027 (dbt emitter)
- Design note: `docs/helix/02-design/ldp-sibling-emitter.md`

## Review Checklist

- [x] Context names a specific problem — multi-backend emission without forking casts/refs
- [x] Decision statement is actionable ("we will formalize a shared seam … sibling emitters")
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-028 and PRD FR-19.1 / FR-19.3
