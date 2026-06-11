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

## Slot Resolution

Exclusive slots per `workflows/concerns/slots.yml`, resolved operator-override →
shipped-default → recorded-assumption:

| Slot | Filler | Source | Rationale |
|------|--------|--------|-----------|
| language-runtime | python-uv | assumption | Shipped default (`typescript-bun`) contradicts the product: tablespec is a Python 3.12+ library (`pyproject.toml`). Recorded as assumption per resolution order. |
| frontend-framework | — (not applicable) | assumption | No UI surface; PRD Non-Goals exclude GUI/web interfaces. |
| e2e-framework | — (not applicable as browser e2e) | assumption | Non-UI library: the whole-stack exercise is the cross-engine conformance harness plus `examples/demo.py` (run by `tests/integration/test_demo.py`), substituting for browser e2e per the verification concern's library exception. |
| auth-provider | — (not applicable) | assumption | No accounts, tenants, or sign-in surface. |
| datastore | — (not applicable) | assumption | The library holds no state of its own; compiled artifacts target the consumer's platform (Databricks/UC, DuckDB in tests). |
| deploy-target | Python package (wheel/sdist) | assumption | Distributed as a library package; no service deployment. |
| architecture-style | target-agnostic core seam (project-local) | assumption | Governed by ADR-013: framework-agnostic `core/` IR with sibling emitters (`dbt/`, `ldp/`, SQL) and enforced import encapsulation. |

## Project Overrides

| Concern | Practice | Override | Authority |
|---------|----------|----------|-----------|
| sample-data | Seed via the stack's semantic faker library | tablespec's own `sample_data/` engine (FEAT-011) is the generator — it is domain-aware (healthcare LOBs, FK graphs) and itself under test | FEAT-011, ADR-008 (seeds path) |
| testing | e2e = browser/HTTP flow against a running app | e2e = compile → committed artifacts → backbone execution on real engines (Spark, DuckDB, Sail; opt-in Databricks serverless) | TP-001, ADR-012 |

## Area Labels

This project uses the following area labels for concern scoping:

- `area:api` — the public Python API surface (`src/tablespec/__init__.py`)
- `area:cli` — the Typer CLI (`tablespec` entry point) and TUI
- `area:data` — UMF models, emitters, profiling, validation, sample data
- `area:infra` — CI, packaging, Spark/Databricks test environments

## Concern Conflicts

| Conflict | Resolution |
|----------|------------|
| unity-catalog (three-part runtime naming) vs. testing (local engines without catalogs) | The relation seam (`core/relations.py`) renders engine-appropriate references; conformance fixtures pin the per-engine expected form — never hardcode either shape in emitters |
| sample-data (varied, generated data) vs. testing (byte-for-byte golden assertions) | Golden/parity tests use pinned deterministic generation configs; variability is exercised in generator unit tests, not in cross-engine golden comparisons |
