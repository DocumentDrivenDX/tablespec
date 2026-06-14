# Kaggle flat-file onboarding demo notebooks (US-044)

Land a delimited flat-file dataset from a Unity Catalog volume, derive a
validated UMF spec, export a schema workbook, generate compiled artifacts,
and run staged validation — all from shipped tablespec code (FEAT-031,
FEAT-024, FEAT-005, FEAT-021, FEAT-009, FEAT-007/FEAT-017).

Default dataset: the **NYC Airbnb Open Data CSV** (`AB_NYC_2019.csv`).
The notebooks are fully widget-swappable for any similarly-shaped CSV.

## Notebooks

| Notebook | What it does | Owner |
|---|---|---|
| `01-stage-csv-kaggle` | Create UC schema+volume; acquire and stage the CSV via URL or manual upload | Consumer plumbing — the US-044 precondition; tablespec never does this |
| `02-kaggle-tablespec-demo` | The tablespec story: land all-STRING → profile → spec → workbook → artifacts → staged validation → scorecard | tablespec |

## Cluster requirements

- **DBR 13.3 LTS or later** (Python 3.10+; DBR 16.4+ for Spark 4 parity)
- **Single-user access mode** (or shared with Unity Catalog enabled)
- tablespec wheel installed via `wheel_path` widget or pre-installed on the cluster

## Operating it

1. Import this folder into the workspace (Git folder or
   `databricks workspace import-dir`).
2. Build and upload the tablespec wheel:
   ```
   uv build
   databricks workspace import dist/tablespec-*.whl \
     /Workspace/Shared/tablespec-demo/tablespec.whl --overwrite
   ```
3. Run `01-stage-csv-kaggle` with the `csv_url` widget pointing at a public copy
   of `AB_NYC_2019.csv`, or stage the file manually:
   - Download from Kaggle (free account):
     `https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data`
   - Upload via Catalog UI: **Catalog ▸ your catalog ▸ your schema ▸ Volumes
     ▸ your volume ▸ Upload**
4. Run `02-kaggle-tablespec-demo` with the same `output_catalog`,
   `output_schema`, `output_volume`, and `csv_filename` widget values.
   Set `wheel_path` to the workspace import path from step 2.

Artifacts land under the target volume at `tablespec_out/`:
`specs/`, `workbooks/`, `artifacts/`, `reports/`.

## Widget reference

### Notebook 01

| Widget | Default | Notes |
|---|---|---|
| `wheel_path` | *(empty)* | `%pip` glob path; empty = pre-installed |
| `output_catalog` | `main` | Unity Catalog catalog |
| `output_schema` | `kaggle_demo` | UC schema |
| `output_volume` | `raw` | UC volume |
| `csv_url` | *(empty)* | Public download URL; empty = manual staging |
| `csv_filename` | `AB_NYC_2019.csv` | Filename in the volume |

### Notebook 02

| Widget | Default | Notes |
|---|---|---|
| `wheel_path` | *(empty)* | `%pip` glob path; empty = pre-installed |
| `output_catalog` | `main` | Unity Catalog catalog |
| `output_schema` | `kaggle_demo` | UC schema |
| `output_volume` | `raw` | UC volume |
| `csv_filename` | `AB_NYC_2019.csv` | CSV to land and spec |
| `table_name` | `ab_nyc_2019` | UMF table name for the derived spec |

## Swapping datasets (AC4)

Only notebook 01 contains dataset-specific logic (download URL and filename).
Notebook 02 is fully widget-driven and contains **no dataset-specific code**:
point `csv_filename` at any header-bearing, comma-delimited, double-quote CSV
in the volume and `table_name` at the desired UMF table name — the full
tablespec flow (land → profile → spec → workbook → artifacts → validation)
runs unmodified.

## Notes

- The CSV is **never committed** to the repo; notebook 01 acquires it at runtime.
- The raw landing is **all-STRING** (`inferSchema=False`, ADR-007): no type
  inference during landing — the derived UMF is a reviewable VARCHAR spec the
  engineer enriches before compiling production pipelines.
- The `source: {kind: delimited}` declaration drives all reader options
  (`CsvReader` via the ingestion reader seam); notebook 02 contains no
  hardcoded `spark.read.csv()` calls.
- Quoted fields containing the delimiter (e.g. Airbnb listing names with
  commas) are handled by Spark's default `"` quote character; the column
  count check asserts no silent shifting.
- Proven cluster: **DBR 17.3 LTS** (`17.3.x-scala2.13`, Spark 4, Ubuntu 24.04)
  on a single-node DS3_v2 (same pairing as the Northwind demo, job 1016486615934960).
