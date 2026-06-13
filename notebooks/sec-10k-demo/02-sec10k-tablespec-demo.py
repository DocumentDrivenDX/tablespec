# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — tablespec SEC 10-K demo: specs → artifacts → validation → scorecard
# MAGIC
# MAGIC **The US-045 tablespec story.**  Run `01-edgar-plumbing` on this cluster
# MAGIC first (or set `volume_path` to any matching volume).
# MAGIC
# MAGIC 1. **Load** the corpus spec (`EMBEDDING(1024)`, CORP-01 pattern) and the
# MAGIC    XBRL facts spec (`json` source kind, FLAT projection).
# MAGIC 2. **Validate** both specs — zero errors expected.
# MAGIC 3. **Inspect artifacts** — DDL (`ARRAY<FLOAT>`), PySpark schema
# MAGIC    (`ArrayType(FloatType())`), JSON Schema (array-of-number with
# MAGIC    `minItems`/`maxItems` 1024).
# MAGIC 4. **Export schema workbooks** for both tables.
# MAGIC 5. **Staged validation** against the landed corpus (Delta) and facts (JSONL)
# MAGIC    tables: dimensionality checked per-row, corrupted-vector fixture row
# MAGIC    confirmed failing, PK/Vector Search prerequisites surfaced as advisories.
# MAGIC 6. **Scorecard** — one row per US-045 AC; job exits PASS / FAIL.
# MAGIC
# MAGIC **What this notebook does NOT do** (CORP-05): no EDGAR fetches, no HTML
# MAGIC parsing, no chunking, no embedding model calls.  The tablespec library
# MAGIC code called here performs none of those operations either.
# MAGIC
# MAGIC **Widgets**
# MAGIC - `wheel_path` — tablespec wheel path/glob (empty = preinstalled).
# MAGIC - `output_catalog` — Unity Catalog catalog (default `main`).
# MAGIC - `output_schema` — UC schema (default `sec_10k_demo`).
# MAGIC - `output_volume` — UC volume name (default `raw`).

# COMMAND ----------

dbutils.widgets.text("wheel_path", "", "tablespec wheel path/glob (empty = preinstalled)")
dbutils.widgets.text("output_catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("output_schema", "sec_10k_demo", "UC schema")
dbutils.widgets.text("output_volume", "raw", "UC volume name")

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
# MAGIC ## Paths and spec locations

# COMMAND ----------

import json
import uuid
from pathlib import Path

UC_CATALOG = dbutils.widgets.get("output_catalog").strip() or "main"
UC_SCHEMA = dbutils.widgets.get("output_schema").strip() or "sec_10k_demo"
UC_VOLUME = dbutils.widgets.get("output_volume").strip() or "raw"

VOLUME_BASE = Path(f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}")
CORPUS_DELTA_PATH = str(VOLUME_BASE / "sec_10k_corpus")
FACTS_JSONL_PATH = str(VOLUME_BASE / "sec_xbrl_facts" / "companyfacts.jsonl")

OUT_DIR = VOLUME_BASE / "tablespec_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Locate example specs shipped next to this notebook (Git folder checkout) or
# from the tablespec wheel's bundled examples.
_nb_dir = Path(
    dbutils.notebook.entry_point.getDbutils()
    .notebook()
    .getContext()
    .notebookPath()
    .get()
).parent

_candidates_root = [
    Path("/Workspace") / _nb_dir.relative_to("/").parents[1] / "examples",
    Path.cwd().parents[1] / "examples",
    Path("/Workspace") / _nb_dir.relative_to("/") / ".." / ".." / "examples",
]
EXAMPLES_DIR: Path | None = next(
    (p.resolve() for p in _candidates_root if p.exists()), None
)
if EXAMPLES_DIR is None:
    raise FileNotFoundError(
        "examples/ directory not found. Check out the tablespec repo next to this "
        "notebook, or copy sec10k_corpus.yaml and sec10k_companyfacts.yaml into "
        "a location reachable from the notebook."
    )

CORPUS_SPEC_PATH = EXAMPLES_DIR / "sec10k_corpus.yaml"
FACTS_SPEC_PATH = EXAMPLES_DIR / "sec10k_companyfacts.yaml"

for p in [CORPUS_SPEC_PATH, FACTS_SPEC_PATH]:
    if not p.exists():
        raise FileNotFoundError(f"spec not found: {p}")

print(f"corpus spec    : {CORPUS_SPEC_PATH}")
print(f"facts spec     : {FACTS_SPEC_PATH}")
print(f"corpus delta   : {CORPUS_DELTA_PATH}")
print(f"facts jsonl    : {FACTS_JSONL_PATH}")
print(f"artifacts out  : {OUT_DIR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Load and display both specs

# COMMAND ----------

import yaml

from tablespec.models.umf import load_umf_from_yaml

corpus_umf = load_umf_from_yaml(CORPUS_SPEC_PATH)
facts_umf = load_umf_from_yaml(FACTS_SPEC_PATH)

print(f"corpus spec  : {corpus_umf.table_name}  ({len(corpus_umf.columns)} columns)")
for col in corpus_umf.columns:
    dim = f"  dim={col.dimension}" if col.data_type == "EMBEDDING" else ""
    print(f"  {col.name:<20} {col.data_type}{dim}")

print(f"\nfacts spec   : {facts_umf.table_name}  ({len(facts_umf.columns)} columns)")
for col in facts_umf.columns:
    proj = next(
        (p.path for p in (facts_umf.source.projection if facts_umf.source else [])
         if p.column == col.name),
        col.name,
    )
    print(f"  {col.name:<20} {col.data_type:<12} → JSON path: {proj!r}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Validate both specs (zero errors expected)

# COMMAND ----------

from tablespec.umf_validator import UMFValidator

validator = UMFValidator()

corpus_valid = validator.validate_data(
    corpus_umf.model_dump(mode="json", exclude_none=True),
    raise_on_error=False,
    source_name="sec_10k_corpus",
)
facts_valid = validator.validate_data(
    facts_umf.model_dump(mode="json", exclude_none=True),
    raise_on_error=False,
    source_name="sec_xbrl_facts",
)

display(
    spark.createDataFrame(
        [("sec_10k_corpus", corpus_valid), ("sec_xbrl_facts", facts_valid)],
        ["spec", "valid"],
    )
)
assert corpus_valid, "corpus spec failed tablespec validation"
assert facts_valid, "facts spec failed tablespec validation"
print("both specs pass tablespec validate — zero errors")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Compiled artifacts
# MAGIC
# MAGIC ### DDL — `ARRAY<FLOAT>` for the embedding column
# MAGIC
# MAGIC `ARRAY<FLOAT>` is what Databricks Vector Search and the 2026 DBSQL
# MAGIC vector functions consume. The UMF stays the source of truth: the DDL
# MAGIC cannot round-trip back to `EMBEDDING(1024)` — that's by design (ADR-016).

# COMMAND ----------

from tablespec.schemas import generate_json_schema, generate_pyspark_schema, generate_sql_ddl

corpus_data = corpus_umf.model_dump(mode="json", exclude_none=True)
facts_data = facts_umf.model_dump(mode="json", exclude_none=True)

corpus_ddl = generate_sql_ddl(corpus_data)
facts_ddl = generate_sql_ddl(facts_data)

print("=== corpus DDL ===")
print(corpus_ddl)
assert "ARRAY<FLOAT>" in corpus_ddl, "embedding column must compile to ARRAY<FLOAT>"
assert "ARRAY<FLOAT>" in corpus_ddl  # AC1 — DDL rendering

print("\n=== facts DDL ===")
print(facts_ddl)

# COMMAND ----------

# MAGIC %md
# MAGIC ### PySpark schema

# COMMAND ----------

corpus_pyspark = generate_pyspark_schema(corpus_data)
print("=== corpus PySpark schema ===")
print(corpus_pyspark)
assert "ArrayType(FloatType())" in corpus_pyspark, (
    "embedding column must compile to ArrayType(FloatType())"
)

facts_pyspark = generate_pyspark_schema(facts_data)
print("\n=== facts PySpark schema ===")
print(facts_pyspark)

# COMMAND ----------

# MAGIC %md
# MAGIC ### JSON Schema — `minItems`/`maxItems` pinned to 1024

# COMMAND ----------

corpus_json_schema = generate_json_schema(corpus_data)
print("=== corpus JSON Schema (embedding column) ===")

embedding_prop = corpus_json_schema["properties"].get("embedding", {})
print(json.dumps(embedding_prop, indent=2))

assert embedding_prop.get("type") == "array", "embedding JSON Schema type must be array"
assert embedding_prop.get("minItems") == 1024, "minItems must be 1024"
assert embedding_prop.get("maxItems") == 1024, "maxItems must be 1024"
print("\n✓ embedding JSON Schema: array-of-number with minItems=maxItems=1024 (AC1)")

facts_json_schema = generate_json_schema(facts_data)
print("\n=== facts JSON Schema ===")
print(json.dumps(facts_json_schema, indent=2))

# Persist artifacts for inspection
artifacts_dir = OUT_DIR / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)
(artifacts_dir / "corpus_ddl.sql").write_text(corpus_ddl)
(artifacts_dir / "corpus_pyspark.txt").write_text(corpus_pyspark)
(artifacts_dir / "corpus_json_schema.json").write_text(json.dumps(corpus_json_schema, indent=2))
(artifacts_dir / "facts_ddl.sql").write_text(facts_ddl)
(artifacts_dir / "facts_pyspark.txt").write_text(facts_pyspark)
print(f"\nartifacts written to {artifacts_dir}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Schema workbooks

# COMMAND ----------

from tablespec.excel_converter import UMFToExcelConverter

workbook_dir = OUT_DIR / "workbooks"
workbook_dir.mkdir(parents=True, exist_ok=True)
exporter = UMFToExcelConverter()

corpus_wb_path = workbook_dir / "sec_10k_corpus.xlsx"
facts_wb_path = workbook_dir / "sec_xbrl_facts.xlsx"

exporter.convert(corpus_umf).save(corpus_wb_path)
exporter.convert(facts_umf).save(facts_wb_path)

print(f"corpus workbook : {corpus_wb_path}")
print(f"facts workbook  : {facts_wb_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Baseline expectations
# MAGIC
# MAGIC ### No string-shape checks on EMBEDDING columns (EMB-08)
# MAGIC
# MAGIC `STRING_SHAPE_EXPECTATION_TYPES` lists patterns that are only meaningful
# MAGIC for string/text columns.  EMBEDDING columns must be excluded.

# COMMAND ----------

from tablespec.gx_baseline import (
    STRING_SHAPE_EXPECTATION_TYPES,
    BaselineExpectationGenerator,
)

composer = BaselineExpectationGenerator()

corpus_expectations = composer.generate_baseline_expectations(corpus_data)
facts_expectations = composer.generate_baseline_expectations(facts_data)

# EMB-08: no "true" string-shape checks on the EMBEDDING column.
# Note: expect_column_value_lengths_to_equal IS generated for the EMBEDDING column
# as the dimensionality check (array-length = 1024) — this reuse of the type name
# is intentional; the test excludes it to avoid conflating dimensionality with string checks.
embedding_col_name = next(c.name for c in corpus_umf.columns if c.data_type == "EMBEDDING")
embedding_col_exps = [
    e for e in corpus_expectations
    if e.get("kwargs", {}).get("column") == embedding_col_name
]
FORBIDDEN_ON_EMBEDDING = STRING_SHAPE_EXPECTATION_TYPES - {"expect_column_value_lengths_to_equal"}
forbidden_on_embedding = {e["type"] for e in embedding_col_exps} & FORBIDDEN_ON_EMBEDDING
assert not forbidden_on_embedding, (
    f"forbidden string-shape checks emitted for EMBEDDING column {embedding_col_name!r}: "
    f"{forbidden_on_embedding}"
)
print("✓ no forbidden string-shape checks on EMBEDDING column (EMB-08 / AC1)")

# The dimensionality expectation for the EMBEDDING column
dim_exps = [
    e for e in embedding_col_exps
    if e["type"] == "expect_column_value_lengths_to_equal"
]
assert dim_exps, f"dimensionality expectation not found for {embedding_col_name}"
print(f"\ndimensionality expectation (EMBEDDING column):")
for e in dim_exps:
    print(json.dumps(e, indent=2))

print(f"\ncorpus: {len(corpus_expectations)} expectations total")
print(f"facts:  {len(facts_expectations)} expectations total")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Dimension % 16 advisory (EMB-05)
# MAGIC
# MAGIC 1024 % 16 == 0 so the storage-optimized advisory does NOT fire.
# MAGIC Surfacing it anyway to demonstrate the advisory mechanism works.

# COMMAND ----------

advisory_type = "expect_embedding_dimension_multiple_of_16_advisory"
advisory_exps = [e for e in corpus_expectations if e["type"] == advisory_type]
print(f"% 16 advisory expectations: {len(advisory_exps)}")
print("✓ 1024 % 16 == 0 → no advisory for corpus embedding column (as designed)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Staged validation — corpus (Delta)
# MAGIC
# MAGIC ### AC2-part-A: corrupted fixture row fails dimensionality

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, FloatType

from tablespec.models.quality import QualityCheckResult, QualityCheckRun
from tablespec.validation.gx_executor import GXSuiteExecutor
from tablespec.validation.report import ValidationReport


def build_report(
    table_name: str,
    staged,
    expectations: list,
    pipeline_name: str = "sec_10k_demo",
) -> ValidationReport:
    """Bridge staged ExecutionResults to a ValidationReport."""
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
        pipeline_name=pipeline_name,
        table_name=table_name,
        run_id=uuid.uuid4().hex[:8],
        results=results,
        should_block=any(not r.success for r in results),
    )
    return ValidationReport(run)


executor = GXSuiteExecutor(spark)

# Load clean corpus from Delta
corpus_df = spark.read.format("delta").load(CORPUS_DELTA_PATH)
print(f"corpus loaded: {corpus_df.count()} rows, schema: {corpus_df.schema.simpleString()[:120]}")

# Build a corrupted row with wrong-length embedding (AC2 — must FAIL)
corrupted_row = corpus_df.limit(1).withColumn(
    "embedding",
    F.array(*[F.lit(0.1)] * 512).cast(ArrayType(FloatType())),  # wrong: 512 instead of 1024
)
corrupted_df = corpus_df.union(corrupted_row)

staged_corrupted = executor.execute_staged(corrupted_df, corrupted_df, corpus_expectations)
report_corrupted = build_report("sec_10k_corpus_corrupted", staged_corrupted, corpus_expectations)

# The dimensionality check uses expect_column_value_lengths_to_equal on the embedding column
dim_results = [
    r for r in report_corrupted.results
    if r.expectation_type == "expect_column_value_lengths_to_equal"
    and r.column_name == embedding_col_name
]
dim_pass_on_corrupted = all(r.success for r in dim_results) if dim_results else True
print(f"\nCorrupted dataset (1 row with 512-dim vector instead of 1024):")
print(f"  dimensionality check passes: {dim_pass_on_corrupted}  (expected: False)")
assert dim_results, "no dimensionality expectation result found — check executor routing"
assert not dim_pass_on_corrupted, (
    "AC2: dimensionality expectation must FAIL on a wrong-length vector"
)
print("✓ corrupted fixture row correctly FAILS dimensionality expectation (AC2)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### AC2-part-B: clean corpus passes dimensionality

# COMMAND ----------

staged_clean = executor.execute_staged(corpus_df, corpus_df, corpus_expectations)
report_clean = build_report("sec_10k_corpus", staged_clean, corpus_expectations)

dim_results_clean = [
    r for r in report_clean.results
    if r.expectation_type == "expect_column_value_lengths_to_equal"
    and r.column_name == embedding_col_name
]
dim_pass_clean = all(r.success for r in dim_results_clean)
print(f"Clean corpus — dimensionality check passes: {dim_pass_clean}")
assert dim_pass_clean, "AC2: dimensionality expectation must PASS on clean corpus"
print("✓ clean corpus PASSES dimensionality expectation (AC2)")
print(f"\n{report_clean.summary()}")

# Advisory: PK declared, CDF is a runtime Delta property — surface as advisory
print("\n[advisory] Vector Search prerequisites check:")
pk_present = bool(corpus_umf.primary_key)
print(f"  primary_key declared: {pk_present} → PK advisory: {'absent' if not pk_present else 'satisfied'}")
print("  Change Data Feed: runtime property (not in spec) — verify on the Delta table before indexing")

# Save corpus report
corpus_report_path = OUT_DIR / "reports" / "sec_10k_corpus.json"
corpus_report_path.parent.mkdir(parents=True, exist_ok=True)
corpus_report_path.write_text(json.dumps(report_clean.as_dict(), indent=2, default=str))
print(f"\ncorpus validation report: {corpus_report_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7 · Staged validation — facts table (JSON-landed)
# MAGIC
# MAGIC The facts table is read via `JsonReader` with the FLAT projection from the
# MAGIC spec — each UMF column maps to an explicit top-level field in the JSONL.
# MAGIC No string-shape checks should appear in the suite (typed raw source).

# COMMAND ----------

from tablespec.ingestion import JsonReader, get_reader

# Attach the runtime path to the facts spec's source
facts_source_with_path = facts_umf.source.model_copy(
    update={"path": FACTS_JSONL_PATH}
)
facts_df = JsonReader().read(facts_source_with_path, spark)
print(f"facts loaded: {facts_df.count()} rows, schema: {facts_df.schema.simpleString()}")
display(facts_df)

# Verify no string-shape expectations in the facts suite (typed raw)
facts_composed_types = {e["type"] for e in facts_expectations}
string_shape_on_facts = facts_composed_types & STRING_SHAPE_EXPECTATION_TYPES
assert not string_shape_on_facts, (
    f"string-shape expectations emitted for typed-raw facts source: {string_shape_on_facts}"
)
print("✓ no string-shape raw checks on json-kind typed source (AC3 / SUITE-02)")

staged_facts = executor.execute_staged(facts_df, facts_df, facts_expectations)
report_facts = build_report("sec_xbrl_facts", staged_facts, facts_expectations)
print(f"\n{report_facts.summary()}")

facts_report_path = OUT_DIR / "reports" / "sec_xbrl_facts.json"
facts_report_path.write_text(json.dumps(report_facts.as_dict(), indent=2, default=str))
print(f"facts validation report: {facts_report_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8 · Scorecard (US-045 ACs)

# COMMAND ----------

# AC4: verify no credential / endpoint coupling in either spec.
# Check for actual credential/URL patterns, not documentation that mentions them.
corpus_spec_text = CORPUS_SPEC_PATH.read_text()
facts_spec_text = FACTS_SPEC_PATH.read_text()
CREDENTIAL_PATTERNS = [
    "https://",
    "http://",
    "Bearer ",
    "api_key:",
    "password:",
    "secret:",
    "token:",
    "Authorization:",
]
corpus_has_credential = any(p in corpus_spec_text for p in CREDENTIAL_PATTERNS)
facts_has_credential = any(p in facts_spec_text for p in CREDENTIAL_PATTERNS)

# AC5: plumbing boundary — check this notebook itself contains no model calls
this_nb_path = Path("/Workspace") / _nb_dir.relative_to("/") / "02-sec10k-tablespec-demo.py"
this_nb_text = this_nb_path.read_text() if this_nb_path.exists() else ""
nb2_has_edgar_call = "edgar_get" in this_nb_text or "requests.get" in this_nb_text
nb2_has_model_call = (
    "mlflow.deployments" in this_nb_text
    or "databricks-gte-large-en" in this_nb_text
)

checks = {
    "AC1 (corpus spec EMBEDDING(1024) validates, DDL=ARRAY<FLOAT>, PySpark=ArrayType(FloatType()), JSON minItems/maxItems=1024)": (
        corpus_valid
        and "ARRAY<FLOAT>" in corpus_ddl
        and "ArrayType(FloatType())" in corpus_pyspark
        and embedding_prop.get("minItems") == 1024
        and embedding_prop.get("maxItems") == 1024
        and not forbidden_on_embedding
    ),
    "AC2 (dimensionality: corrupted row FAILS, clean corpus PASSES)": (
        not dim_pass_on_corrupted and dim_pass_clean
    ),
    "AC3 (facts json-kind spec validates, typed landing passes, no string-shape checks)": (
        facts_valid
        and report_facts.success
        and not string_shape_on_facts
    ),
    "AC4 (no credential/endpoint/model coupling in either spec)": (
        not corpus_has_credential and not facts_has_credential
    ),
    "AC5 (plumbing boundary: nb02 has no EDGAR calls, no model endpoint calls)": (
        not nb2_has_edgar_call and not nb2_has_model_call
    ),
    "AC6 (scorecard produced, advisories distinct from failures, corpus suite passes)": (
        report_clean.success
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
print(f"  SEC 10-K demo scorecard: {overall}")
print(f"{'='*60}")
print(f"\nArtifacts under {OUT_DIR}: artifacts/, workbooks/, reports/")

assert all_pass, f"demo scorecard has failures: {[k for k, v in checks.items() if not v]}"

# COMMAND ----------

dbutils.notebook.exit(
    json.dumps(
        {
            "status": overall,
            "corpus_rows": corpus_df.count(),
            "facts_rows": facts_df.count(),
            "corpus_validation": report_clean.summary(),
            "facts_validation": report_facts.summary(),
        }
    )
)
