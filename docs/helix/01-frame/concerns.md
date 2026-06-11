---
ddx:
  id: concerns
---

# Project Concerns

Project Concerns declare active cross-cutting context for downstream work. They
are not principles, requirements, ADRs, test plans, or implementation tasks.

Selection recorded 2026-06-10 during a spec-compliance pass. No
`concerns.local.yml` operator override exists; slot fillers below are recorded
assumptions inferred from the product's nature (a pure-Python schema-compilation
library), reviewable by the operator.

## Active Concerns

| Concern | Source | Areas | Why Active | Key Practices |
|---------|--------|-------|------------|---------------|
| python-uv | library | `area:*` | The whole product is a Python 3.12+ library managed with uv (`pyproject.toml`, `uv.lock`); every change builds and tests through it | uv-managed env (`make install-dev`), ruff format/lint, pyright on `src/`, pytest via `uv run` |
| testing | library | `area:*` | Determinism and multi-engine parity are P0 product claims (PRD Success Criteria); the test pyramid (unit → conformance matrix → e2e bootstrap paths) is what proves them | Test plan TP-001 governs; golden/byte-for-byte artifact assertions; markers `no_spark`/`spark_only`/`databricks_e2e` |
| verification | library | `area:*` | "Implemented" status claims across FEATs/USs must trace to observed evidence, not assertions; conformance harness + `examples/demo.py` are the whole-stack exercise for a non-UI library | Record command + exit status for acceptance claims; spec-traceability tests in `tests/docs/` gate governing-doc drift |
| sample-data | library | `area:data` | Sample data is both a product feature (FEAT-011, `sample_data/`) and the seed mechanism for the dbt-seeds path and parity harnesses; generated data must be varied, deterministic, and clearly synthetic | Deterministic generation config; healthcare-domain generators; FK-graph-aware pools; never mixed with production data |
| unity-catalog | library | `area:data`, `area:infra` | Compiled artifacts target Databricks Unity Catalog tables at runtime; UC naming/qualification affects SQL plan, dbt, and LDP emission | Three-part naming via the relation seam (`core/relations.py`); no hardcoded catalogs in emitted artifacts |
| databricks-declarative-pipelines | library | `area:data` | The LDP sibling emitter (FEAT-028, ADR-013) emits Lakeflow Declarative Pipelines projects; LDP semantics (APPLY CHANGES, EXPECTATIONS) constrain the shared core seam | LDP generated from the core seam only; no Databricks runtime imports at generation time (`tests/test_core_encapsulation.py`) |
| hugo-hextra | library | `area:docs`, `area:infra` | FEAT-030 introduces a Hugo/Hextra product microsite under `website/` and ADR-014 requires it to coexist with the Pages package index | Hugo extended pinned in CI; Hextra as Hugo Module; content under `website/`; Playwright screenshots; combined Pages artifact preserves `/simple/` |
| product-microsite-ia | library | `area:docs` | The microsite must serve evaluators, first-time users, active users, and operators instead of exposing repository internals as a flat document tree | Separate Evaluate/Start/Decide/Operate paths; homepage answers product/category/value/action; top-level sections distinguish Why, Use, Concepts, Reference, and Demos |

## Slot Resolution

Exclusive slots per `workflows/concerns/slots.yml`, resolved operator-override →
shipped-default → recorded-assumption:

| Slot | Filler | Source | Rationale |
|------|--------|--------|-----------|
| language-runtime | python-uv | assumption | Shipped default (`typescript-bun`) contradicts the product: tablespec is a Python 3.12+ library (`pyproject.toml`). Recorded as assumption per resolution order. |
| frontend-framework | Hugo + Hextra for documentation | assumption | The product remains a non-UI library, but FEAT-030 adds a public documentation microsite. Hextra is the framework for that site only; it is not an operational app UI. |
| e2e-framework | Playwright for microsite; conformance harness for library runtime | assumption | Browser e2e applies to FEAT-030 navigation and rendering. The product runtime remains covered by compile/backbone/conformance tests rather than browser flows. |
| auth-provider | — (not applicable) | assumption | No accounts, tenants, or sign-in surface. |
| datastore | — (not applicable) | assumption | The library holds no state of its own; compiled artifacts target the consumer's platform (Databricks/UC, DuckDB in tests). |
| deploy-target | Python package plus GitHub Pages docs/package index | assumption | Releases publish wheel/sdist and the Pages package index; FEAT-030 adds a Hugo microsite to the same Pages artifact while preserving `/simple/`. |
| architecture-style | target-agnostic core seam (project-local) | assumption | Governed by ADR-013: framework-agnostic `core/` IR with sibling emitters (`dbt/`, `ldp/`, SQL) and enforced import encapsulation. |

## Project Overrides

| Concern | Practice | Override | Authority |
|---------|----------|----------|-----------|
| sample-data | Seed via the stack's semantic faker library | tablespec's own `sample_data/` engine (FEAT-011) is the generator — it is domain-aware (healthcare LOBs, FK graphs) and itself under test | FEAT-011, ADR-008 (seeds path) |
| testing | e2e = browser/HTTP flow against a running app | e2e = compile → committed artifacts → backbone execution on real engines (Spark, DuckDB, Sail; opt-in Databricks serverless) | TP-001, ADR-012 |
| testing | e2e = browser/HTTP flow against a running app | For FEAT-030 only, browser e2e is applicable: Playwright verifies microsite navigation, responsive rendering, and screenshots. This does not replace the library/runtime conformance definition above. | FEAT-030, ADR-014 |

## Area Labels

This project uses the following area labels for concern scoping:

- `area:api` — the public Python API surface (`src/tablespec/__init__.py`)
- `area:cli` — the Typer CLI (`tablespec` entry point) and TUI
- `area:data` — UMF models, emitters, profiling, validation, sample data
- `area:docs` — source docs, API reference, Hugo microsite, and documentation IA
- `area:infra` — CI, packaging, Spark/Databricks test environments

## Concern Conflicts

| Conflict | Resolution |
|----------|------------|
| unity-catalog (three-part runtime naming) vs. testing (local engines without catalogs) | The relation seam (`core/relations.py`) renders engine-appropriate references; conformance fixtures pin the per-engine expected form — never hardcode either shape in emitters |
| sample-data (varied, generated data) vs. testing (byte-for-byte golden assertions) | Golden/parity tests use pinned deterministic generation configs; variability is exercised in generator unit tests, not in cross-engine golden comparisons |
