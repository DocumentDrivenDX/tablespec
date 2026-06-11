# Northwind demo notebooks (US-039)

Operate the tablespec multi-source ingestion demo on Databricks: point
tablespec at a SQL Server database and get validated UMF specs, schema
workbooks, FK-aware sample data, and staged validation reports — all
spec-driven (FEAT-031, ADR-015).

## Notebooks

| Notebook | What it does | Owner |
|---|---|---|
| `01-provision-sqlserver-northwind` | Installs SQL Server 2022 on the driver node, configures and starts it, loads `northwind.sql` | Consumer plumbing — the US-039 precondition; tablespec never does this |
| `02-northwind-discovery-demo` | The tablespec story: discover → validate → workbooks → sample data → land typed → validation reports, ending in a scorecard | tablespec |

## Cluster requirements

- **Single node** (driver == executor, so the `localhost` JDBC endpoint works)
- **DBR 16.4 LTS or 17.3 LTS** — notebook 01 detects the host Ubuntu and
  installs the matching SQL Server rev: Ubuntu 22.04 (DBR 15.4/16.4) →
  SQL Server 2022; Ubuntu 24.04 (DBR 17.3, **Spark 4** — engine parity with
  tablespec's local matrix) → SQL Server 2025. The tablespec wheel needs
  Python ≥3.12, so prefer DBR ≥16.4.
- **Single-user access mode** (notebook 01 runs root shell commands)
- Azure DBR images need the LDAP runtime libs (`libldap`/`liblber`) — the
  notebook installs them; AWS images and the apt key trust differ per cloud
  and are likewise handled by the notebook.

## Operating it

1. Import this folder into the workspace (Git folder or
   `databricks workspace import-dir`), keeping `northwind.sql` next to the
   notebooks.
2. Build and upload the wheel:
   `uv build && databricks fs cp dist/tablespec-*.whl dbfs:/FileStore/tablespec-demo/`
3. Run `01-provision-sqlserver-northwind` on the cluster (widgets optional:
   it auto-generates an SA password and finds the fixture next to itself).
4. Run `02-northwind-discovery-demo` on the **same cluster**, setting the
   `wheel_path` widget (e.g. `/dbfs/FileStore/tablespec-demo/tablespec-*.whl`).
   It reads the endpoint handoff from `/local_disk0/northwind_demo/`.

Against an external SQL Server instead, skip notebook 01 and set the
`jdbc_url` / `jdbc_user` / `password_env` widgets (export the password into
the named env var; tablespec only ever sees the reference — per FEAT-031
JDBC-01, a literal credential fails spec validation).

Artifacts land under `/local_disk0/northwind_demo/out/`:
`specs/`, `workbooks/`, `sample_data/`, `reports/`.

## Notes

- The SA password is stored only at `/local_disk0/northwind_demo/sa_password`
  (0600, driver-local, destroyed with the cluster). For anything beyond a
  demo use a Databricks secret scope and pass its name via `password_env`
  conventions instead.
- The same flow runs locally without Databricks:
  `uv run pytest tests/integration/test_northwind_e2e.py` (Docker-gated).
