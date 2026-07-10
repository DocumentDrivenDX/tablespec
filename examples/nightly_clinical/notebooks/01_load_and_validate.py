# Databricks notebook source
# MAGIC %md
# MAGIC # Nightly clinical load — raw → ingested → gate
# MAGIC
# MAGIC Task 1 of the `nightly_clinical` job. Runs **in the workspace** on the
# MAGIC notebook's native `spark` session — no Databricks Connect, no token, and
# MAGIC no extra pip installs (so it runs on serverless without fighting the
# MAGIC immutable package constraints).
# MAGIC
# MAGIC 1. Load the nightly CSV from a UC Volume into `raw_<table>` (all STRING).
# MAGIC 2. Run the **tablespec-generated** transform → typed `ingested_<table>`.
# MAGIC 3. Apply a lightweight inline gate; fail the task on violations so the
# MAGIC    downstream dbt task never builds from bad data.
# MAGIC
# MAGIC Full tablespec Great Expectations validation runs in the data-profiling
# MAGIC app (Load Results tab) and the local `db_validate.py`, where tablespec is
# MAGIC installed. Task 2 (the dbt task) then builds the final model from `raw_<table>`.

# COMMAND ----------
dbutils.widgets.text("catalog", "dev")
dbutils.widgets.text("target_schema", "test_main_clinical")
dbutils.widgets.text("table", "encounter")
# Where the nightly CSVs land (the notebook globs <table>*.csv here).
dbutils.widgets.text("landing_dir", "/Volumes/dev/test_main_profiler/ab_runs")
# The committed ingest SQL for this table (synced with the bundle).
dbutils.widgets.text("ingest_sql_path", "../sql/encounter.ingest.sql")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("target_schema")
table = dbutils.widgets.get("table")
landing_dir = dbutils.widgets.get("landing_dir")
ingest_sql_path = dbutils.widgets.get("ingest_sql_path")

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")
print(f"Loading {table} into {catalog}.{schema}")

# COMMAND ----------
# MAGIC %md ### 1. Create raw + ingested tables and split the transform
# MAGIC
# MAGIC Same statement-splitting as the local loader: strip line comments first
# MAGIC (they contain ';'), then split on the terminator.

# COMMAND ----------
from pathlib import Path

sql_text = Path(ingest_sql_path).read_text(encoding="utf-8")
no_comments = "\n".join(
    ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")
)
statements = [s.strip() for s in no_comments.split(";") if s.strip()]
creates = [s for s in statements if s.upper().startswith("CREATE TABLE")]
transform = next(s for s in statements if s.upper().startswith("INSERT INTO"))

for stmt in creates:
    spark.sql(stmt)
spark.sql(f"TRUNCATE TABLE raw_{table}")
spark.sql(f"TRUNCATE TABLE ingested_{table}")

raw_cols = [f.name for f in spark.table(f"raw_{table}").schema.fields]

# COMMAND ----------
# MAGIC %md ### 2. Load the CSV into `raw_<table>`
# MAGIC
# MAGIC Timestamp/metadata columns are GENERATED here, not trusted from the file;
# MAGIC CSV columns absent from the raw schema (drift) are dropped and reported.

# COMMAND ----------
from pyspark.sql import functions as F

GEN_TS_STRING = {"ingest_datetime", "META_Load_DTTM"}
GEN_TS_COL = "_load_ts"
GEN_SOURCE_FILE = "_source_file"
generated = {GEN_TS_COL, GEN_SOURCE_FILE, *GEN_TS_STRING}

# Resolve the exact file: UC Volumes don't support glob wildcards in
# spark.read, so list the directory and pick the newest <table>*.csv.
matches = sorted(
    f.path
    for f in dbutils.fs.ls(landing_dir)
    if f.name.startswith(table) and f.name.endswith(".csv")
)
if not matches:
    raise Exception(f"No {table}*.csv found in {landing_dir}")
csv_path = matches[-1]
print(f"reading {csv_path}")
csv = (
    spark.read.option("header", True)
    .option("mode", "PERMISSIVE")
    .csv(csv_path)
)
# Everything arrives as string; keep it that way for the raw landing zone.
# Carry the real source filename (UC bans input_file_name(); use _metadata).
csv = csv.select(
    *[F.col(c).cast("string").alias(c) for c in csv.columns],
    F.reverse(F.split(F.col("_metadata.file_path"), "/"))[0].alias("_srcfile"),
)
csv.createOrReplaceTempView(f"_stage_{table}")

file_cols = [c for c in csv.columns if c != "_srcfile"]
dropped = [c for c in file_cols if c not in raw_cols]          # drift
missing = [c for c in raw_cols if c not in file_cols and c not in generated]
keep = [c for c in file_cols if c in raw_cols and c not in generated]

proj = []
for c in raw_cols:
    if c == GEN_TS_COL:
        proj.append(f"current_timestamp() AS {c}")
    elif c == GEN_SOURCE_FILE:
        proj.append(f"`_srcfile` AS {c}")
    elif c in GEN_TS_STRING:
        proj.append(f"date_format(current_timestamp(),'yyyy-MM-dd HH:mm:ss') AS {c}")
    elif c in keep:
        proj.append(f"`{c}`")
    else:
        proj.append(f"CAST(NULL AS STRING) AS {c}")

spark.sql(
    f"INSERT INTO raw_{table} SELECT {', '.join(proj)} FROM _stage_{table}"
)
raw_n = spark.table(f"raw_{table}").count()
print(f"raw_{table}: {raw_n} rows | dropped(drift)={dropped} | null-filled={missing}")

# COMMAND ----------
# MAGIC %md ### 3. Transform raw → ingested (tablespec-generated casts)

# COMMAND ----------
spark.sql(transform)
ing_n = spark.table(f"ingested_{table}").count()
print(f"ingested_{table}: {ing_n} rows")
display(spark.sql(f"SELECT * FROM ingested_{table} LIMIT 5"))

# COMMAND ----------
# MAGIC %md ### 4. Inline gate (pure Spark)
# MAGIC
# MAGIC A lightweight structural check that needs no extra packages: rows landed,
# MAGIC the key column is fully populated, and no rows were lost in the transform.
# MAGIC The authoritative Great Expectations validation (from the tablespec-generated
# MAGIC suite) runs in the app's Load Results tab and in `db_validate.py`.

# COMMAND ----------
from pyspark.sql import functions as F

key = f"{table}_id"
ing = spark.table(f"ingested_{table}")
null_keys = ing.where(F.col(key).isNull()).count()
col_count = len(ing.columns)

failures = []
if ing_n == 0:
    failures.append("ingested table is empty")
if raw_n != ing_n:
    failures.append(f"row-count mismatch raw={raw_n} ingested={ing_n}")
if null_keys:
    failures.append(f"{null_keys} null {key} value(s)")

print(f"gate: rows={ing_n}, columns={col_count}, null {key}={null_keys}")
if failures:
    raise Exception("Inline gate failed: " + "; ".join(failures))
print("gate PASSED")

# COMMAND ----------
# Surface counts to the job UI + downstream tasks.
dbutils.notebook.exit(
    f'{{"table":"{table}","raw":{raw_n},"ingested":{ing_n},"null_keys":{null_keys}}}'
)
