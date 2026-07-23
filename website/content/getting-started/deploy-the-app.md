---
title: Deploy the app
weight: 3
---

Deploy the first-party **data-profiling Databricks App** into any workspace by
changing declared inputs only — never by editing tracked application source.

The app is an optional operator companion: guidebook browsing, profiling,
comparison, load results. The library, CLI, and committed artifacts remain the
product core.

## What you need

- A Databricks workspace where you can create Apps and use a SQL warehouse
- Permission to create a catalog schema and volume (or an admin who can)
- A tablespec install path for the app (`pip install .` from the repo root, or
  the git pin in `apps/data-profiling/requirements.txt`)

## 1. Choose the metadata home

Pick a `(catalog, schema, volume)` triple where this deployment's governance
tables and run artifacts will live. The app is told that address; it does not
scan for a naming convention.

Two deployments may share one metadata home when you want that.

## 2. Dry-run provision, then provision

From a machine with Databricks CLI/auth:

```bash
cd apps/data-profiling
export DATABRICKS_CONFIG_PROFILE=<profile>   # or DATABRICKS_HOST + TOKEN

python scripts/provision.py --dry-run \
  --catalog <catalog> \
  --schema <schema> \
  --volume <volume> \
  --warehouse-id <sql-warehouse-id>
```

Confirm the printed target, then re-run without `--dry-run`. Provisioning is
idempotent and additive: a second run is a no-op; it never drops columns.

## 3. Set deployment inputs

In `app.yaml` (or the Apps UI env form), declare at least:

| Variable | Role |
|----------|------|
| `PROFILER_METADATA_CATALOG` | Metadata catalog |
| `PROFILER_METADATA_SCHEMA` | Metadata schema |
| `PROFILER_OUTPUT_VOLUME` | Output volume |
| `DATABRICKS_WAREHOUSE_ID` | SQL warehouse the app identity can use |
| `PROFILER_RUNTIME` | `databricks` in the workspace; `mock` only for local unit smoke |

Optional (absent-tolerant — they hide a surface, they do not crash the app):

| Variable | When unset |
|----------|------------|
| `GENIE_SPACE_ID` | Ask Genie tab hidden |
| `PROFILER_DASHBOARD_URL` | Sidebar dashboard button hidden |
| `PROFILER_SPEC_VOLUME` | Guidebook falls back under the output volume |

Precedence is fixed:

```text
deployment environment  >  connections.yaml metadata:  >  built-in default
```

Built-in defaults are intentionally generic (`main.tablespec_profiler`). Do not
put a real environment address in tracked source.

## 4. Grant the app service principal

Find the identity under **Compute → Apps → *your app* → Authorization** (also
shown in the app sidebar after start).

| Grant | On |
|-------|-----|
| `USE CATALOG` | metadata catalog |
| `USE SCHEMA` | metadata schema |
| `SELECT`, `MODIFY` | governance tables |
| `READ VOLUME`, `WRITE VOLUME` | output volume |
| `CAN USE` | SQL warehouse |
| `SELECT` | catalogs you will profile, and `system.information_schema` |
| `CAN RUN` | Genie space, if configured |

Missing grants should fail at **startup** with a message that names the setting
and the grant — not mid-click on first query.

## 5. Deploy

**From the repository root** (recommended when you want `pip install .` for
tablespec):

```bash
databricks sync --profile <profile> . /Workspace/Users/<you>/tablespec
databricks apps deploy <app-name> --profile <profile> \
  --source-code-path /Workspace/Users/<you>/tablespec
```

The root `app.yaml` installs tablespec from the repo, then chdir's into
`apps/data-profiling` so `connections.yaml` and assets resolve correctly.

**From `apps/data-profiling/` alone** if you prefer the subdirectory
`requirements.txt` git pin for tablespec.

## 6. Confirm in the UI

1. App process starts without a configuration stack trace.
2. Sidebar shows the resolved metadata location (the declared triple).
3. Guidebook tab can reflect a catalog table or load UMF from a volume path.
4. Profile or Compare against a table the app identity can `SELECT`.

If startup fails, fix the named setting/grant and redeploy — do not patch
literals into application code.

## Local smoke (no workspace)

```bash
cd apps/data-profiling
PROFILER_RUNTIME=mock \
  PROFILER_METADATA_CATALOG=main \
  PROFILER_METADATA_SCHEMA=tablespec_profiler \
  uv run pytest tests/test_fr23_stack.py tests/test_config.py \
    tests/test_provision.py tests/test_diagnostics.py -q
```

Or from the repo root: `make app-smoke`.

## Next

{{< cards >}}
  {{< card link="/getting-started/in-a-workspace/" title="In a workspace" subtitle="Notebook demos and opt-in serverless conformance." icon="server" >}}
  {{< card link="/demos/" title="Demos" subtitle="Northwind, Kaggle, Synthea, and the local screencast." icon="play" >}}
{{< /cards >}}
