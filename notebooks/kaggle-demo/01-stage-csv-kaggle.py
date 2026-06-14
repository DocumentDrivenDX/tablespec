# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Acquire and stage the Kaggle flat-file dataset (US-044)
# MAGIC
# MAGIC **Consumer-side plumbing for the tablespec Kaggle flat-file demo (US-044).**
# MAGIC
# MAGIC Creates a Unity Catalog schema and volume, then acquires and stages the
# MAGIC dataset CSV — by default the NYC Airbnb Open Data file (`AB_NYC_2019.csv`).
# MAGIC tablespec never does any of this: acquiring files and provisioning storage
# MAGIC are permanently consumer plumbing.  Notebook 02 (`02-kaggle-tablespec-demo`)
# MAGIC reads the staged file through the tablespec reader seam.
# MAGIC
# MAGIC **Widgets**
# MAGIC - `csv_url` — Public download URL for the CSV.  If provided the file is
# MAGIC   downloaded directly into the volume.  Leave empty when the file is already
# MAGIC   staged or to stage it manually.
# MAGIC - `output_catalog` — Unity Catalog catalog (default `main`).
# MAGIC - `output_schema` — UC schema (default `kaggle_demo`).
# MAGIC - `output_volume` — UC volume name (default `raw`).
# MAGIC - `csv_filename` — Filename to save or look for in the volume
# MAGIC   (default `AB_NYC_2019.csv`).
# MAGIC - `wheel_path` — tablespec wheel path/glob (empty = pre-installed on cluster).
# MAGIC
# MAGIC **Manual staging (when `csv_url` is empty)**
# MAGIC 1. Download `AB_NYC_2019.csv` from Kaggle (free account):
# MAGIC    `https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data`
# MAGIC 2. Upload to the target volume path printed by this notebook (cell 4).
# MAGIC    Use the Databricks Catalog UI: Catalog ▸ your catalog ▸ your schema
# MAGIC    ▸ Volumes ▸ your volume ▸ Upload.
# MAGIC 3. Re-run this notebook to verify the file is present.

# COMMAND ----------

dbutils.widgets.text("wheel_path", "", "tablespec wheel path/glob (empty = pre-installed)")
dbutils.widgets.text("output_catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("output_schema", "kaggle_demo", "UC schema")
dbutils.widgets.text("output_volume", "raw", "UC volume name")
dbutils.widgets.text("csv_url", "", "CSV download URL (empty = manual staging)")
dbutils.widgets.text("csv_filename", "AB_NYC_2019.csv", "CSV filename in the volume")

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
# MAGIC ## Create Unity Catalog schema and volume

# COMMAND ----------

import json
from pathlib import Path

UC_CATALOG = dbutils.widgets.get("output_catalog").strip() or "main"
UC_SCHEMA = dbutils.widgets.get("output_schema").strip() or "kaggle_demo"
UC_VOLUME = dbutils.widgets.get("output_volume").strip() or "raw"
CSV_FILENAME = dbutils.widgets.get("csv_filename").strip() or "AB_NYC_2019.csv"

VOLUME_BASE = Path(f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}")
CSV_PATH = VOLUME_BASE / CSV_FILENAME

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{UC_CATALOG}`.`{UC_SCHEMA}`")
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{UC_CATALOG}`.`{UC_SCHEMA}`.`{UC_VOLUME}`")
VOLUME_BASE.mkdir(parents=True, exist_ok=True)

print(f"catalog   : {UC_CATALOG}")
print(f"schema    : {UC_SCHEMA}")
print(f"volume    : {UC_VOLUME}")
print(f"csv path  : {CSV_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Acquire the CSV
# MAGIC
# MAGIC Downloads from `csv_url` when provided; otherwise checks for an existing
# MAGIC file and prints manual-staging instructions when the file is absent.

# COMMAND ----------

import urllib.request

csv_url = dbutils.widgets.get("csv_url").strip()

if CSV_PATH.exists():
    print(f"file already present: {CSV_PATH} ({CSV_PATH.stat().st_size:,} bytes)")
elif csv_url:
    print(f"downloading from {csv_url[:100]}...")
    urllib.request.urlretrieve(csv_url, str(CSV_PATH))
    print(f"downloaded: {CSV_PATH} ({CSV_PATH.stat().st_size:,} bytes)")
else:
    print("MANUAL STAGING REQUIRED")
    print(f"\n  Target path: {CSV_PATH}")
    print("\n  Options:")
    print("    A. Set the csv_url widget to a public download URL and re-run.")
    print("    B. Upload the file via the Databricks Catalog UI:")
    print(f"       Catalog > {UC_CATALOG} > {UC_SCHEMA} > Volumes > {UC_VOLUME} > Upload")
    print("\n  Kaggle source (free account):")
    print("    https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data")
    dbutils.notebook.exit(
        json.dumps({"status": "MANUAL_STAGING_REQUIRED", "csv_path": str(CSV_PATH)})
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify the staged file

# COMMAND ----------

preview_df = (
    spark.read
    .option("header", "true")
    .option("sep", ",")
    .option("inferSchema", "false")
    .option("quote", '"')
    .csv(str(CSV_PATH))
)
num_rows = preview_df.count()
num_cols = len(preview_df.columns)

print(f"rows    : {num_rows:,}")
print(f"columns : {num_cols}")
print(f"header  : {preview_df.columns}")
display(preview_df.limit(5))

assert num_rows > 0, f"CSV at {CSV_PATH} appears empty — check the staged file"
assert num_cols > 0, "no columns detected — check the CSV format"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Handoff
# MAGIC
# MAGIC Run `02-kaggle-tablespec-demo` on this cluster with the same
# MAGIC `output_catalog`, `output_schema`, `output_volume`, and `csv_filename`
# MAGIC widget values.

# COMMAND ----------

print("READY")
print(f"  csv_path : {CSV_PATH}")
print(f"  rows     : {num_rows:,}")
print(f"  columns  : {num_cols}")
dbutils.notebook.exit(
    json.dumps({
        "status": "READY",
        "csv_path": str(CSV_PATH),
        "rows": num_rows,
        "columns": num_cols,
    })
)
