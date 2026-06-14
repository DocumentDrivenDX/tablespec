# US-044 AC Evidence — tablespec-da6ee32b

## Deliverables committed

| File | Purpose |
|---|---|
| `notebooks/kaggle-demo/01-stage-csv-kaggle.py` | Consumer plumbing: create UC volume, stage CSV |
| `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py` | The tablespec story: land → profile → spec → workbook → artifacts → validation → scorecard |
| `notebooks/kaggle-demo/README.md` | Widget reference, cluster requirements, operating instructions |

## AC evidence (code)

### US-044-AC1 — land + profile + spec

- **File**: `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py` §1–3
- **Evidence**:
  - `DelimitedSource(kind="delimited", delimiter=",", header=True, quote_char='"')` — all reader options come from the declaration; no hardcoded `spark.read.csv(...)` call exists in notebook 02.
  - `get_reader(source).read(source, spark)` — uses the ingestion reader seam (FEAT-031 SRC-01..05).
  - `assert not non_string_cols` — verifies all-STRING raw landing (ADR-007).
  - `NativeSparkProfiler(spark).profile(raw_df)` — profiles the landed DataFrame.
  - `SparkToUmfMapper().map_dataframe_to_umf(raw_df, TABLE_NAME)` — derives UMF from schema.
  - `UMF.model_validate(umf_dict)` + `UMFValidator().validate_data(umf_data)` — spec passes with zero errors, zero manual edits.

### US-044-AC2 — schema workbook

- **File**: `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py` §4
- **Evidence**:
  - `UMFToExcelConverter().convert(umf).save(wb_path)` — produces workbook whose rows match UMF columns/types.
  - `ExcelToUMFConverter().convert(wb_path)` — re-imports the workbook.
  - `assert roundtrip_ok` — verifies table name + column names match without loss (FEAT-009 contract).

### US-044-AC3 — artifacts + staged validation

- **File**: `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py` §5–6
- **Evidence**:
  - `generate_sql_ddl(umf_data)` → raw DDL written to `artifacts/{table}_ddl.sql`.
  - `generate_pyspark_schema(umf_data)` → ingest schema written to `artifacts/{table}_pyspark.txt`.
  - `generate_json_schema(umf_data)` → JSON schema written to `artifacts/{table}_json_schema.json`.
  - `BaselineExpectationGenerator().generate_baseline_expectations(umf_data)` → expectation suites.
  - `GXSuiteExecutor(spark).execute_staged(raw_df, raw_df, expectations)` → staged execution.
  - `assert report.results` + `assert any(r.success is not None for r in report.results)` — verifies real per-expectation results (no silent stubs).

### US-044-AC4 — demo lane + swappability

- **File**: `notebooks/kaggle-demo/02-kaggle-tablespec-demo.py` scorecard
- **Evidence**:
  - Scorecard asserts `not _nb_has_dataset_code` — checks notebook 02 text for forbidden literals (`AB_NYC_2019`, `ab_nyc_2019`, `neighbourhood`, `airbnb`) and asserts none are present. Notebook 02 contains only widget-driven logic; all dataset-specific values live in `csv_filename`/`table_name` widgets and notebook 01.
  - `dbutils.notebook.exit(json.dumps({"status": overall, ...}))` — job exits PASS when all ACs pass; exits FAIL and raises `AssertionError` on the first failing AC.

## Databricks job run status

**Status: PENDING**

The `dbw-dev-eus2` CLI profile shows `NO` (credentials expired as of 2026-06-13).
The notebooks are authored and committed; the job run requires renewed credentials.

**To execute**:
```bash
# Renew credentials
databricks auth login --profile dbw-dev-eus2

# Upload wheel
uv build
databricks workspace import dist/tablespec-*.whl \
  /Workspace/Shared/tablespec-demo/tablespec.whl --overwrite --profile dbw-dev-eus2

# Stage CSV (or set csv_url widget in notebook 01)
# Then run notebook pair as a Databricks job — expected exit: PASS
```

**Expected cluster**: DBR 17.3 LTS + DS3_v2 (proven pairing from Northwind job 1016486615934960).

Record the run ID here when green: `run_id: _____`
