# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — tablespec Northwind demo: database → specs → artifacts → validation
# MAGIC
# MAGIC **The US-039 flow, live.** Point tablespec at a SQL Server database and:
# MAGIC
# MAGIC 1. **Discover** one UMF spec per table (`JdbcToUmfMapper` — all connectivity
# MAGIC    is Spark's JDBC connector; tablespec opens no connection of its own)
# MAGIC 2. **Validate** every discovered spec (`UMFValidator`)
# MAGIC 3. **Export** a reviewable schema workbook per table (Excel round-trip)
# MAGIC 4. **Generate** FK-aware sample data from the specs
# MAGIC 5. **Land** typed tables through the reader seam and run **staged
# MAGIC    validation**, producing a per-table validation report
# MAGIC
# MAGIC Run `01-provision-sqlserver-northwind` on this cluster first (or set the
# MAGIC widgets to any reachable SQL Server with Northwind).
# MAGIC
# MAGIC **Widgets**
# MAGIC - `wheel_path` — path/glob of the tablespec wheel to install (empty = assume
# MAGIC   tablespec is already installed on the cluster)
# MAGIC - `jdbc_url` — Northwind JDBC URL (empty = read the handoff from notebook 01)
# MAGIC - `jdbc_user` — login (default `sa`)
# MAGIC - `password_env` — name of the env var holding the password (tablespec only
# MAGIC   ever sees this *reference*; empty = read notebook 01's driver-local handoff
# MAGIC   into `NORTHWIND_SA_PASSWORD`)

# COMMAND ----------

dbutils.widgets.text("wheel_path", "", "tablespec wheel path/glob (empty = preinstalled)")
dbutils.widgets.text("jdbc_url", "", "Northwind JDBC URL (empty = notebook 01 handoff)")
dbutils.widgets.text("jdbc_user", "sa", "JDBC user")
dbutils.widgets.text("password_env", "", "Env var holding the password (empty = notebook 01 handoff)")

# COMMAND ----------

import glob

_wheel_widget = dbutils.widgets.get("wheel_path").strip()
if _wheel_widget:
    _matches = sorted(glob.glob(_wheel_widget)) or [_wheel_widget]
    _wheel = _matches[-1]
    print(f"installing {_wheel}")
    %pip install --quiet {_wheel}
    dbutils.library.restartPython()
else:
    print("wheel_path empty — assuming tablespec is already installed")

# COMMAND ----------

import json
import os
import uuid
from pathlib import Path

STATE_DIR = Path("/local_disk0/northwind_demo")
OUT_DIR = STATE_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

jdbc_url = dbutils.widgets.get("jdbc_url").strip() or (
    (STATE_DIR / "jdbc_url").read_text().strip()
    if (STATE_DIR / "jdbc_url").exists()
    else ""
)
if not jdbc_url:
    raise ValueError("No jdbc_url widget and no notebook-01 handoff found — run 01 first")

password_env = dbutils.widgets.get("password_env").strip()
if not password_env:
    password_env = "NORTHWIND_SA_PASSWORD"
    handoff = STATE_DIR / "sa_password"
    if not handoff.exists():
        raise ValueError("No password_env widget and no notebook-01 handoff — run 01 first")
    os.environ[password_env] = handoff.read_text().strip()

jdbc_user = dbutils.widgets.get("jdbc_user").strip() or "sa"
print(f"endpoint: {jdbc_url}")
print(f"credential: env reference {password_env!r} (never stored in specs)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Discover — one validated UMF per table
# MAGIC
# MAGIC The spec carries the connection *parameters*; the credential exists only as
# MAGIC a **named reference** (`password_secret_ref`). A literal `password` field
# MAGIC would fail model validation.

# COMMAND ----------

from tablespec.models.umf import JdbcSource
from tablespec.profiling.jdbc_mapper import JdbcToUmfMapper

MSSQL_DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"

spec = JdbcSource(
    kind="jdbc",
    url=jdbc_url,
    dbtable="INFORMATION_SCHEMA.TABLES",  # connection spec; ignored by discover()
    driver=MSSQL_DRIVER if jdbc_url.startswith("jdbc:sqlserver:") else None,
    user=jdbc_user,
    password_secret_ref=password_env,
)

discovered = {u.table_name: u for u in JdbcToUmfMapper().discover(spec, spark)}
print(f"discovered {len(discovered)} tables")

summary_rows = []
for name, umf in sorted(discovered.items()):
    fks = (umf.relationships.foreign_keys if umf.relationships else None) or []
    summary_rows.append(
        (
            name,
            umf.canonical_name,
            len(umf.columns),
            ", ".join(umf.primary_key or []),
            "; ".join(f"{fk.column}→{fk.references_table}.{fk.references_column}" for fk in fks),
        )
    )
display(
    spark.createDataFrame(
        summary_rows, ["table", "source_name", "columns", "primary_key", "foreign_keys"]
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Validate every discovered spec

# COMMAND ----------

from tablespec.umf_validator import UMFValidator

validator = UMFValidator()
validation = {
    name: validator.validate_data(
        umf.model_dump(mode="json", exclude_none=True), source_name=name
    )
    for name, umf in discovered.items()
}
display(spark.createDataFrame(sorted(validation.items()), ["table", "valid"]))
assert all(validation.values()), f"specs failed validation: {[n for n, ok in validation.items() if not ok]}"
print(f"all {len(validation)} discovered specs pass tablespec validation")

# also persist the specs for inspection / downstream compile
specs_dir = OUT_DIR / "specs" / "tables"
specs_dir.mkdir(parents=True, exist_ok=True)
for name, umf in discovered.items():
    (specs_dir / f"{name}.json").write_text(
        json.dumps(umf.model_dump(mode="json", exclude_none=True), indent=2)
    )
print(f"specs written to {specs_dir}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Schema workbook — Excel export + round-trip check

# COMMAND ----------

from tablespec.excel_converter import ExcelToUMFConverter, UMFToExcelConverter

workbook_dir = OUT_DIR / "workbooks"
workbook_dir.mkdir(parents=True, exist_ok=True)
exporter = UMFToExcelConverter()
importer = ExcelToUMFConverter()

roundtrip_ok = {}
for name, umf in discovered.items():
    workbook_path = workbook_dir / f"{name}.xlsx"
    exporter.convert(umf).save(workbook_path)
    reimported, _notes = importer.convert(workbook_path)
    roundtrip_ok[name] = (
        reimported.table_name == umf.table_name
        and [c.name for c in reimported.columns] == [c.name for c in umf.columns]
        and reimported.primary_key == umf.primary_key
    )

display(spark.createDataFrame(sorted(roundtrip_ok.items()), ["table", "roundtrip_ok"]))
assert all(roundtrip_ok.values())
print(f"{len(roundtrip_ok)} workbooks at {workbook_dir}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · FK-aware sample data from the discovered specs

# COMMAND ----------

import csv

from tablespec.sample_data import GenerationConfig, SampleDataGenerator

sample_dir = OUT_DIR / "sample_data"
sample_dir.mkdir(parents=True, exist_ok=True)
generator = SampleDataGenerator(
    input_dir=OUT_DIR / "specs",
    output_dir=sample_dir,
    config=GenerationConfig(
        num_members=120, key_pool_size=6, key_distribution_80_20=False, random_seed=42
    ),
)
assert generator.run_generation() is True


def _rows(name: str) -> list[dict[str, str]]:
    with (sample_dir / f"{name}.txt").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


counts = {name: len(_rows(name)) for name in discovered}
display(spark.createDataFrame(sorted(counts.items()), ["table", "generated_rows"]))

customer_ids = {r["CustomerID"] for r in _rows("customers") if r["CustomerID"]}
order_customer_ids = {r["CustomerID"] for r in _rows("orders") if r["CustomerID"]}
fk_holds = bool(order_customer_ids) and order_customer_ids <= customer_ids
print(f"FK integrity (orders.customer_id ⊆ customers.customer_id): {fk_holds}")
assert fk_holds

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Land typed tables + staged validation report
# MAGIC
# MAGIC Tables land **native-typed** through the reader seam (never round-tripped
# MAGIC through string parsing — ADR-015). Suites composed for a typed source carry
# MAGIC **no string-shape raw checks** (FEAT-031 SUITE-01/02).

# COMMAND ----------

from tablespec.gx_baseline import (
    STRING_SHAPE_EXPECTATION_TYPES,
    BaselineExpectationGenerator,
)
from tablespec.ingestion import get_reader
from tablespec.ingestion.raw_ingester import build_column_lookup, map_headers
from tablespec.models.quality import QualityCheckResult, QualityCheckRun
from tablespec.validation.gx_executor import GXSuiteExecutor
from tablespec.validation.report import ValidationReport

DEMO_TABLES = ("customers", "orders", "order_details")


def land_typed(umf):
    source = umf.source
    df = get_reader(source).read(source, spark)
    mapping = map_headers(df.columns, build_column_lookup(umf))
    return df.select(*[df[raw].alias(m.umf_column) for raw, m in mapping.items()])


def build_report(table_name, staged, expectations) -> ValidationReport:
    # Inline bridge from staged ExpectationResults to the ValidationReport
    # surface (a shipped adapter is tracked as bead tablespec-72c03317).
    meta_by_key = {}
    for exp in expectations:
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
        pipeline_name="northwind_demo",
        table_name=table_name,
        run_id=uuid.uuid4().hex[:8],
        results=results,
        should_block=any(not r.success for r in results),
    )
    return ValidationReport(run)


composer = BaselineExpectationGenerator()
executor = GXSuiteExecutor(spark)
report_rows = []

for name in DEMO_TABLES:
    umf = discovered[name]
    df = land_typed(umf)
    print(f"\n=== {name} (typed landing) ===")
    display(df)

    expectations = composer.generate_baseline_expectations(
        umf.model_dump(mode="json", exclude_none=True)
    )
    composed_types = {e["type"] for e in expectations}
    assert not (composed_types & STRING_SHAPE_EXPECTATION_TYPES), (
        f"string-shape raw checks composed for typed source {name}"
    )

    staged = executor.execute_staged(df, df, expectations)
    report = build_report(name, staged, expectations)
    print(f"[validation report] {name}: {report.summary()}")
    print(json.dumps(report.as_dict(), indent=2, default=str))
    report_rows.append((name, report.total, report.passed, report.failed, report.success))

    report_path = OUT_DIR / "reports" / f"{name}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.as_dict(), indent=2, default=str))

display(
    spark.createDataFrame(report_rows, ["table", "expectations", "passed", "failed", "success"])
)

# zero silent NULL-out: the typed orders landing keeps every order_date value
orders_df = land_typed(discovered["orders"])
null_dates = orders_df.filter(orders_df["order_date"].isNull()).count()
total = orders_df.count()
print(f"orders.order_date: {total} rows, {null_dates} NULLs after typed landing")
assert null_dates == 0

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scorecard

# COMMAND ----------

checks = {
    "AC1 discovery (one UMF per table, FKs, no credentials in specs)": len(discovered) > 0
    and all(
        os.environ[password_env]
        not in json.dumps(u.model_dump(mode="json", exclude_none=True))
        for u in discovered.values()
    ),
    "AC2 sanitization (order_details ← 'Order Details')": "order_details" in discovered
    and discovered["order_details"].canonical_name == "Order Details",
    "AC3 every spec validates": all(validation.values()),
    "AC4 schema workbooks round-trip": all(roundtrip_ok.values()),
    "AC5 FK-aware sample data": fk_holds,
    "AC6 staged validation reports (typed, no string-shape raw checks)": all(
        row[4] for row in report_rows
    ),
}
for label, ok in checks.items():
    print(f"  {'✅' if ok else '❌'}  {label}")
assert all(checks.values()), "demo scorecard has failures"
print(f"\nArtifacts under {OUT_DIR}: specs/, workbooks/, sample_data/, reports/")
dbutils.notebook.exit(json.dumps({"status": "PASS", "tables": len(discovered)}))
