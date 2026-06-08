# tablespec

Python library for working with table schemas in Universal Metadata Format (UMF). Provides type-safe models, validation, profiling integration, and schema generation tools.

## Features

- **Type-Safe UMF Models**: Pydantic-based models with runtime validation
- **Schema Generation**: Generate SQL DDL, PySpark schemas, and JSON schemas from UMF
- **Great Expectations Integration**: Baseline expectation generation and constraint extraction
- **Profiling**: Native Spark profiles feed GX validation; schema reflection
  handles UMF creation for bootstrap
- **Validation**: Table validation against UMF specifications with Great Expectations
- **Type Mappings**: Convert between UMF, PySpark, JSON, and Great Expectations types
- **LLM Prompt Generation**: Generate structured prompts for documentation, validation rules, relationships, and survivorship logic
- **CLI**: Typer-based command-line interface with Rich output for schema management and conversion
- **Excel Conversion**: Bidirectional Excel export/import for domain expert collaboration
- **Split-Format UMF**: Git-friendly directory-based storage with automatic format detection
- **Sample Data Generation**: Healthcare-specific, constraint-aware sample data from UMF specs
- **Domain Type Inference**: Automatic detection of domain types (SSN, NPI, phone, state codes, etc.)
- **Change Management**: UMF diffing, atomic change application, and git-based changelogs

## Demo

[![asciicast](https://github.com/easel/tablespec/raw/main/examples/tablespec-demo.gif)](https://github.com/easel/tablespec/blob/main/examples/tablespec-demo.cast)

The demo walks through loading a UMF schema, generating SQL/PySpark/JSON schemas, type mappings, domain type inference, Great Expectations baseline generation, LLM prompt generation, UMF diffing, and PySpark validation with sample data generation.

[**Watch with narration (MP4)**](https://github.com/easel/tablespec/raw/main/examples/tablespec-demo-narrated.mp4)

Play the asciinema recording in your terminal:

```bash
# Install asciinema, then play the recording
asciinema play examples/tablespec-demo.cast

# Or run the demo live (requires tablespec[spark])
uv run python examples/demo.py
```

## Installation

### Using uv (recommended)

```bash
# Add to your uv project
uv add tablespec --index-url https://easel.github.io/tablespec/simple/

# With Spark support (for profiling and validation)
uv add tablespec[spark] --index-url https://easel.github.io/tablespec/simple/
```

### Using pip

```bash
# Install from GitHub Pages index
pip install tablespec --index-url https://easel.github.io/tablespec/simple/

# With Spark support
pip install tablespec[spark] --index-url https://easel.github.io/tablespec/simple/
```

**Note**: This package is distributed via GitHub Pages. The `--index-url` flag is required.

**Optional extras**:
- `tablespec[spark]` - Adds PySpark support for `SparkToUmfMapper`, `TableValidator`, `SampleDataGenerator` (with Spark FK seeding), `BaselineService`, and table merge. Install this extra only if you need Spark-dependent features.

## Quick Start

### Loading and Saving UMF Files

```python
from tablespec import load_umf_from_yaml, save_umf_to_yaml, UMF

# Load UMF from YAML (see examples/ for sample files)
umf = load_umf_from_yaml("examples/schema.yaml")

# Access metadata
print(f"Table: {umf.table_name}")
print(f"Columns: {len(umf.columns)}")

# Modify and save
umf.description = "Updated description"
save_umf_to_yaml(umf, "updated_schema.yaml")
```

### Creating UMF Programmatically

```python
from tablespec import UMF, UMFColumn, Nullable

umf = UMF(
    version="1.0",
    table_name="Medical_Claims",
    description="Healthcare claims data",
    columns=[
        UMFColumn(
            name="claim_id",
            data_type="VARCHAR",
            length=50,
            description="Unique claim identifier",
            nullable=Nullable(MD=False, MP=False, ME=False)
        ),
        UMFColumn(
            name="claim_amount",
            data_type="DECIMAL",
            precision=10,
            scale=2,
            description="Claim amount in USD",
            nullable=Nullable(MD=True, MP=True, ME=True)
        )
    ]
)

save_umf_to_yaml(umf, "medical_claims.yaml")
```

### Generating Schemas

```python
from tablespec import generate_sql_ddl, generate_pyspark_schema, generate_json_schema

# Load UMF
umf = load_umf_from_yaml("examples/schema.yaml")
umf_dict = umf.model_dump()

# Generate SQL DDL
ddl = generate_sql_ddl(umf_dict)
print(ddl)

# Generate PySpark schema code
spark_schema = generate_pyspark_schema(umf_dict)
print(spark_schema)

# Generate JSON Schema
json_schema = generate_json_schema(umf_dict)
print(json_schema)
```

### Bootstrapping from Existing Spark Tables

```python
from tablespec import bootstrap_from_tables

artifacts = bootstrap_from_tables(
    spark,
    ["member"],
    "/tmp/tablespec-bootstrap",
    profile=True,
)

print(artifacts.manifest_path)
print(artifacts.table("member").suite_json)
```

`bootstrap_from_tables` reflects each Spark table into UMF, optionally profiles
the data to enrich the compiled validation suite, and persists the full
artifact tree in one call. The profiler enriches validation; it does not create
UMF.

This is the development bootstrap path. Production installs the published
`tablespec` wheel and consumes the committed artifact tree through the manifest;
it does not re-run the bootstrap orchestration from source-time Python.

## Documentation

Full documentation is available at [easel.github.io/tablespec](https://easel.github.io/tablespec/):

- **[User Guide](https://easel.github.io/tablespec/guide/umf-format/)** -- UMF format, schema generation, GX integration, CLI, Excel, and more
- **[API Reference](https://easel.github.io/tablespec/api/models/)** -- Complete API documentation
- **[Development](https://easel.github.io/tablespec/development/)** -- Setup, testing, and project structure

## License

Apache License 2.0 - see LICENSE file for details.
