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
     │ per-table pages, lineage,  │◀──┤ Compare · Profile · Genie │
     │ columns, validation rules  │   │ Load Results · Guidebook  │
     └────────────────────────────┘   └─────────────┬─────────────┘
                                                    │
                     dev.test_main_profiler.{profiler_runs, column_profiles,
                        column_alerts, column_comparisons, load_*}  ← Delta
```

## Tabs

| Tab | What it does |
|-----|--------------|
| **Compare two tables** | Side-by-side profile of two tables; schema diff plus drift metrics (PSI, KS, Chi-square, JS divergence). |
| **Profile table(s)** | Single-table profiling; writes an HTML profile, Excel workbook, and a DQ metamodel JSON to a UC Volume. |
| **Ask Genie** | Conversational querying via a Databricks Genie space. |
| **Load Results** | Per-run results of the nightly incremental load: row counts, schema drift, Great Expectations findings, and MERGE promotion metrics. |
| **Guidebook** | Renders the tablespec guidebook from UMFs — either read from a UC Volume or reflected live from a catalog. |

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

## Deployment

The app imports `tablespec`, and Databricks Apps installs the `requirements.txt`
at the **source root** — so the source root must be the repository root, not
`apps/data-profiling/`.

The root `app.yaml` therefore:

1. lets `pip install .` build and install tablespec from `pyproject.toml`, and
2. `cd`s into `apps/data-profiling` before launching Streamlit, because the app
   resolves `connections.yaml` and `assets/` relative to the working directory.

```bash
databricks sync --profile <profile> . /Workspace/Users/<you>/<repo>
databricks apps deploy <app-name> --profile <profile> \
    --source-code-path /Workspace/Users/<you>/<repo>
```

`apps/data-profiling/app.yaml` is retained for standalone deploys without
tablespec. Keep its `resources`/`env` blocks in sync with the root manifest.

The app's service principal needs `SELECT` on the governance tables it reads and
on `information_schema` for the catalogs it reflects.

## Development status

The app is formatted with `ruff format` like the rest of the repository.

It is **not yet in `make check`**: `make lint` and `make test` scope to `src/`,
`scripts/`, and `tests/`, and pyright scopes to `src/`. Run the app's own suite
from its directory:

```bash
cd apps/data-profiling && pytest tests/
```

Planned, not yet done:

- **Lint + test integration** — clear the outstanding `ruff check` findings under
  `apps/`, then widen `TRACKED_LINT_FILES` and the pytest paths so `make check`
  covers the app.
- **Phase 2** — unify the two profile models. `tablespec.profiling` is
  spec-oriented (UMF + GX generation); the app's `profiler/` is
  observation-oriented (`ProfilerRun`, drift, Delta governance). Feeding observed
  profiles into the guidebook renderer would put *spec vs. reality* on one page.
- **Phase 3** — move the app under `src/tablespec/app/`, add a `[app]` extra and
  a `tablespec app` CLI command, and decompose `streamlit_app.py`.
