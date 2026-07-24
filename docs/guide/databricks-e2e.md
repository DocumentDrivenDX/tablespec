# Databricks serverless e2e (opt-in)

Vision KPI: multi-engine parity including Databricks serverless.

Default CI and local `make test` **never** require a workspace. The real
serverless lane is an **opt-in** marker:

```bash
# Without credentials: tests marked databricks_e2e SKIP with a precise reason
uv run pytest -m databricks_e2e -q

# With a configured workspace (export secrets first):
export DATABRICKS_HOST=https://<workspace>
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<id>
export DATABRICKS_TOKEN=<pat>
# plus dbt-databricks + databricks-sdk + databricks-sql-connector installed
uv run pytest -m databricks_e2e -q
```

## Gate

`tablespec.e2e.gating.databricks_e2e_availability()` returns:

- a **skip reason string** when the tier must not run, or
- `None` when credentials + adapters look complete

Required env (all three):

| Variable | Role |
|----------|------|
| `DATABRICKS_HOST` | Opt-in switch |
| `DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `DATABRICKS_TOKEN` | PAT / token |

Unit gate (no workspace):

```bash
uv run pytest tests/unit/test_databricks_e2e_gate.py -q
```

## What the tier proves

When green against a real workspace: dbt/LDP deploy+run and read-back rows
match the Spark-oracle corpus through the shared canonicalizer
(`docs/helix/03-test/conformance-acceptance.md` §2.3).

When skipped: **not a silent pass** — the skip reason names the missing piece.
