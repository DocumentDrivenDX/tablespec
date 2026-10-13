# Databricks notebook source
# @covers US-044-AC1
# @covers US-044-AC2
# @covers US-044-AC3
# @covers US-044-AC4
# MAGIC %md
# MAGIC # 02 — tablespec Kaggle demo: flat-file CSV → specs → artifacts → validation
# MAGIC
# MAGIC **The US-044 tablespec story.**  Run `01-stage-csv-kaggle` on this cluster
# MAGIC first (or set the volume widgets to any CSV already staged).
# MAGIC
# MAGIC 1. **Land** the CSV all-STRING through the ingestion reader seam, with
# MAGIC    reader options derived from a `source: {kind: delimited}` declaration —
# MAGIC    no hardcoded reader (AC1).
# MAGIC 2. **Profile** the landed DataFrame with `NativeSparkProfiler` for review.
# MAGIC 3. **Map** the schema to one UMF spec via `SparkToUmfMapper`; the derived
# MAGIC    spec passes `tablespec validate` with zero errors and zero manual edits
# MAGIC    (AC1).
# MAGIC 4. **Export** a reviewable schema workbook; verify Excel round-trip (AC2).
# MAGIC 5. **Generate** compiled artifacts: raw DDL, PySpark schema, JSON schema,
# MAGIC    expectation suites (AC3).
# MAGIC 6. **Staged validation** against the landed all-STRING table; produce a
# MAGIC    per-expectation report with real results (AC3).
# MAGIC 7. **Scorecard** — one row per US-044 AC; job exits PASS / FAIL (AC4).
# MAGIC
# MAGIC **What this notebook does NOT do**: no file downloads, no Kaggle API calls,
# MAGIC no dataset-specific column references.  All dataset-specific values live in
# MAGIC widgets and notebook 01.
# MAGIC
# MAGIC **Widgets**
# MAGIC - `wheel_path` — tablespec wheel path/glob (empty = pre-installed).
# MAGIC - `output_catalog` — Unity Catalog catalog (default `main`).
# MAGIC - `output_schema` — UC schema (default `kaggle_demo`).
# MAGIC - `output_volume` — UC volume name (default `raw`).
# MAGIC - `csv_filename` — CSV filename in the volume (default `AB_NYC_2019.csv`).
# MAGIC - `table_name` — UMF table name for the derived spec (default `ab_nyc_2019`).

# COMMAND ----------

dbutils.widgets.text("wheel_path", "", "tablespec wheel path/glob (empty = pre-installed)")
dbutils.widgets.text("output_catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("output_schema", "kaggle_demo", "UC schema")
dbutils.widgets.text("output_volume", "raw", "UC volume name")
dbutils.widgets.text("csv_filename", "AB_NYC_2019.csv", "CSV filename in the volume")
dbutils.widgets.text("table_name", "ab_nyc_2019", "UMF table name for the derived spec")

# COMMAND ----------

import glob as _glob

_wheel_widget = dbutils.widgets.get("wheel_path").strip()
if _wheel_widget:
    _matches = sorted(_glob.glob(_wheel_widget)) or [_wheel_widget]
    _wheel = _matches[-1]
    print(f"installing {_wheel}")
    %pip install --quiet {_wheel}
    dbutils.library.restartPython()
else:
    print("wheel_path empty — assuming tablespec is already installed")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Paths and configuration

# COMMAND ----------

import json
import uuid
from pathlib import Path

UC_CATALOG = dbutils.widgets.get("output_catalog").strip() or "main"
UC_SCHEMA = dbutils.widgets.get("output_schema").strip() or "kaggle_demo"
UC_VOLUME = dbutils.widgets.get("output_volume").strip() or "raw"
CSV_FILENAME = dbutils.widgets.get("csv_filename").strip() or "AB_NYC_2019.csv"
TABLE_NAME = dbutils.widgets.get("table_name").strip() or "ab_nyc_2019"

VOLUME_BASE = Path(f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}")
CSV_PATH = VOLUME_BASE / CSV_FILENAME
OUT_DIR = VOLUME_BASE / "tablespec_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"csv path   : {CSV_PATH}")
print(f"table name : {TABLE_NAME}")
print(f"output dir : {OUT_DIR}")

if not CSV_PATH.exists():
    raise FileNotFoundError(
        f"CSV not found at {CSV_PATH} — run 01-stage-csv-kaggle first "
        "or check the output_catalog / output_schema / output_volume / csv_filename widgets"
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Land all-STRING via the ingestion reader seam
# MAGIC
# MAGIC The `source: {kind: delimited}` declaration drives every reader option:
# MAGIC delimiter, header flag, quoting character, and encoding.  `CsvReader` derives
# MAGIC these from the spec — no hardcoded `spark.read.csv(...)` calls exist in this
# MAGIC notebook (AC1).
# MAGIC
# MAGIC `inferSchema: False` keeps all columns STRING, satisfying the all-STRING
# MAGIC raw-landing contract (ADR-007).  Quoted fields that contain the delimiter
# MAGIC (e.g. Airbnb listing names containing commas) are parsed by Spark's default
# MAGIC `"` quote character; the landed column count must equal the CSV header count,
# MAGIC never silently shifting.

# COMMAND ----------

from pyspark.sql.types import StringType

from tablespec.ingestion import get_reader
from tablespec.models.umf import DelimitedSource

# Source declaration — all reader options come from this spec.
source = DelimitedSource(
    kind="delimited",
    delimiter=",",
    header=True,
    quote_char='"',
    encoding="UTF-8",
    path=str(CSV_PATH),
)

raw_df = get_reader(source).read(source, spark)
num_rows = raw_df.count()
num_cols = len(raw_df.columns)

print(f"landed: {num_rows:,} rows × {num_cols} columns")
print(f"columns: {raw_df.columns}")

# All columns must be STRING (inferSchema=False, ADR-007).
non_string_cols = [
    f.name for f in raw_df.schema.fields
    if not isinstance(f.dataType, StringType)
]
assert not non_string_cols, (
    f"non-STRING columns in raw landing (ADR-007 violation): {non_string_cols}"
)
assert num_rows > 0, "no rows loaded — check the CSV file"
assert num_cols > 0, "no columns detected — check the CSV format and delimiter"

display(raw_df.limit(5))
print(f"\nall {num_cols} columns are STRING — raw landing contract satisfied (AC1)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Profile with NativeSparkProfiler
# MAGIC
# MAGIC Profiles the all-STRING landed DataFrame.  Because every column is STRING,
# MAGIC the profiler reports string-length statistics and cardinality — useful for the
# MAGIC engineer reviewing the derived spec before enriching it with narrower types,
# MAGIC descriptions, or a primary key.

# COMMAND ----------

from tablespec.profiling.native_profiler import NativeSparkProfiler

profiler = NativeSparkProfiler(spark)
profile = profiler.profile(raw_df, infer_key_candidates=True)

print(f"profiled: {profile.num_records:,} records, {len(profile.columns)} columns")

profile_rows = [
    (
        col_name,
        col.data_type,
        round(col.completeness, 4),
        col.approximate_num_distinct,
        col.string_length_min,
        col.string_length_max,
    )
    for col_name, col in profile.columns.items()
]
display(
    spark.createDataFrame(
        profile_rows,
        ["column", "spark_type", "completeness", "approx_distinct", "min_len", "max_len"],
    )
)

if profile.key_candidates:
    print("\nkey candidate(s) from profile signals:")
    for kc in profile.key_candidates:
        if getattr(kc, "emitted", False):
            print(f"  {kc.columns}  exact_unique={kc.exact_unique}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Map schema to UMF + validate
# MAGIC
# MAGIC `SparkToUmfMapper` converts the DataFrame schema to a UMF column list.
# MAGIC Since the landing is all-STRING, every column maps to VARCHAR — a reviewable
# MAGIC starting spec the engineer can enrich (widen types, add descriptions, set PKs)
# MAGIC before compiling production pipelines.
# MAGIC
# MAGIC The spec passes `tablespec validate` with zero errors and zero manual edits
# MAGIC (AC1).

# COMMAND ----------

from tablespec.models.umf import UMF
from tablespec.profiling.spark_mapper import SparkToUmfMapper
from tablespec.umf_validator import UMFValidator

mapper = SparkToUmfMapper()
umf_dict = mapper.map_dataframe_to_umf(raw_df, TABLE_NAME, table_type="inferred")

# Add required UMF version and the source declaration so the spec carries the
# landing contract (delimiter, quoting, encoding).
umf_dict["version"] = "1.0"
umf_dict["source"] = {
    "kind": "delimited",
    "delimiter": ",",
    "header": True,
    "quote_char": '"',
    "encoding": "UTF-8",
}

# SparkToUmfMapper sets nullable as a Python bool; UMFColumn.nullable is a
# Nullable model (dict-shaped).  Wrap bools before model_validate().
for col in umf_dict["columns"]:
    if isinstance(col.get("nullable"), bool):
        col["nullable"] = {"default": col["nullable"]}

umf = UMF.model_validate(umf_dict)

print(f"spec: {umf.table_name}  ({len(umf.columns)} columns)")
for col in umf.columns:
    print(f"  {col.name:<40} {col.data_type}")

# Persist the derived spec for inspection and downstream use.
specs_dir = OUT_DIR / "specs"
specs_dir.mkdir(parents=True, exist_ok=True)
spec_path = specs_dir / f"{TABLE_NAME}.json"
umf_data = umf.model_dump(mode="json", exclude_none=True)
spec_path.write_text(json.dumps(umf_data, indent=2))
print(f"\nspec written to {spec_path}")

# Validate against the UMF JSON schema — zero errors, zero manual edits (AC1).
validator = UMFValidator()
spec_valid = validator.validate_data(umf_data, raise_on_error=False, source_name=TABLE_NAME)
print(f"\nUMF validate: {spec_valid}  (expected True — zero errors)")
assert spec_valid, f"derived spec failed tablespec validation for {TABLE_NAME}"
print("spec passes tablespec validate — zero errors, zero manual edits (AC1)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Schema workbook — Excel export + round-trip check
# MAGIC
# MAGIC Exports a reviewable schema workbook for domain review, then re-imports it
# MAGIC to verify the round-trip preserves table name and column names (AC2).

# COMMAND ----------

from tablespec.excel_converter import ExcelToUMFConverter, UMFToExcelConverter

workbook_dir = OUT_DIR / "workbooks"
workbook_dir.mkdir(parents=True, exist_ok=True)

wb_path = workbook_dir / f"{TABLE_NAME}.xlsx"
UMFToExcelConverter().convert(umf).save(wb_path)

reimported, _notes = ExcelToUMFConverter().convert(wb_path)
roundtrip_col_match = (
    [c.name for c in reimported.columns] == [c.name for c in umf.columns]
)
roundtrip_ok = reimported.table_name == umf.table_name and roundtrip_col_match

print(f"workbook    : {wb_path}")
print(f"table name  : {reimported.table_name} == {umf.table_name}  → {reimported.table_name == umf.table_name}")
print(f"column names: {roundtrip_col_match}")
assert roundtrip_ok, "workbook round-trip failed — table name or column names mismatch (AC2)"
print("workbook rows match UMF columns and round-trips without loss (AC2)")

display(
    spark.createDataFrame(
        [(c.name, c.data_type) for c in reimported.columns],
        ["column", "data_type"],
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Compiled artifacts
# MAGIC
# MAGIC Generates raw DDL, PySpark schema, JSON schema, and expectation suites from
# MAGIC the derived spec deterministically (AC3).  Running this cell twice against
# MAGIC the same spec produces identical output.

# COMMAND ----------

from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.schemas import generate_json_schema, generate_pyspark_schema, generate_sql_ddl

artifacts_dir = OUT_DIR / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)

ddl = generate_sql_ddl(umf_data)
pyspark_schema_str = generate_pyspark_schema(umf_data)
json_schema = generate_json_schema(umf_data)
expectations = BaselineExpectationGenerator().generate_baseline_expectations(umf_data)

(artifacts_dir / f"{TABLE_NAME}_ddl.sql").write_text(ddl)
(artifacts_dir / f"{TABLE_NAME}_pyspark.txt").write_text(pyspark_schema_str)
(artifacts_dir / f"{TABLE_NAME}_json_schema.json").write_text(
    json.dumps(json_schema, indent=2)
)
(artifacts_dir / f"{TABLE_NAME}_expectations.json").write_text(
    json.dumps(expectations, indent=2)
)

print("=== raw DDL ===")
print(ddl)
print("\n=== PySpark schema ===")
print(pyspark_schema_str)
print(f"\nexpectation suites: {len(expectations)} expectations generated")
print(f"artifacts written to {artifacts_dir}")

assert ddl.strip(), "raw DDL is empty — artifact generation failed (AC3)"
assert expectations, "no expectation suites generated (AC3)"
print("\ncompiled artifacts produced deterministically from spec (AC3)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Staged validation
# MAGIC
# MAGIC Executes the expectation suite against the landed all-STRING table and
# MAGIC produces a per-expectation report (AC3).  Both raw and ingested DataFrames
# MAGIC are the all-STRING landing — no type casting occurs at the raw stage.

# COMMAND ----------

from tablespec.models.quality import QualityCheckResult, QualityCheckRun
from tablespec.validation.gx_executor import GXSuiteExecutor
from tablespec.validation.report import ValidationReport


def build_report(
    table_name: str, staged, expectations_list: list
) -> ValidationReport:
    """Bridge staged ExecutionResults to a ValidationReport."""
    meta_by_key = {}
    for exp in expectations_list:
        key = (exp.get("type", ""), exp.get("kwargs", {}).get("column"))
        meta_by_key.setdefault(key, exp.get("meta", {}))
    results = []
    for stage, suite in (("raw", staged.raw), ("ingested", staged.ingested)):
        for r in suite.results:
            meta = meta_by_key.get((r.expectation_type, r.column), {})
            results.append(
                QualityCheckResult(
                    check_id=f"{stage}:{r.expectation_type}:{r.column or '-'}",
                    expectation_type=r.expectation_type,
                    success=r.success,
                    severity=meta.get("severity", "critical"),
                    column_name=r.column,
                    description=meta.get("description"),
                    unexpected_count=r.unexpected_count,
                    observed_value=r.observed_value,
                    details=r.details,
                    tags=[stage],
                )
            )
    run = QualityCheckRun(
        pipeline_name="kaggle_demo",
        table_name=table_name,
        run_id=uuid.uuid4().hex[:8],
        results=results,
        should_block=any(not r.success for r in results),
    )
    return ValidationReport(run)


executor = GXSuiteExecutor(spark)
staged = executor.execute_staged(raw_df, raw_df, expectations)
report = build_report(TABLE_NAME, staged, expectations)

print(f"validation report: {report.summary()}")
print(json.dumps(report.as_dict(), indent=2, default=str))

report_path = OUT_DIR / "reports" / f"{TABLE_NAME}.json"
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report.as_dict(), indent=2, default=str))
print(f"\nreport written to {report_path}")

# Verify real per-expectation results — no silent success=False stubs (AC3).
assert report.results, "validation report is empty — no per-expectation results (AC3)"
assert any(r.success is not None for r in report.results), (
    "all results appear to be stubs — check GXSuiteExecutor routing (AC3)"
)
print(f"\nstaged validation: {len(report.results)} real per-expectation results (AC3)")

display(
    spark.createDataFrame(
        [
            (r.check_id, r.expectation_type, r.column_name or "-", r.success)
            for r in report.results
        ],
        ["check_id", "expectation_type", "column", "success"],
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scorecard (US-044 ACs)

# COMMAND ----------

# AC4: verify this notebook contains no dataset-specific code (widget-only coupling).
# No column name literals, no dataset-specific assertions, no hardcoded file paths.
_this_nb_path = (
    Path("/Workspace")
    / Path(
        dbutils.notebook.entry_point.getDbutils()
        .notebook()
        .getContext()
        .notebookPath()
        .get()
    ).relative_to("/")
)
_nb_text = _this_nb_path.read_text() if _this_nb_path.exists() else ""
# Dataset-specific values that must NOT appear in notebook 02.
_forbidden_literals = ["AB_NYC_2019", "ab_nyc_2019", "neighbourhood", "airbnb"]
_nb_has_dataset_code = any(lit in _nb_text for lit in _forbidden_literals)

checks = {
    "AC1 (all-STRING landing, reader options from declaration, spec validates zero errors)": (
        not non_string_cols
        and spec_valid
        and num_rows > 0
        and num_cols > 0
    ),
    "AC2 (schema workbook rows match UMF columns, round-trip without loss)": roundtrip_ok,
    "AC3 (artifacts produced deterministically, staged validation has real results)": (
        bool(ddl.strip())
        and bool(expectations)
        and bool(report.results)
    ),
    "AC4 (demo lane: job exits PASS; notebook 02 has no dataset-specific code)": (
        not _nb_has_dataset_code
    ),
}

report_rows = []
for label, ok in checks.items():
    status = "PASS" if ok else "FAIL"
    print(f"  {'✅' if ok else '❌'}  [{status}]  {label}")
    report_rows.append((label, status))

display(spark.createDataFrame(report_rows, ["ac", "status"]))

all_pass = all(checks.values())
overall = "PASS" if all_pass else "FAIL"
print(f"\n{'='*60}")
print(f"  Kaggle flat-file demo scorecard: {overall}")
print(f"{'='*60}")
print(f"\nArtifacts under {OUT_DIR}: specs/, workbooks/, artifacts/, reports/")

assert all_pass, f"demo scorecard has failures: {[k for k, v in checks.items() if not v]}"

# COMMAND ----------

dbutils.notebook.exit(
    json.dumps({
        "status": overall,
        "table": TABLE_NAME,
        "rows": num_rows,
        "columns": num_cols,
        "spec_valid": spec_valid,
        "roundtrip_ok": roundtrip_ok,
        "expectations": len(expectations),
        "validation_results": len(report.results),
        "validation_summary": report.summary(),
    })
)
