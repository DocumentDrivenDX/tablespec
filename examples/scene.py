#!/usr/bin/env python3
"""Run a single demo scene for the screencast.

Usage: python examples/scene.py <scene-name>

Scenes:
  yaml      Show the raw UMF YAML
  load      Load & inspect UMF schemas
  generate  Schema generation (SQL DDL, PySpark, JSON Schema)
  types     Type mapping table
  domains   Domain type inference
  gx        Great Expectations baseline
  prompts   LLM prompt generation
  diff      UMF diffing & change detection
  context   Context-aware nullable expectations
  compat    Compatibility checking
  excel     Excel round-trip
  spark     PySpark sections 8-11 (session, profile, validate, sample data)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

# Suppress Spark/py4j noise
logging.getLogger("py4j").setLevel(logging.ERROR)
logging.getLogger("tablespec.sample_data").setLevel(logging.ERROR)
os.environ.setdefault("SPARK_LOG_LEVEL", "ERROR")

EXAMPLES_DIR = Path(__file__).resolve().parent
CLAIMS_YAML = EXAMPLES_DIR / "schema.yaml"
PROVIDERS_YAML = EXAMPLES_DIR / "providers.yaml"


def scene_yaml():
    print(CLAIMS_YAML.read_text(), end="")


def scene_load():
    from tablespec import load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    providers = load_umf_from_yaml(str(PROVIDERS_YAML))

    print(f"Table: {claims.table_name}")
    print(f"  {claims.description}")
    print(f"  {len(claims.columns)} columns:\n")
    for col in claims.columns:
        if col.nullable:
            nd = col.nullable.model_dump(exclude_none=True)
            req = [k for k, v in nd.items() if not v]
        else:
            req = []
        req_str = f"  required: {','.join(req)}" if req else "  (nullable)"
        print(f"    {col.name:20s} {col.data_type:10s}{req_str}")

    print(f"\nTable: {providers.table_name}")
    print(
        f"  {len(providers.columns)} columns: {', '.join(c.name for c in providers.columns)}"
    )


def scene_generate():
    from tablespec import (
        generate_json_schema,
        generate_pyspark_schema,
        generate_sql_ddl,
        load_umf_from_yaml,
    )

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    d = claims.model_dump(mode="json", exclude_none=True)

    print("--- SQL DDL ---")
    print(generate_sql_ddl(d))

    print("--- PySpark StructType ---")
    print(generate_pyspark_schema(d))

    print("--- JSON Schema ---")
    print(json.dumps(generate_json_schema(d), indent=2))


def scene_types():
    from tablespec import (
        load_umf_from_yaml,
        map_to_gx_spark_type,
        map_to_json_type,
        map_to_pyspark_type,
    )

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    providers = load_umf_from_yaml(str(PROVIDERS_YAML))

    print(f"{'Column':<22} {'UMF':<12} {'PySpark':<14} {'JSON':<10} {'GX Spark'}")
    print("-" * 72)
    for col in [*claims.columns, *providers.columns]:
        print(
            f"{col.name:<22} {col.data_type:<12} "
            f"{map_to_pyspark_type(col.data_type):<14} "
            f"{map_to_json_type(col.data_type):<10} "
            f"{map_to_gx_spark_type(col.data_type)}"
        )


def scene_domains():
    from tablespec import DomainTypeInference, DomainTypeRegistry

    registry = DomainTypeRegistry()
    inference = DomainTypeInference(registry)

    print(f"{len(registry.list_domain_types())} registered domain types\n")

    tests = [
        ("provider_npi", "National Provider Identifier", ["1234567890"]),
        ("state_code", "Provider state code", ["CA", "NY", "TX"]),
        ("member_email", "Member email address", ["jane@example.com"]),
        ("date_of_birth", "Member date of birth", ["1985-03-15"]),
        ("claim_id", "Unique claim identifier", ["CLM-001"]),
    ]

    print(f"{'Column':<22} {'Inferred Domain':<22} {'Confidence'}")
    print("-" * 56)
    for name, desc, samples in tests:
        dt, conf = inference.infer_domain_type(name, desc, samples)
        tag = dt or "(none)"
        print(f"{name:<22} {tag:<22} {conf:.0%}")

    print("\nExample: 'npi' domain type provides these validation rules:")
    for spec in registry.get_validation_specs("npi"):
        print(f"  {spec['type']}: {spec['kwargs']}")


def scene_gx():
    from tablespec import BaselineExpectationGenerator, load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    d = claims.model_dump(mode="json", exclude_none=True)

    gen = BaselineExpectationGenerator()
    expectations = gen.generate_baseline_expectations(d, include_structural=True)

    print(f"{len(expectations)} expectations generated from UMF metadata:\n")
    for exp in expectations:
        kwargs = exp.get("kwargs", {})
        col = kwargs.get("column", "")
        sev = exp.get("meta", {}).get("severity", "")
        col_str = f"  ({col})" if col else ""
        print(f"  [{sev:<8}] {exp['type']}{col_str}")


def scene_prompts():
    from tablespec import (
        generate_documentation_prompt,
        generate_validation_prompt,
        load_umf_from_yaml,
    )

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    d = claims.model_dump(mode="json", exclude_none=True)

    doc = generate_documentation_prompt(d)
    val = generate_validation_prompt(d)

    print(f"Documentation prompt: {len(doc):,} chars")
    print(f"Validation prompt:    {len(val):,} chars\n")
    print("Documentation prompt preview:")
    print("-" * 50)
    # Show just the structured part, not the boilerplate
    for line in doc.splitlines()[:15]:
        print(f"  {line}")
    print("  ...")


def scene_diff():
    from tablespec import UMFColumn, UMFDiff, load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    modified = deepcopy(claims)
    modified.columns[1].description = "Total claim amount in USD (updated)"
    modified.columns.append(
        UMFColumn(name="service_date", data_type="DATE", description="Date of service")
    )

    differ = UMFDiff(claims, modified)
    changes = differ.get_column_changes()

    print(f"{len(changes)} column change(s) detected:\n")
    for c in changes:
        print(f"  {c.description()}")


def scene_context():
    from tablespec import BaselineExpectationGenerator

    umf_with_context = {
        "table_name": "Enrollments",
        "context_column": "LOB",
        "columns": [
            {
                "name": "member_id",
                "data_type": "VARCHAR",
                "nullable": {"MD": False, "MP": True, "ME": False},
            },
            {"name": "LOB", "data_type": "VARCHAR"},
        ],
    }

    gen = BaselineExpectationGenerator()
    exps = gen.generate_baseline_expectations(
        umf_with_context, include_structural=False
    )
    row_cond = [e for e in exps if "row_condition" in e.get("kwargs", {})]

    print(f"{len(exps)} expectations generated ({len(row_cond)} context-aware):\n")
    for exp in row_cond:
        col = exp["kwargs"].get("column", "")
        cond = exp["kwargs"]["row_condition"]
        print(f"  {exp['type']}")
        print(f"    column={col}  row_condition={cond}")

    print("\nDifferent LOBs get different nullable rules — from one YAML.")


def scene_compat():
    from tablespec import UMFColumn, check_compatibility, load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    modified = deepcopy(claims)
    modified.columns[1].data_type = "INTEGER"  # Narrowing DECIMAL -> INTEGER
    modified.columns.append(
        UMFColumn(name="diagnosis_code", data_type="VARCHAR", description="ICD-10 code")
    )

    report = check_compatibility(claims, modified)

    print(f"Backward compatible: {report.is_backward_compatible}")
    print(f"Forward compatible:  {report.is_forward_compatible}")
    print(f"Issues found: {len(report.issues)}\n")
    for issue in report.issues:
        print(f"  [{issue.severity:8s}] {issue.component}: {issue.description}")


def scene_excel():
    from tablespec import UMFToExcelConverter, load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        excel_path = Path(f.name)

    try:
        exporter = UMFToExcelConverter()
        workbook = exporter.convert(claims)
        workbook.save(str(excel_path))
        size = excel_path.stat().st_size

        print(f"Exported to Excel: {excel_path.name} ({size:,} bytes)")
        print(f"Sheets: {workbook.sheetnames}")

        cols_sheet = workbook["Columns"]
        headers = [cell.value for cell in cols_sheet[1] if cell.value]
        nullable_headers = [h for h in headers if h.startswith("Nullable")]
        print(f"Nullable columns in Excel: {nullable_headers}")

        # Show a few rows from the Columns sheet
        print("\nColumns sheet preview:")
        for row in cols_sheet.iter_rows(min_row=1, max_row=4, values_only=True):
            vals = [str(v) if v is not None else "" for v in row[:5]]
            print(f"  {' | '.join(vals)}")
    finally:
        excel_path.unlink(missing_ok=True)


def scene_spark():
    import time

    print("Starting Spark ", end="", flush=True)
    t0 = time.time()

    from tablespec import (
        GenerationConfig,
        SampleDataGenerator,
        SparkToUmfMapper,
        TableValidator,
        create_delta_spark_session,
        load_umf_from_yaml,
        save_umf_to_yaml,
    )
    from tablespec.umf_loader import UMFLoader

    spark = create_delta_spark_session("tablespec-demo")
    spark.sparkContext.setLogLevel("ERROR")
    elapsed = time.time() - t0
    print(f"... ready ({elapsed:.1f}s, Spark {spark.version})")

    # --- Section 8: Create DataFrame ---
    print(f"\n{'=' * 60}")
    print("  8. Create Sample DataFrame")
    print(f"{'=' * 60}\n")

    from pyspark.sql import Row

    claims_df = spark.createDataFrame(
        [
            Row(claim_id="CLM-001", claim_amount=1500.00, provider_id="PRV001"),
            Row(claim_id="CLM-002", claim_amount=2300.50, provider_id="PRV002"),
            Row(claim_id="CLM-003", claim_amount=None, provider_id="PRV001"),
            Row(claim_id="CLM-004", claim_amount=750.25, provider_id="PRV003"),
            Row(claim_id="CLM-005", claim_amount=4100.00, provider_id="PRV002"),
        ]
    )
    claims_df.show()
    print("###MARK:spark_profile###", flush=True)

    # --- Section 9: Profile ---
    print(f"{'=' * 60}")
    print("  9. Profile DataFrame -> Inferred UMF")
    print(f"{'=' * 60}\n")

    mapper = SparkToUmfMapper()
    inferred = mapper.map_dataframe_to_umf(claims_df, table_name="InferredClaims")
    for col in inferred["columns"]:
        print(
            f"  {col['name']:20s} -> {col['data_type']:10s} nullable={col['nullable']}"
        )
    print("###MARK:spark_validate###", flush=True)

    # --- Section 10: Validate ---
    print(f"\n{'=' * 60}")
    print("  10. Validate DataFrame Against UMF Spec")
    print(f"{'=' * 60}\n")

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        save_umf_to_yaml(claims, f.name)
        umf_path = Path(f.name)

    validator = TableValidator(spark)
    error_df = validator.validate_table(
        claims_df, umf_path, table_name="Medical_Claims"
    )
    error_count = error_df.count()
    if error_count > 0:
        print(f"Validator caught {error_count} issue(s):")
        error_df.select("error_type", "column_name", "error_message").show(truncate=60)
        print("(Expected: Spark infers double, UMF spec says DECIMAL)")
    umf_path.unlink(missing_ok=True)
    print("###MARK:spark_sample###", flush=True)

    # --- Section 11: Sample Data ---
    print(f"{'=' * 60}")
    print("  11. Generate Sample Data from UMF Specs")
    print(f"{'=' * 60}\n")

    providers = load_umf_from_yaml(str(PROVIDERS_YAML))
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "specs"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        loader = UMFLoader()
        loader.save(claims, input_dir / claims.table_name)
        loader.save(providers, input_dir / providers.table_name)

        generator = SampleDataGenerator(
            input_dir=input_dir,
            output_dir=output_dir,
            config=GenerationConfig(num_members=100, random_seed=42),
            spark=spark,
        )
        generator.run_generation()

        for f in sorted(output_dir.rglob("*")):
            if f.is_file() and f.suffix in (".csv", ".txt"):
                lines = f.read_text().splitlines()
                print(f"{f.name}: {len(lines) - 1} rows")
                print(f"  Header: {lines[0]}")
                for line in lines[1:4]:
                    print(f"  {line}")
                print()

    spark.stop()


def scene_sql_plan():
    from tablespec import (
        UMF,
        UMFColumn,
        UMFColumnDerivation,
        DerivationCandidate,
        Nullable,
        Relationships,
        OutgoingRelationship,
        generate_sql_plan,
    )

    # Build a derived table that joins claims + providers
    target = UMF(
        version="1.0",
        table_name="Claims_Summary",
        description="Enriched claims with provider info",
        table_type="generated",
        columns=[
            UMFColumn(
                name="claim_id",
                data_type="VARCHAR",
                length=50,
                description="Unique claim identifier",
                nullable=Nullable(MD=False, MP=False, ME=False),
                derivation=UMFColumnDerivation(
                    strategy="primary_key",
                    candidates=[
                        DerivationCandidate(
                            table="Medical_Claims",
                            column="claim_id",
                            priority=1,
                        )
                    ],
                ),
            ),
            UMFColumn(
                name="claim_amount",
                data_type="DECIMAL",
                precision=10,
                scale=2,
                description="Claim amount",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="Medical_Claims",
                            column="claim_amount",
                            priority=1,
                        )
                    ],
                ),
            ),
            UMFColumn(
                name="provider_name",
                data_type="VARCHAR",
                length=200,
                description="Provider full name",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="Providers",
                            column="provider_name",
                            priority=1,
                        )
                    ],
                ),
            ),
            UMFColumn(
                name="state_code",
                data_type="VARCHAR",
                length=2,
                description="Provider state",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="Providers",
                            column="state_code",
                            priority=1,
                        )
                    ],
                ),
            ),
        ],
        relationships=Relationships(
            outgoing=[
                OutgoingRelationship(
                    target_table="Medical_Claims",
                    source_column="claim_id",
                    target_column="claim_id",
                    type="foreign_to_primary",
                    confidence=1.0,
                ),
                OutgoingRelationship(
                    target_table="Providers",
                    source_column="provider_id",
                    target_column="provider_id",
                    type="foreign_to_primary",
                    confidence=1.0,
                ),
            ]
        ),
    )

    from tablespec import load_umf_from_yaml

    claims = load_umf_from_yaml(str(CLAIMS_YAML))
    providers = load_umf_from_yaml(str(PROVIDERS_YAML))

    related = {
        "Medical_Claims": claims,
        "Providers": providers,
    }

    sql = generate_sql_plan(target, related)
    # Show first 40 lines
    lines = sql.splitlines()
    for line in lines[:40]:
        print(line)
    if len(lines) > 40:
        print(f"... ({len(lines)} total lines)")


def scene_cli():
    """Demonstrate the CLI mutation commands."""
    import subprocess

    from tablespec import load_umf_from_yaml

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=tempfile.gettempdir()
    ) as f:
        umf = load_umf_from_yaml(str(CLAIMS_YAML))
        d = umf.model_dump(mode="json", exclude_none=True)
        f.write(json.dumps(d, indent=2))
        umf_path = f.name

    def run_cmd(args: list[str]) -> None:
        cmd = ["uv", "run", "tablespec", *args]
        print(f"$ tablespec {' '.join(args)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip() and result.returncode != 0:
            print(result.stderr.strip())
        print()

    print("--- Column Mutations ---\n")
    run_cmd(
        [
            "column-add",
            umf_path,
            "--name",
            "service_date",
            "--type",
            "DATE",
            "--description",
            "Date of service",
        ]
    )
    run_cmd(["column-modify", umf_path, "--name", "service_date", "--type", "DATETIME"])
    run_cmd(
        [
            "column-rename",
            umf_path,
            "--from",
            "service_date",
            "--to",
            "svc_dt",
            "--keep-alias",
        ]
    )

    print("--- Domain Assignment ---\n")
    run_cmd(["domains-set", umf_path, "--column", "provider_id", "--type", "npi"])

    print("--- Validation Management ---\n")
    run_cmd(
        [
            "validation-remove",
            umf_path,
            "--type",
            "expect_column_values_to_not_be_null",
            "--column",
            "claim_id",
        ]
    )

    # Show final state
    d = json.loads(Path(umf_path).read_text())
    print("Final columns:")
    for col in d["columns"]:
        dt = col.get("domain_type", "")
        alias = col.get("aliases", [])
        extras = []
        if dt:
            extras.append(f"domain={dt}")
        if alias:
            extras.append(f"aliases={alias}")
        extra_str = f"  ({', '.join(extras)})" if extras else ""
        print(f"  {col['name']:20s} {col['data_type']:10s}{extra_str}")

    Path(umf_path).unlink(missing_ok=True)


# ─── Dispatch ─────────────────────────────────────────────────────

SCENES = {
    "yaml": scene_yaml,
    "load": scene_load,
    "generate": scene_generate,
    "types": scene_types,
    "domains": scene_domains,
    "gx": scene_gx,
    "prompts": scene_prompts,
    "diff": scene_diff,
    "context": scene_context,
    "compat": scene_compat,
    "excel": scene_excel,
    "sql_plan": scene_sql_plan,
    "spark": scene_spark,
    "cli": scene_cli,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SCENES:
        print(f"Usage: python {sys.argv[0]} <{'|'.join(SCENES)}>")
        sys.exit(1)
    SCENES[sys.argv[1]]()
