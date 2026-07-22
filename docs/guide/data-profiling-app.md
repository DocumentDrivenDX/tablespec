# Data Profiling App

A Streamlit **Databricks App** that profiles Unity Catalog tables, compares any
two of them, tracks statistical drift, surfaces nightly load results, and renders
the tablespec [guidebook](guidebook.md) — all over the same UMF metadata.

It lives at `apps/data-profiling/` as first-party code under the repository's
Apache-2.0 license. It was first developed in a separate repository
([FocusedDiversity/data-profiling-dbx-app](https://github.com/FocusedDiversity/data-profiling-dbx-app));
the root `NOTICE` records that history.

## Where it fits

tablespec turns catalog tables into a **specification** — UMF, and from it DDL,
PySpark/JSON schemas, dbt models, ingestion SQL, and Great Expectations suites.
The app supplies the other half: **observation** — what the data actually looks
like, how it drifted, whether last night's load was clean.

```
            ┌──────────────── UMF: the contract ────────────────┐
 catalog ─▶ reflect ─▶ UMF ─▶ DDL / schemas / dbt / ingest / GX suites
                        │
                        ▼
     ┌──── guidebook (static) ────┐   ┌──── app (interactive) ────┐
     │ per-table pages, lineage,  │◀──┤ Guidebook · Compare       │
     │ columns, validation rules  │   │ Profile · Load · Genie    │
     └────────────────────────────┘   └─────────────┬─────────────┘
                                                    │
              <metadata home>.{profiler_runs, column_profiles,
                 column_alerts, column_comparisons, load_*}  ← Delta
```

The **metadata home** is a `(catalog, schema, volume)` address declared per
deployment rather than compiled into the app — see
[Deploy and configure](#deploy-and-configure).

## Tabs

In display order:

| Tab | What it does |
|-----|--------------|
| **Guidebook** | Renders the tablespec guidebook from UMFs — either read from a UC Volume or reflected live from a catalog. |
| **Compare two tables** | Side-by-side profile of two tables; schema diff plus drift metrics (PSI, KS, Chi-square, JS divergence). |
| **Profile table(s)** | Single-table profiling; writes an HTML profile, Excel workbook, and a DQ metamodel JSON to a UC Volume. |
| **Load Results** | Per-run results of the nightly incremental load: row counts, schema drift, Great Expectations findings, and MERGE promotion metrics. |
| **Ask Genie** | Conversational querying via a Databricks Genie space. Hidden when no Genie space is configured. |

## The Guidebook tab

Two sources for the UMFs it renders:

**Reflect from catalog.** Pick a catalog/schema/tables; the app reads
`INFORMATION_SCHEMA.COLUMNS` through its SQL warehouse and builds a UMF per table.

!!! note "No Spark in a Databricks App"
    Apps run in a container with a SQL warehouse and the workspace SDK, but **no
    `SparkSession`**. `SparkToUmfMapper` needs a DataFrame and `JdbcToUmfMapper`
    needs `spark.read.format("jdbc")`, so neither can run there. Reflection uses
    [`umf_from_information_schema`][tablespec.profiling.sql_reflect.umf_from_information_schema],
    which takes rows and opens no connection of its own — consistent with
    tablespec's rule that the caller owns connectivity.

**From UC Volume.** Point at a directory of `*.umf.yaml` / `*.umf.json` written
by the tablespec pipeline; the app downloads them and renders.

!!! warning "Links inside the embedded frame"
    The guidebook is a multi-page static site whose pages link to one another.
    Streamlit embeds HTML in a `srcdoc` iframe, where those relative links cannot
    resolve. A **page selector** replaces cross-page navigation; use
    **Download site (.zip)** to get a copy where the links work normally.

## Reflecting a UMF without Spark

```python
from tablespec.profiling import umf_from_information_schema

rows = warehouse.query(
    "SELECT column_name, data_type, is_nullable, character_maximum_length, "
    "       numeric_precision, numeric_scale, comment, ordinal_position "
    "FROM `dev`.information_schema.columns "
    "WHERE table_schema = 'prod_main_clinical' AND table_name = 'encounter' "
    "ORDER BY ordinal_position"
)

umf = umf_from_information_schema("encounter", rows)
```

Behaviour worth knowing:

- Rows may be raw mappings or `ColumnMeta`; keys match case-insensitively, so
  Databricks (`column_name`) and SQL Server (`COLUMN_NAME`) rows both work.
- `is_nullable` accepts `"YES"`/`"NO"` or a bool, and becomes `nullable.default`.
- `DECIMAL` carries `precision`/`scale`; `VARCHAR`/`CHAR` carry `length`.
- Columns are ordered by `ordinal_position` when every row has one.
- A type with no UMF equivalent (`ARRAY`, `MAP`, `STRUCT`, `VARIANT`) is recorded
  as `VARCHAR` **and logged** — never dropped, since dropping it would
  misrepresent the table's shape.

## Deploy and configure

One source tree serves any workspace. Everything environment-specific is a
declared deployment input; moving to another environment is a manifest change
and a provisioning run, never a source edit.

### 1. Choose the metadata home

Decide the `(catalog, schema, volume)` where this deployment's governance tables
and run artifacts live. The app is *told* this address — it never scans for a
naming convention, so a typo surfaces as an error instead of a silent write into
somebody else's schema. Two deployments may share one metadata home; that is
permitted rather than prevented.

### 2. Provision it — once per environment

```bash
cd apps/data-profiling
export DATABRICKS_CONFIG_PROFILE=<profile>       # or DATABRICKS_HOST/TOKEN

python scripts/provision.py --dry-run \
    --catalog <catalog> --schema <schema> --volume <volume> \
    --warehouse-id <sql-warehouse-id>
```

`--dry-run` prints the resolved target and where each value came from, and
changes nothing. Confirm it points where you expect, then re-run without it.

Provisioning creates the schema, the output volume, and the governance tables,
and reports what it created versus what already existed. It is:

- **idempotent** — a second run against a provisioned environment reports
  `No changes — already provisioned.`
- **additive** — it adds absent tables and columns; a column present but not in
  the current model is *reported*, never dropped, because dropping it destroys
  data provisioning does not own
- **non-escalating** — a failed `GRANT` is a warning carrying the exact
  statement an administrator must run, not a failure and not an attempt to
  acquire the privilege

!!! note "There is no lazy creation"
    The app does not create its own tables on first write. That was deliberate
    ([ADR-019](../helix/02-design/adr/ADR-019-app-configuration-precedence-and-provisioning-authority.md)):
    lazy creation defers discovery of a misconfiguration to a user's first
    click, and happily creates objects at a mistyped address. An unprovisioned
    target instead fails with a message pointing at this step.

### 3. Declare the inputs in `app.yaml`

```yaml
env:
  - name: "PROFILER_METADATA_CATALOG"
    value: "<catalog>"
  - name: "PROFILER_METADATA_SCHEMA"
    value: "<schema>"
  - name: "PROFILER_OUTPUT_VOLUME"
    value: "<volume>"
  - name: "DATABRICKS_WAREHOUSE_ID"
    value: "<sql-warehouse-id>"
  - name: "PROFILER_RUNTIME"
    value: "databricks"            # "mock" for local development
```

Keep the `resources:` block (`output-volume`, `sql-warehouse`) naming the same
location.

Settings resolve through one precedence:

```
deployment environment  >  connections.yaml `metadata:`  >  built-in default
```

Built-in defaults are intentionally generic (`main.tablespec_profiler`). A
default that named a real address would put an environment literal back into
tracked source through the fallback path.

These optional inputs each disable **only** the surface that depends on them:

| Input | Unset behaviour |
|-------|-----------------|
| `GENIE_SPACE_ID` | Ask Genie tab hidden |
| `PROFILER_DASHBOARD_URL` | Sidebar dashboard button hidden |
| `PROFILER_SPEC_VOLUME` | Guidebook falls back to a path under the output volume |

### 4. Grant the app's service principal

Its id is under **Compute → Apps → *app* → Authorization**, and the app displays
the identity it is actually running as in the sidebar.

| Grant | On |
|-------|-----|
| `USE CATALOG` | the metadata catalog |
| `USE SCHEMA` | the metadata schema |
| `SELECT`, `MODIFY` | the governance tables |
| `READ VOLUME`, `WRITE VOLUME` | the output volume |
| `CAN USE` | the SQL warehouse |
| `SELECT` | every catalog the app should profile, and `system.information_schema` |
| `CAN RUN` | the Genie space, if one is configured |

### 5. Deploy

The app imports `tablespec`, and Databricks Apps installs the `requirements.txt`
found at the **source root**. Two arrangements satisfy that:

**From the repository root.** The root `app.yaml` lets `pip install .` build the
library from `pyproject.toml`, then `cd`s into `apps/data-profiling` before
launching Streamlit (the app resolves `connections.yaml` and `assets/` relative
to the working directory).

```bash
databricks sync --profile <profile> . /Workspace/Users/<you>/<repo>
databricks apps deploy <app-name> --profile <profile> \
    --source-code-path /Workspace/Users/<you>/<repo>
```

**From `apps/data-profiling/`.** Its own `requirements.txt` installs the library
from git (`tablespec @ git+…@main`), so the Guidebook tab works without the root
manifest.

```bash
databricks apps deploy <app-name> --profile <profile> \
    --source-code-path /Workspace/Users/<you>/<repo>/apps/data-profiling
```

!!! tip "Which to use"
    Prefer the subfolder when the root deploy is slow or times out — the
    repository is several thousand files and the Apps file listing has to walk
    all of them, whereas the app directory is a few dozen. The trade-off is that
    the subfolder pins the library to a git ref rather than building the working
    tree, so a local library change is not picked up until it is pushed.

    On Git Bash, prefix the command with `MSYS_NO_PATHCONV=1`, or `/Workspace/…`
    is rewritten into a Windows path.

Keep the two manifests' `resources`/`env` blocks in step; whichever one you
deploy from is the one that takes effect.

### 6. Verify after start

The sidebar **Environment** panel lists every setting, its value, and which tier
supplied it. Source `default` next to the catalog or schema means the manifest
input did not take effect and the app fell back to the generic default — which
is exactly what that column exists to make visible.

Configuration faults appear as a banner above the tabs, each naming the setting
at fault and the fix. A stopped warehouse reports as a *deferred* check rather
than blocking startup: start it with **Initialize Compute**, then
**Re-check configuration**.

## Development status

The app is formatted with `ruff format`, and its **318 tests run in `make test`
and CI** alongside the library's. That wiring lives in the root
`pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "apps/data-profiling/tests"]
pythonpath = ["apps/data-profiling"]   # so the tests can import `profiler`
```

Two constraints that are easy to trip over:

- `apps/data-profiling/tests/` is **not a package**. Adding an `__init__.py` would
  create a second top-level `tests` package that shadows the library's, and
  collection fails with `ModuleNotFoundError: No module named 'tests.…'`.
- `pandas` and `scipy` are in the root `dev` dependency group solely so this suite
  can run; `profiler` imports pandas at module import time.

Not yet done:

- **Lint + type-check integration** — `ruff check` *is* clean over `apps/`, and
  the repo-wide ruff excludes cover this tree's Databricks notebooks. What
  remains is scope: `make lint` still runs against `TRACKED_LINT_FILES`
  (`src/` + `scripts/`) and pyright against `src/`, so neither covers `apps/`
  yet. Widening them is open work.
- **Python-version coverage** — the app previously ran its own CI on 3.10/3.11 to
  match the Databricks Apps runtime. The library floor is now 3.11, but CI
  installs 3.12 and the merged suite runs there only, so the Apps runtime
  version is not exercised.
- **Phase 2** — unify the two profile models. `tablespec.profiling` is
  spec-oriented (UMF + GX generation); the app's `profiler/` is
  observation-oriented (`ProfilerRun`, drift, Delta governance). Feeding observed
  profiles into the guidebook renderer would put *spec vs. reality* on one page.
- **Phase 3** — move the app under `src/tablespec/app/`, add a `[app]` extra and
  a `tablespec app` CLI command, and decompose `streamlit_app.py`.
