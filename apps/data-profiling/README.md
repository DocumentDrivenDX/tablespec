# data-profiling (table-ab-profiler)

> **Origin.** This app was first developed in a separate repository
> ([FocusedDiversity/data-profiling-dbx-app](https://github.com/FocusedDiversity/data-profiling-dbx-app))
> and now lives here as first-party code under the repository's Apache-2.0
> `LICENSE` (see also `NOTICE`).
>
> **Source of truth:** `docs/guide/data-profiling-app.md` (architecture,
> configuration, provisioning, deployment) and `CLAUDE.md` in this directory
> (design decisions, status, conventions). This README is the short tour.

A Streamlit **Databricks App** that profiles Unity Catalog tables, compares any
two side-by-side (A/B) with statistical drift metrics (PSI, KS, Chi-square, JS
divergence), surfaces nightly load results, and renders tablespec's UMF
guidebook in-app. Each run persists a quality snapshot to Delta governance
tables so quality trends are queryable over time.

**Status:** feature-complete — no module is a stub. UI tabs: Guidebook,
Compare two tables, Profile table(s), Load Results, Ask Genie (hidden when no
Genie space is configured).

---

## 1. How it's wired

The current deployment is a **single workspace, single `dev` catalog**;
environments are distinguished by schema-name prefix (`test_main_*`,
`prod_main_*`). No Delta Sharing is required for this scope. Env labels in the
UI (DEV/TEST/QA/STAGE/PROD/custom) are metadata; actual routing comes from
`connections.yaml`, which lists each reachable connection (native or
delta_share) and the catalogs it exposes. Section 7 keeps the D2D Delta
Sharing runbook for when a source environment lives in a separate workspace.

The app writes run artifacts to a UC Volume and quality snapshots to Delta
governance tables in a declared metadata home (catalog, schema, volume) — see
`profiler/config.py` for how settings resolve.

---

## 2. Repo layout

```
data-profiling/
├── app.yaml                   Databricks Apps manifest (standalone deploys)
├── requirements.txt           Runtime deps
├── requirements-dev.txt       Dev deps (pytest, coverage)
├── connections.yaml           Connection registry (edit to add new envs)
├── streamlit_app.py           UI (5 tabs)
├── scripts/provision.py       Idempotent metadata-home provisioning
├── profiler/
│   ├── config.py              Resolved settings; the only place a setting is read
│   ├── provision.py           Provisioning implementation
│   ├── diagnostics.py         Startup validation; faults name setting + grant
│   ├── catalog.py             UC lookups (mock + databricks backends)
│   ├── storage.py             Run folder + volume I/O
│   ├── manifest.py            Per-run manifest
│   ├── metamodel.py           DQ metamodel (Pydantic v2) — single source of truth
│   ├── profile.py             Single-table profiling + HTML report
│   ├── compare.py             Schema diff + aggregate stat diff
│   ├── row_diff.py            Row-level diff via row keys
│   ├── drift.py               PSI / KS / Chi-square / JS divergence
│   ├── excel.py               Excel summary workbook writer
│   ├── mermaid.py             3 Mermaid diagrams per run
│   ├── delta_repo.py          Delta governance tables (DDL + ingest)
│   └── genie_chat.py          Genie space conversational backend
└── tests/                     Run by the parent repo's CI (no __init__.py — see CLAUDE.md)
```

---

## 3. One-time setup per environment

1. Set the `PROFILER_METADATA_*` values in `app.yaml` (metadata catalog,
   schema, output volume, warehouse ID).
2. Run `python scripts/provision.py --dry-run` to see the resolved target,
   then re-run without `--dry-run`. It creates the schema, the output volume,
   and the governance tables, and is safe to re-run. There is no lazy creation
   on first write — an unprovisioned target fails with a message pointing
   here.
3. Grant the app's service principal what `app.yaml`'s header comment lists
   (catalog/schema/table reads, governance-table `SELECT`+`MODIFY`, volume
   read/write, warehouse `CAN USE`, Genie `CAN RUN` if set). The app reports a
   missing grant at startup with the exact statement to run; it never acquires
   privileges itself.

---

## 4. Local development (no Databricks)

The app has a mock backend for offline UI iteration:

```bash
pip install -r requirements-dev.txt
pip install ../..            # the Guidebook tab imports tablespec
export PROFILER_RUNTIME=mock
streamlit run streamlit_app.py
```

- Catalog/schema/table/volume dropdowns return a fixed fake dataset.
- Volume writes redirect to `./_mock_runs/`.
- Tests: `pytest tests/ -v` from this directory, or `make app-smoke` /
  `make app-typecheck` from the repo root.

---

## 5. Deploying to Databricks Apps

Deploy from the **repository root** so the Guidebook tab can
`import tablespec` — the root `app.yaml` runs `pip install .` and then chdir's
into this directory:

```bash
databricks sync --profile <p> . /Workspace/Users/<you>/<repo>
databricks apps deploy <app-name> --profile <p> \
    --source-code-path /Workspace/Users/<you>/<repo>
```

Deploying this directory directly (using the `app.yaml` here) remains valid
for standalone deploys without tablespec; the Guidebook tab will show an
import error. Full steps and trade-offs: `docs/guide/data-profiling-app.md`.

---

## 6. What's next

The original milestone plan is complete. Open work (details in `CLAUDE.md`):
widen parent lint/type-check gates to this directory, an all-string-table
guard for profiling, and unifying the observed-profile models with tablespec's
specification models.

---

## 7. Wiring a source environment in another workspace (D2D Delta Sharing — future use)

Not active in the current single-workspace scope, kept as the runbook for when
an environment lives in a separate workspace/metastore.

Run in **the source (e.g. TEST) workspace**:

```sql
-- 1. Register the Profiler Host metastore as a recipient.
CREATE RECIPIENT profiler_host
  USING ID '<profiler-host-metastore-id>';    -- D2D: use the metastore ID, not a token

-- 2. Create a share exposing the catalogs/schemas to profile.
CREATE SHARE test_for_profiler;
ALTER SHARE test_for_profiler
  ADD SCHEMA test_main.sales;                 -- add whatever schemas matter

-- 3. Grant the share to the recipient.
GRANT SELECT ON SHARE test_for_profiler TO RECIPIENT profiler_host;
```

Run in **the Profiler Host workspace**:

```sql
-- 4. Mount the share as a read-only catalog.
CREATE CATALOG test_sh USING SHARE <test_provider>.test_for_profiler;

-- 5. Grant the app SP read access.
GRANT USE CATALOG, USE SCHEMA ON CATALOG test_sh TO `<app-sp>`;
GRANT SELECT ON ALL TABLES IN CATALOG test_sh TO `<app-sp>`;
```

Then add a `type: delta_share` entry to `connections.yaml` and redeploy — no
code change required.

### Azure-specific gotchas

- **Private endpoints / storage firewalls:** D2D Sharing reads the source
  storage account directly from the Profiler Host compute. Networking team
  must allow Profiler Host compute → source storage.
- **Customer-managed keys:** recipient must be able to decrypt shared
  storage; coordinate with whoever owns the CMK.
- **Row-level diff across shared catalogs** is slower than native — push down
  filters (date, partition col) before joining.
