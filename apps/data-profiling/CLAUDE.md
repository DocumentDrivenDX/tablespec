# Synaptiq Data Quality Platform

A Databricks App for ongoing data quality monitoring of Unity Catalog tables.
Profiles individual tables, compares any two versions side-by-side (A/B),
detects statistical drift, and persists quality snapshots to a Delta governance
repository so quality trends are queryable over time. Outputs include per-side
HTML profiles, a comparison HTML, an Excel summary, drift metrics (PSI, KS,
Chi-square, JS divergence), a UML-inspired DQ Metamodel as machine-readable
JSON, and three Mermaid schema/drift diagrams per run.

This file is the project context for any AI coding assistant (Claude Code
in particular) and any new human contributor. Read it before doing anything
non-trivial in the repo.

---

## Quick context

- **Purpose:** Monitor, profile, and compare Unity Catalog tables across any
  catalogs or environments (TEST vs PROD, v1 vs v2, blue vs green). Each run
  produces a quality snapshot persisted to a Delta governance repo, making
  quality trends queryable over time. A/B comparison surfaces schema and
  statistical drift for data engineers shipping table changes between
  environments.
- **Frontend:** Streamlit, deployed as a Databricks App.
- **Profiling engine:** pandas-derived statistics rendered directly to HTML.
  ydata-profiling was evaluated and dropped -- too slow for interactive web
  app use (see `requirements.txt`).
- **Comparison engine:** custom PSI / KS / Chi-square / JS divergence with
  schema-diff (`profiler/drift.py`, `profiler/compare.py`).
- **Guidebook:** renders tablespec's static UMF guidebook in-app, from a UC
  Volume of UMFs or by reflecting a catalog through the SQL warehouse.
- **Outputs (per run):** per-side HTML profile, comparison HTML, Excel
  summary workbook, `metamodel.json`, schema file, 3 Mermaid diagrams,
  rows appended to Delta governance tables. All in a UC Volume.

---

## Environment topology

- **Cloud:** Azure Databricks.
- **Workspaces:** single workspace; one Unity Catalog metastore.
- **Environments:** a **single `dev` catalog**; environments are distinguished by
  a schema-name prefix (`test_main_*`, `prod_main_*`), e.g.
  `dev.test_main_clinical` and `dev.prod_main_clinical`. **No Delta Sharing
  required** for current scope. See the header comment in `connections.yaml`;
  when this moves to a multi-catalog workspace, split that file into one native
  connection per catalog and drop the prefix convention.
- **Profiler Host:** the app's service principal writes outputs to
  `dev.test_main_profiler.ab_runs` (a UC Volume), and the Delta governance
  tables live in `dev.test_main_profiler`. Intentional — keeps tooling
  artifacts out of PROD.
- **Connections** are declared in `connections.yaml`, currently one `type: native`
  entry. If a future env lives in a separate workspace, add a `type: delta_share`
  entry — code supports it without changes (README §4 has the D2D Sharing
  runbook).

---

## Repo layout

```
.
├── CLAUDE.md                     <- this file
├── README.md                     <- human-facing setup + deploy docs
├── app.yaml                      <- Databricks Apps manifest (standalone deploys)
├── streamlit_app.py              <- UI: 5 tabs (see below)
├── connections.yaml              <- connection registry
├── requirements.txt              <- runtime deps
├── requirements-dev.txt          <- dev deps (pytest, coverage)
├── profiler/
│   ├── __init__.py
│   ├── catalog.py                <- UC lookups (mock + databricks backends)
│   ├── storage.py                <- run folder + volume I/O
│   ├── manifest.py               <- per-run manifest (inputs/timings)
│   ├── metamodel.py              <- DQ metamodel (Pydantic v2) — single source of truth
│   ├── profile.py                <- single-table profiling + HTML report
│   ├── compare.py                <- schema diff + aggregate stat diff
│   ├── row_diff.py               <- row-level diff via row keys
│   ├── drift.py                  <- PSI / KS / Chi-square / JS divergence
│   ├── excel.py                  <- Excel summary workbook writer
│   ├── mermaid.py                <- 3 Mermaid diagrams per run
│   ├── delta_repo.py             <- Delta governance tables (DDL + ingest)
│   └── genie_chat.py             <- Genie space conversational backend
└── tests/                        <- 8 files, 258 tests; run by the parent repo's CI
```

UI tabs in `streamlit_app.py`: Compare two tables, Profile table(s), Ask Genie,
Load Results, Guidebook.

---

## Current status

The original milestone plan is complete, except where noted. No module is a
stub; `profiler/` has no `NotImplementedError`.

Shipped:

- Skeleton: UI, input validation, run folder, per-run manifest.
- Single-table profiling with an HTML report (`profiler/profile.py`).
- Schema diff + aggregate stat diff, exported to an Excel workbook
  (`profiler/compare.py`, `profiler/excel.py`).
- Row-level diff via row keys (`profiler/row_diff.py`).
- Drift metrics: PSI, KS, Chi-square, JS divergence (`profiler/drift.py`).
- DQ metamodel (Pydantic v2) + JSON + JSON Schema export
  (`profiler/metamodel.py`).
- Mermaid renderer, 3 diagrams per run (`profiler/mermaid.py`).
- Delta governance repo: 5 tables, idempotent DDL + ingest
  (`profiler/delta_repo.py`).
- Runs-history sidebar.
- Sampling controls (`sampling_mode`: full / sample_n / stratified).
- Ask Genie tab (`profiler/genie_chat.py`).
- Load Results tab: nightly load row counts, schema drift, Great Expectations
  findings, and MERGE promotion metrics, read from the Delta governance schema.
- Guidebook tab: renders tablespec's UMF guidebook from a UC Volume or by
  reflecting a catalog through the SQL warehouse.

Superseded, deliberately not built:

- **ydata-profiling** (originally milestones 2 and 5, for per-side and
  side-by-side HTML). Dropped -- too slow for interactive web app use. HTML
  reports are generated directly from pandas statistics instead. Do not
  reintroduce it without revisiting that decision.

Known gaps:

- **No all-string-table guard.** The hardening milestone called for detecting
  all-string tables and auto-disabling correlations/interactions. Nothing
  implements this today; a wide all-string table will still be profiled naively.
- **`ruff check` is not clean here**, and the app is outside the parent repo's
  `make lint` and pyright scopes.
- **Tests now run on Python 3.12 only.** This app's old CI matrixed 3.10/3.11 to
  match the Databricks Apps runtime; the parent repo requires 3.12+, so that
  version coverage was lost when the suites merged.

---

## Key design decisions (locked in)

These should be respected unless explicitly revisited with the user.

### UML metamodel approach
- `profiler/metamodel.py` is the **single source of truth**. Every other
  output format (Mermaid diagrams, JSON files, Delta tables, future XMI)
  serializes from the same Pydantic object graph.
- **PlantUML and XMI export are deferred** until a concrete external
  consumer (UML tool, governance catalog) appears.
- **Stereotypes are JSON-tag strings** like `["MeasuredAttribute","Drifted"]`,
  not formal UML Profile machinery. The string literal type is in
  `metamodel.Stereotype`.

### Schema versioning
- `METAMODEL_VERSION = "1.0"` constant in `profiler/metamodel.py`.
- Emit `dq-metamodel-v<MAJOR>.schema.json` per major version into the run
  folder (`schema_for_current_version()` returns the schema dict).
- All models use `extra="ignore"` — old code reads new (minor-version)
  payloads without crashing. Major-version bumps are explicit breaks;
  minor versions add fields.

### Run identity
- `run_id` is **UUIDv7** (RFC 9562) — sortable by creation time, globally
  unique, retry-idempotent. Implemented inline in `metamodel.py` to avoid
  the `uuid-utils` dependency.
- Folder names embed the timestamp for humans; the UUID is the primary key
  for Delta MERGEs.

### Histogram storage
- Parallel arrays: `histogram_edges: list[float]`,
  `histogram_counts: list[int]` where `len(edges) == len(counts) + 1`.
- Capped at 50 bins (`HISTOGRAM_MAX_BINS`).
- For tables with >500 columns, histograms may eventually move to a
  separate `column_histograms` Delta table partitioned by run_id.

### Delta governance repo (milestone 4.5.2)
- Five tables: `profiler_runs`, `dataset_profiles`, `column_profiles`,
  `column_alerts`, `column_comparisons`.
- Partition by `created_date`.
- Liquid clustering on `(catalog, schema, table, column_name)`.
- **Direct Delta write from the app**, not Auto Loader — producer/consumer
  are co-located. JSON file is the canonical artifact; Delta tables are
  rebuildable from JSON.
- Retention: 1 year, daily `OPTIMIZE`, weekly `VACUUM`.

### Streamlit Mermaid rendering (milestone 4.5.2)
- Use `st.components.v1.html` with Mermaid.js CDN inline.
- **Do not** depend on `streamlit-mermaid` or `st-mermaid` packages —
  maintenance is uncertain.
- Three diagrams per run, not one:
  1. Side-A schema with per-column alerts and stats
  2. Side-B schema (same shape)
  3. **Drift-only** diagram showing just the columns that moved, with
     cross-side associations stereotyped `<<Drifted>>` and tagged with
     PSI/verdict. This is the most-used view.
- For wide tables (>30 columns), add a "summary mode" that only shows
  columns with alerts or significant drift.

### Verdict semantics
- PSI thresholds (credit-risk convention):
  - `< 0.1` → stable
  - `0.1 ≤ PSI < 0.2` → moderate
  - `≥ 0.2` → significant
- Use `verdict_from_psi(psi, schema_change)` helper — don't hard-code
  thresholds at call sites. A validator enforces consistency between
  stored `verdict` and `psi`.

---

## Runtime modes

The `PROFILER_RUNTIME` environment variable controls behavior:

- **`databricks`** (production): UC lookups via `system.information_schema`
  through `databricks-sql-connector` against a SQL warehouse. Real Volume
  writes.
- **`mock`** (local dev): Returns hard-coded fake catalogs/schemas/tables/
  volumes from `profiler/catalog.py` (`_MOCK_NATIVE`, `_MOCK_SHARED`).
  Volume writes redirect to `./_mock_runs/`. Lets the Streamlit UI run
  locally without a Databricks connection.
- Set in `app.yaml` for production; in PowerShell for local dev:
  `$env:PROFILER_RUNTIME = "mock"`.

The `_MOCK_NATIVE` / `_MOCK_SHARED` split exists to mirror real behavior —
a native auto-discover should not return shared catalogs.

---

## Workflow & conventions

- **Branching:** trunk-based. Feature branches → PR → `main`. No `develop`.
- **Branch names:** `feature/<slug>`.
- **Commits:** imperative mood ("Add Mermaid renderer").
- **CI:** this app's tests **run in the parent repo's CI** and in `make test`.
  They are wired in via `[tool.pytest.ini_options]` in the root `pyproject.toml`
  (`testpaths` includes `apps/data-profiling/tests`, and `pythonpath` includes
  `apps/data-profiling` so `profiler` imports). `pandas` and `scipy` are in the
  root `dev` dependency group for the same reason.
  Two constraints to respect:
    - `tests/` here is **not a package** (no `__init__.py`). Adding one would
      create a second top-level `tests` package that shadows the parent repo's.
    - Tests run on Python 3.12 (the library's floor), not the 3.10/3.11 matrix
      this app used to run standalone.
- **Formatting:** `ruff format` covers this tree, like the rest of the parent
  repository. `ruff check` is not yet clean here.
- **Tests:** add unit tests under `tests/` for every new module. Goal: ≥80%
  coverage on the metamodel and drift modules. Test files import directly
  from the `profiler` package — see `tests/test_metamodel.py` for the
  pattern (builders for synthetic data, then class-grouped tests).
- **Run tests locally:** `pytest tests/ -v` (or
  `pytest tests/ -v --cov=profiler --cov-report=term-missing` for coverage).

---

## Local dev setup

This app lives at `apps/data-profiling/` inside the tablespec repository. Run
everything from this directory -- `connections.yaml` and `assets/` are resolved
relative to the working directory.

```powershell
cd apps\data-profiling
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# The Guidebook tab imports tablespec; install the library from the repo root.
python -m pip install ..\..

# UI in mock mode
$env:PROFILER_RUNTIME = "mock"
streamlit run streamlit_app.py

# Tests
pytest tests/ -v
```

---

## Databricks deployment

See `README.md` §6 for full steps. Summary:

- Output volume: `dev.test_main_profiler.ab_runs` (must exist; create with the
  SQL in `README.md` §2).
- SQL warehouse: any serverless warehouse the app SP can use.
- Both wired in `app.yaml` → `resources.output-volume` and
  `resources.sql-warehouse`. Adjust catalog/warehouse-id per workspace.
- App SP needs: `USE CATALOG` + `USE SCHEMA` + `SELECT` on every catalog
  the app can read; `WRITE VOLUME` on the output volume; `CAN USE` on the
  warehouse; `SELECT` on `system.information_schema`.

**Deploying with the Guidebook tab.** That tab does `import tablespec`, and
Databricks Apps installs the `requirements.txt` at the app's *source root*. So
deploy from the **repository root** using the root `app.yaml`, which installs the
library (`pip install .`) and then chdir's into this directory. The `app.yaml` in
this directory remains valid only for standalone deploys without tablespec, where
the Guidebook tab will show an import error. See
`docs/guide/data-profiling-app.md` in the repository root.

---

## Things to do a certain way

- **Code comments explain *why*, not what.** The code shows the what.
- **Pydantic v2 patterns:** `field_validator`, `model_validator(mode="after")`,
  `ConfigDict`, `model_dump_json(exclude_none=True, by_alias=True)`.
- **Type hints** on all public functions and dataclass-style models.
- Use `from __future__ import annotations` at the top of new modules.
- Prefer explicit imports over wildcards.
- **No emojis** in code, commits, or PR titles.
- **No stubs remain.** `profile.py`/`compare.py`/`drift.py`/`excel.py` are all
  implemented; don't reintroduce `NotImplementedError` placeholders.

---

## Known gotchas

- **All-string tables are not guarded.** Correlations and interactions are still
  attempted on tables with no numeric columns. Detecting that case and flagging
  it in the manifest is unimplemented; see "Known gaps" above.
- **OneDrive caching** can conflict with `.git/index.lock`. Repo lives at
  `C:\Users\garyf\synaptiqrepos\` (outside OneDrive) deliberately.
- **`schema` is a reserved-ish name.** `DatasetProfile` uses `schema_`
  internally with `Field(alias="schema")` so the wire format stays clean.
  Always serialize with `by_alias=True`.
- **Stale `.git/index.lock`** can be left behind when a git operation is
  killed. Safe to delete *only* after closing every git client (VS Code,
  PowerShell, etc.):
  `Remove-Item .git/index.lock -Force`
- **Profile HTML can be large** (several MB for wide tables). Don't load it
  into memory; let Streamlit iframe it directly from the Volume.
- **The guidebook is a multi-page site.** Its pages link to each other, and
  `st.components.v1.html` renders a `srcdoc` iframe where those relative links
  cannot resolve. The Guidebook tab uses a page selector instead; don't "fix"
  the links.

---

## Out of scope (do not add unless explicitly asked)

- PlantUML and XMI export
- Auto Loader / streaming ingestion for the Delta repo
- Cross-workspace deployments via Delta Sharing (the path is documented
  in `README.md` §4 for future use, but not active)
- Lakehouse Federation
- A separate web frontend beyond Streamlit
- A REST API
- Multi-tenant or org-level features

---

## What to pick up next

The milestone plan is finished. The open work, roughly in order of value:

1. **Make `ruff check` clean here**, then widen the parent repo's
   `TRACKED_LINT_FILES` so `make lint` covers this directory. Pyright too.
2. **All-string-table guard** (see "Known gaps"): detect tables with no numeric
   columns, skip correlations/interactions, and record the decision in the
   manifest.
3. **Restore Databricks-runtime Python coverage** if it matters: the suite now
   runs on 3.12 only. A separate CI job could exercise `apps/data-profiling` on
   the Apps runtime's Python version.
4. **Unify the profile models.** `profiler/metamodel.py` describes *observed*
   data; tablespec's `profiling/` describes the *specification*. Feeding observed
   profiles into the guidebook renderer would put spec and reality on one page.

See `tests/test_metamodel.py` for the test pattern. `make test` and CI run this
suite, but running `pytest tests/` here before pushing is faster.
