---
name: tablespec-profiling-app
description: Deploying and operating the data-profiling Databricks App (apps/data-profiling) - provisioning the metadata home, app.yaml configuration, service-principal grants, deploying from repo root or app subfolder, Spark-less UMF reflection via umf_from_information_schema, and local development with the mock runtime. Use when working on the Streamlit profiling/guidebook app or its Unity Catalog deployment.
---

# Tablespec Profiling App

A Streamlit **Databricks App** at `apps/data-profiling/` that profiles Unity
Catalog tables and renders the tablespec guidebook over the same UMF metadata.
Its tabs, in display order: **Guidebook**, **Compare two tables**,
**Profile table(s)**, **Load Results**, and **Ask Genie** (hidden when no Genie
space is configured). Prefer `docs/guide/data-profiling-app.md` as the source of
truth over `apps/data-profiling/README.md`.

## No Spark inside the App container

App containers get a SQL warehouse and the workspace SDK, but **no
`SparkSession`**. Do not use `SparkToUmfMapper` (needs a DataFrame) or
`JdbcToUmfMapper` (needs `spark.read.format("jdbc")`) in app code. Reflect UMFs
from `INFORMATION_SCHEMA` rows instead — the function takes rows and opens no
connection of its own; the caller owns connectivity:

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

Signature: `umf_from_information_schema(table_name, columns, *,
table_type="inferred", description=None) -> UMF`. Behavior worth knowing:

- Rows may be raw mappings or `ColumnMeta`; keys match case-insensitively, so
  Databricks (`column_name`) and SQL Server (`COLUMN_NAME`) rows both work.
- `is_nullable` accepts `"YES"`/`"NO"` or a bool and becomes `nullable.default`.
- `DECIMAL` carries `precision`/`scale`; `VARCHAR`/`CHAR` carry `length`.
- Columns are ordered by `ordinal_position` when every row has one.
- A type with no UMF equivalent (`ARRAY`, `MAP`, `STRUCT`, `VARIANT`) becomes
  `VARCHAR` and is logged — never dropped.

## Metadata home

Each deployment declares a `(catalog, schema, volume)` where its governance
tables and run artifacts live. The app is *told* this address — it never scans
for a naming convention. It writes Delta tables `profiler_runs`,
`dataset_profiles`, `column_profiles`, `column_alerts`, and
`column_comparisons` there, and the Load Results tab reads the nightly-load
tables in the same home. There is **no
lazy creation**: the app does not create its own tables on first write, so an
unprovisioned target fails deliberately with a message pointing at the
provision step, instead of creating objects at a mistyped address.

## Provision — once per environment

```bash
cd apps/data-profiling
export DATABRICKS_CONFIG_PROFILE=<profile>   # or DATABRICKS_HOST/TOKEN

python scripts/provision.py --dry-run \
    --catalog <catalog> --schema <schema> --volume <volume> \
    --warehouse-id <sql-warehouse-id>
```

Run with `--dry-run` first — it prints the resolved target and where each value
came from, changing nothing. Then re-run without it. With no flags it
provisions whatever the resolved config points at, so a shell that already
exports `PROFILER_METADATA_*` needs no arguments. Provisioning is idempotent (a
second run reports no changes) and additive (absent tables and columns are
added; an extra column is reported, never dropped). A failed `GRANT` is a
warning carrying the exact statement an administrator must run, not a failure.

## Configure

Declare the inputs in the `env:` block of `app.yaml`:

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
location. Settings resolve through one precedence: **deployment environment >
`connections.yaml` `metadata:` block > built-in default** — and the built-in
defaults are intentionally generic (`main.tablespec_profiler`), so a manifest
input that didn't take effect shows up as the generic default, not a silent
write elsewhere. `apps/data-profiling/connections.yaml` also declares the
source connections (catalogs) the app can read from and the environment labels
offered in the UI. Optional inputs each disable only their surface:
`GENIE_SPACE_ID` (Ask Genie tab), `PROFILER_DASHBOARD_URL` (sidebar button),
`PROFILER_SPEC_VOLUME` (guidebook falls back to a path under the output
volume).

## Deploy

The Apps **source root must be the repository root**: Databricks Apps installs
the `requirements.txt` found at the source root, and only the root one runs
`pip install .` so the Guidebook tab can `import tablespec`. The root
`app.yaml` command then `cd`s into `apps/data-profiling` before launching
Streamlit, because the app resolves `connections.yaml` and `assets/` relative
to the working directory. Do not deploy `apps/data-profiling/` expecting the
working-tree library — its own `requirements.txt` pins tablespec to a git ref.

```bash
databricks sync --profile <profile> . /Workspace/Users/<you>/<repo>
databricks apps deploy <app-name> --profile <profile> \
    --source-code-path /Workspace/Users/<you>/<repo>
```

A subfolder deploy (`--source-code-path …/<repo>/apps/data-profiling`) is the
faster fallback when the root deploy times out, at the cost of the git-ref pin.
Keep the two manifests' `resources`/`env` blocks in step; whichever you deploy
from takes effect. Grant the app's service principal access to the metadata
home, the warehouse, and every catalog it should profile — the grant table is
in `docs/guide/data-profiling-app.md` ("Grant the app's service principal").

## Verify and local development

After start, the sidebar **Environment** panel lists every setting, its value,
and which tier supplied it — source `default` next to the catalog or schema
means the manifest input did not take effect. Configuration faults appear as a
banner naming the setting and the fix; a stopped warehouse is a deferred check,
not a startup failure.

Locally, `make app-smoke` runs the app's config/provision/diagnostics tests
under `PROFILER_RUNTIME=mock` with no workspace, and `make app-typecheck` runs
the scoped pyright config in `apps/data-profiling/`. Never add an
`__init__.py` to `apps/data-profiling/tests/` — it would create a second
top-level `tests` package that shadows the library's and break collection.

## Related

For generating UMF, validation suites, and pipeline artifacts outside the app,
use the `tablespec-pipeline` skill. Full guide:
`docs/guide/data-profiling-app.md` and
https://documentdrivendx.github.io/tablespec/
