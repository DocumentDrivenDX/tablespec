# Nightly clinical pipeline — run tablespec + dbt inside Databricks

A self-contained [Databricks Asset Bundle](https://docs.databricks.com/dev-tools/bundles/)
that runs the whole clinical load **in the workspace** on a schedule, then lets
you explore the result with **Genie**.

This is the workspace-native counterpart to the local `db_*.py` scripts. The
difference that matters: nothing here needs Databricks Connect, a PAT, or a
minted OAuth token — the notebook uses its own Spark session and the dbt task
authenticates as the job's run-as identity.

## Architecture

```
        UC Volume (nightly CSVs)
                 │
   ┌─────────────▼──────────────┐   Databricks Job: nightly_clinical
   │ Task 1  load_and_validate  │   (serverless notebook)
   │  CSV → raw_<t> → ingested  │   tablespec: transform + GX validation
   │  fails the task on errors  │
   └─────────────┬──────────────┘
                 │ depends_on
   ┌─────────────▼──────────────┐   (dbt task, SQL warehouse)
   │ Task 2  dbt_build          │   raw_<t> → dev.dbt_demo.<t>
   │  contract-enforced model   │   runs as the job identity — no token
   └─────────────┬──────────────┘
                 │
          ┌──────▼───────┐
          │    Genie     │   NL → SQL over the results + governance tables
          └──────────────┘
```

Genie does **not** run the pipeline — it can't execute dbt or Python. It sits on
top for the Q&A half of the demo (see below).

## Layout

```
examples/nightly_clinical/
├── databricks.yml                    # the bundle: job, schedule, 2 tasks
├── notebooks/01_load_and_validate.py # Task 1 — tablespec load (native Spark)
├── dbt/                              # Task 2 — the dbt project
│   ├── dbt_project.yml
│   ├── profiles.yml                  # LOCAL runs only (see note)
│   └── models/{encounter.sql, sources.yml, schema.yml}
└── sql/encounter.ingest.sql          # the tablespec-generated transform the notebook runs
```

## One-time setup

1. **Land the nightly CSVs in a Volume** — the notebook reads from
   `landing_dir`. The remote compute cannot see your laptop, so upload once
   (or have an upstream process drop them):

   ```bash
   databricks fs cp encounter_20260618.csv \
     dbfs:/Volumes/dev/test_main_profiler/ab_runs/nightly/encounter.csv -p gfischer
   ```

2. **The scratch target schema** `dev.dbt_demo` must exist (the demo already
   created it): `CREATE SCHEMA IF NOT EXISTS dev.dbt_demo;`

## Deploy and run

```bash
cd examples/nightly_clinical
databricks bundle validate -p gfischer
databricks bundle deploy   -p gfischer         # creates the job (PAUSED schedule)
databricks bundle run nightly_clinical -p gfischer
```

`bundle deploy` uploads the notebook + dbt project to the workspace and creates
the Job. `bundle run` triggers it once; the schedule stays paused until you flip
`pause_status: UNPAUSED` in `databricks.yml`.

## The dbt task authenticates itself

This is the payoff of running in-workspace. The `dbt_task` sets only
`warehouse_id`, `catalog`, and `schema`; Databricks generates the connection
profile and runs dbt as the job's identity. The committed `dbt/profiles.yml`
(with its `example.databricks.net` / `compile-only` env defaults) is used **only
for local `dbt` runs** — the job ignores it. No PAT, no token minting.

## Explore the result with Genie

Once the job has run, point a Genie space at `dev.dbt_demo` and
`dev.test_main_profiler`, and ask in natural language:

- "How many rows are in dbt_demo.encounter?"
- "Show average paid_amount by encounter_type in dbt_demo.encounter."
- "From load_runs, how many rows were promoted in the latest run and were there
  any validation errors?"
- "Which tables had schema drift in the most recent load?"

The last two query the governance tables the pipeline writes, so Genie becomes a
natural-language front end over your load results. The data-profiling app's
**Ask Genie** tab points at the same space, alongside its **Load Results** and
**Guidebook** tabs.

## Scope / notes

- The demo wires up **`encounter`** only. To add tables: land their CSVs, commit
  each `sql/<table>.ingest.sql`, add the model under `dbt/models/`, and add a
  notebook parameter or a task per table (or loop inside the notebook).
- The dbt model is a **blind-append incremental** (the UMF has no primary key),
  so the task runs `dbt run --full-refresh` to stay idempotent. Give the UMF a
  primary key to switch to a real upsert.
- Task 1 **fails on hard validation errors**, so the dbt task never builds from
  data that failed its Great Expectations checks.
