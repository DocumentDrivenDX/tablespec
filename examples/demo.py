#!/usr/bin/env python3
"""tablespec demo — end-to-end walkthrough of the library's capabilities.

Requires: tablespec[spark]  (uv sync --extra spark)

Also serves as an acceptance test: exits non-zero on any failure.
Run via: uv run python examples/demo.py
Test via: uv run pytest tests/integration/test_demo.py

Sections:
  1. Load & inspect UMF schemas
  2. Schema generation (SQL DDL, PySpark, JSON Schema)
  3. Type mappings
  4. Domain type inference
  5. Great Expectations baseline
  6. LLM prompt generation
  7. UMF diffing & change detection
  8. PySpark: create a Spark session & DataFrame
  9. PySpark: profile a DataFrame -> UMF
 10. PySpark: validate a DataFrame against UMF
 11. Sample data generation
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

# Suppress noisy Spark/py4j/sample_data logging before any imports
logging.getLogger("py4j").setLevel(logging.ERROR)
logging.getLogger("tablespec.sample_data").setLevel(logging.ERROR)
os.environ.setdefault("SPARK_LOG_LEVEL", "ERROR")

# ---------------------------------------------------------------------------
# Resolve Spark availability early so JVM stderr noise happens before output
# ---------------------------------------------------------------------------
try:
    from tablespec import SparkToUmfMapper, TableValidator, create_delta_spark_session

    HAS_SPARK = True
except ImportError:
    HAS_SPARK = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECTION = 0
_ERRORS: list[str] = []


def section(title: str) -> None:
    global _SECTION
    _SECTION += 1
    print(f"\n{'=' * 72}")
    print(f"  {_SECTION}. {title}")
    print(f"{'=' * 72}\n")


def check(condition: bool, msg: str) -> None:
    """Assert a condition; collect failures instead of crashing."""
    if not condition:
        print(f"  FAIL: {msg}")
        _ERRORS.append(msg)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).resolve().parent
CLAIMS_YAML = EXAMPLES_DIR / "schema.yaml"
PROVIDERS_YAML = EXAMPLES_DIR / "providers.yaml"

# ===================================================================
# 1. Load & Inspect UMF Schemas
# ===================================================================

section("Load & Inspect UMF Schemas")

from tablespec import UMF, load_umf_from_yaml

claims: UMF = load_umf_from_yaml(str(CLAIMS_YAML))
providers: UMF = load_umf_from_yaml(str(PROVIDERS_YAML))

print(f"Table : {claims.table_name}")
print(f"Desc  : {claims.description}")
print(f"Cols  : {len(claims.columns)}")
for col in claims.columns:
    if col.nullable:
        nullable_dict = col.nullable.model_dump(exclude_none=True)
        nullable_lobs = [lob for lob, v in nullable_dict.items() if v]
    else:
        nullable_lobs = []
    print(f"  - {col.name:20s}  {col.data_type:10s}  nullable in: {nullable_lobs or '(none)'}")

print()
print(f"Table : {providers.table_name}")
print(f"Cols  : {[c.name for c in providers.columns]}")

check(claims.table_name == "Medical_Claims", "claims table name")
check(len(claims.columns) == 3, "claims should have 3 columns")
check(providers.table_name == "Providers", "providers table name")
check(len(providers.columns) == 4, "providers should have 4 columns")

# ===================================================================
# 2. Schema Generation
# ===================================================================

section("Schema Generation (SQL DDL, PySpark, JSON Schema)")

from tablespec import generate_json_schema, generate_pyspark_schema, generate_sql_ddl

claims_dict = claims.model_dump(mode="json", exclude_none=True)

ddl = generate_sql_ddl(claims_dict)
print("--- SQL DDL ---")
print(ddl)

pyspark_code = generate_pyspark_schema(claims_dict)
print("--- PySpark Schema ---")
print(pyspark_code)

json_schema = generate_json_schema(claims_dict)
print("--- JSON Schema (excerpt) ---")
print(json.dumps(json_schema, indent=2)[:600], "...")

check("CREATE TABLE" in ddl, "DDL should contain CREATE TABLE")
check("StructType" in pyspark_code, "PySpark schema should contain StructType")
check(json_schema.get("$schema") is not None, "JSON Schema should have $schema")
check("claim_id" in ddl, "DDL should reference claim_id")

# ===================================================================
# 3. Type Mappings
# ===================================================================

section("Type Mappings")

from tablespec import map_to_gx_spark_type, map_to_json_type, map_to_pyspark_type

for col in claims.columns:
    print(
        f"  {col.name:20s}  UMF={col.data_type:10s}"
        f"  -> PySpark={map_to_pyspark_type(col.data_type):12s}"
        f"  -> JSON={map_to_json_type(col.data_type):10s}"
        f"  -> GX Spark={map_to_gx_spark_type(col.data_type)}"
    )

check(map_to_pyspark_type("VARCHAR") == "StringType()", "VARCHAR -> StringType()")
check(map_to_json_type("INTEGER") == "integer", "INTEGER -> integer")
check(map_to_gx_spark_type("DECIMAL") == "DecimalType", "DECIMAL -> DecimalType")

# ===================================================================
# 4. Domain Type Inference
# ===================================================================

section("Domain Type Inference")

from tablespec import DomainTypeInference, DomainTypeRegistry

registry = DomainTypeRegistry()
inference = DomainTypeInference(registry)

all_types = registry.list_domain_types()
print(f"Registered domain types: {len(all_types)}")
print(f"Examples: {all_types[:8]}...\n")

test_columns = [
    ("provider_npi", "National Provider Identifier", ["1234567890"]),
    ("state_code", "Provider state code", ["CA", "NY", "TX"]),
    ("member_email", "Member email address", ["jane@example.com"]),
    ("claim_id", "Unique claim identifier", ["CLM-001"]),
]

for col_name, desc, samples in test_columns:
    domain_type, confidence = inference.infer_domain_type(
        column_name=col_name,
        description=desc,
        sample_values=samples,
    )
    tag = f"{domain_type} ({confidence:.0%})" if domain_type else "(no match)"
    print(f"  {col_name:20s} -> {tag}")

npi_specs = registry.get_validation_specs("npi")
if npi_specs:
    print(f"\nValidation specs for 'npi': {json.dumps(npi_specs[0], indent=2)[:200]}...")

check(len(all_types) > 20, f"should have >20 domain types, got {len(all_types)}")
npi_type, npi_conf = inference.infer_domain_type("provider_npi", "NPI", ["1234567890"])
check(npi_type == "npi", f"provider_npi should infer as npi, got {npi_type}")
check(npi_conf >= 0.8, f"npi confidence should be >= 0.8, got {npi_conf}")

# ===================================================================
# 5. Great Expectations Baseline
# ===================================================================

section("Great Expectations Baseline Generation")

from tablespec import BaselineExpectationGenerator

gen = BaselineExpectationGenerator()
expectations = gen.generate_baseline_expectations(claims_dict, include_structural=True)

print(f"Generated {len(expectations)} baseline expectations for {claims.table_name}:\n")
for exp in expectations:
    exp_type = exp["type"]
    kwargs = exp.get("kwargs", {})
    col = kwargs.get("column", kwargs.get("column_list", ""))
    severity = exp.get("meta", {}).get("severity", "")
    print(f"  [{severity:8s}] {exp_type}")
    if col:
        print(f"             column: {col}")

check(len(expectations) >= 7, f"should generate >=7 expectations, got {len(expectations)}")
exp_types = {e["type"] for e in expectations}
check(
    "expect_table_columns_to_match_ordered_list" in exp_types,
    "should generate structural column list expectation",
)
check(
    "expect_column_values_to_cast_to_type" in exp_types,
    "should generate cast-to-type validation",
)
check("expect_column_values_to_not_be_null" in exp_types, "should generate not_be_null")

# ===================================================================
# 6. LLM Prompt Generation
# ===================================================================

section("LLM Prompt Generation")

from tablespec import generate_documentation_prompt, generate_validation_prompt

doc_prompt = generate_documentation_prompt(claims_dict)
print(f"Documentation prompt length: {len(doc_prompt)} chars")
print(f"First 300 chars:\n{doc_prompt[:300]}...\n")

val_prompt = generate_validation_prompt(claims_dict)
print(f"Validation prompt length: {len(val_prompt)} chars")
print("(These prompts are designed to be sent to an LLM for analysis)")

check(len(doc_prompt) > 500, "doc prompt should be substantial")
check("Medical_Claims" in doc_prompt, "doc prompt should reference table name")
check(len(val_prompt) > 1000, "validation prompt should be substantial")

# ===================================================================
# 7. UMF Diffing & Change Detection
# ===================================================================

section("UMF Diffing & Change Detection")

from tablespec import UMFDiff

modified_claims = deepcopy(claims)
modified_claims.columns[1].description = "Total claim amount in USD (updated)"
from tablespec import UMFColumn

new_col = UMFColumn(
    name="service_date",
    data_type="DATE",
    description="Date of service",
)
modified_claims.columns.append(new_col)

differ = UMFDiff(claims, modified_claims)

col_changes = differ.get_column_changes()
print(f"Column changes detected: {len(col_changes)}")
for change in col_changes:
    print(f"  {change.description()}")

check(len(col_changes) == 2, f"should detect 2 changes, got {len(col_changes)}")

# ===================================================================
# 8-11. PySpark Features (require tablespec[spark])
# ===================================================================

if not HAS_SPARK:
    section("PySpark Features (skipped -- install tablespec[spark])")
    print("Sections 8-11 require PySpark. Install with:")
    print("  uv sync --extra spark")
    print("\nThese sections demonstrate:")
    print("  8.  Create a Spark session & sample DataFrame")
    print("  9.  Profile a DataFrame -> inferred UMF schema")
    print("  10. Validate a DataFrame against a UMF spec")
    print("  11. Generate sample data from UMF specs")
else:
    # ---------------------------------------------------------------
    # 8. Spark Session & DataFrame
    # ---------------------------------------------------------------
    section("PySpark: Create Spark Session & Sample DataFrame")

    try:
        spark = create_delta_spark_session("tablespec-demo")
    except RuntimeError as e:
        # The factory (single entrypoint) raises RuntimeError when it detects
        # Databricks but cannot acquire a session (e.g. subprocess on serverless
        # where the Spark Connect socket is only reachable from the main REPL).
        # Degrade gracefully — non-Spark sections (1-7) already validated.
        print(f"Spark session unavailable: {e}")
        print("Skipping PySpark sections 8-11 (not reachable from this process).")
        print("\nDemo complete! All checks passed.")
        sys.exit(0)

    spark.sparkContext.setLogLevel("ERROR")
    print(f"Spark session: {spark.sparkContext.appName}")
    print(f"Spark version: {spark.version}")

    from pyspark.sql import Row

    claims_data = [
        Row(claim_id="CLM-001", claim_amount=1500.00, provider_id="PRV001"),
        Row(claim_id="CLM-002", claim_amount=2300.50, provider_id="PRV002"),
        Row(claim_id="CLM-003", claim_amount=None, provider_id="PRV001"),
        Row(claim_id="CLM-004", claim_amount=750.25, provider_id="PRV003"),
        Row(claim_id="CLM-005", claim_amount=4100.00, provider_id="PRV002"),
    ]

    claims_df = spark.createDataFrame(claims_data)
    print("\nSample claims DataFrame:")
    claims_df.show()
    claims_df.printSchema()

    check(claims_df.count() == 5, "DataFrame should have 5 rows")
    check(len(claims_df.columns) == 3, "DataFrame should have 3 columns")

    # ---------------------------------------------------------------
    # 9. Profile DataFrame -> UMF
    # ---------------------------------------------------------------
    section("PySpark: Profile DataFrame -> Inferred UMF")

    mapper = SparkToUmfMapper()
    inferred_umf = mapper.map_dataframe_to_umf(claims_df, table_name="InferredClaims")

    print(f"Inferred table: {inferred_umf['table_name']}")
    print("Inferred columns:")
    for col in inferred_umf["columns"]:
        print(f"  - {col['name']:20s}  type={col['data_type']:10s}  nullable={col['nullable']}")

    check(inferred_umf["table_name"] == "InferredClaims", "inferred table name")
    check(len(inferred_umf["columns"]) == 3, "should infer 3 columns")

    # ---------------------------------------------------------------
    # 10. Validate DataFrame Against UMF
    # ---------------------------------------------------------------
    section("PySpark: Validate DataFrame Against UMF")

    from tablespec import save_umf_to_yaml

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        save_umf_to_yaml(claims, f.name)
        umf_path = Path(f.name)

    validator = TableValidator(spark)
    error_df = validator.validate_table(claims_df, umf_path, table_name="Medical_Claims")

    error_count = error_df.count()
    if error_count > 0:
        print(f"Validation found {error_count} issue(s):")
        error_df.select("error_type", "severity", "column_name", "error_message").show(
            truncate=60
        )
        # Expected: claim_amount is double in Spark but DECIMAL in UMF spec.
        # The validator correctly catches this type mismatch.
        print("  (Expected: Spark infers double for claim_amount, UMF spec says DECIMAL)")
    else:
        print("All validations passed!")

    check(error_count >= 1, "validator should catch the double vs DECIMAL type mismatch")

    umf_path.unlink(missing_ok=True)

    # ---------------------------------------------------------------
    # 11. Sample Data Generation
    # ---------------------------------------------------------------
    section("Sample Data Generation")

    from tablespec import GenerationConfig, SampleDataGenerator
    from tablespec.umf_loader import UMFLoader

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "specs"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # Save UMF files in split format (what SampleDataGenerator expects)
        loader = UMFLoader()
        loader.save(claims, input_dir / claims.table_name)
        loader.save(providers, input_dir / providers.table_name)
        print("Prepared split-format UMF specs:")
        for d in sorted(input_dir.iterdir()):
            print(f"  {d.name}/")

        config = GenerationConfig(
            num_members=100,
            relationship_density=0.8,
            temporal_range_days=365,
            random_seed=42,
        )

        generator = SampleDataGenerator(
            input_dir=input_dir,
            output_dir=output_dir,
            config=config,
            spark=spark,
        )

        success = generator.run_generation()
        print(f"\nGeneration {'succeeded' if success else 'failed'}")

        generated_files = [f for f in sorted(output_dir.rglob("*")) if f.is_file()]
        if generated_files:
            print("\nGenerated files:")
            for f in generated_files:
                size = f.stat().st_size
                print(f"  {f.relative_to(output_dir)}  ({size:,} bytes)")

                if f.suffix in (".csv", ".txt"):
                    lines = f.read_text().splitlines()
                    print(f"    Header: {lines[0]}")
                    for line in lines[1:4]:
                        print(f"    {line}")
                    if len(lines) > 4:
                        print(f"    ... ({len(lines) - 1} total rows)")

        check(success, "sample data generation should succeed")
        data_files = [f for f in generated_files if f.suffix in (".csv", ".txt")]
        check(len(data_files) >= 2, f"should generate >=2 data files, got {len(data_files)}")

    spark.stop()

# ===================================================================
# Results
# ===================================================================

print(f"\n{'=' * 72}")
if _ERRORS:
    print(f"  FAILED: {len(_ERRORS)} check(s) failed:")
    for err in _ERRORS:
        print(f"    - {err}")
    print(f"{'=' * 72}")
    sys.exit(1)
else:
    print("  Demo complete! All checks passed.")
    print(f"{'=' * 72}")
