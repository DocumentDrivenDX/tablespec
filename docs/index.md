# tablespec

Python library for working with table schemas in Universal Metadata Format (UMF). Provides type-safe models, validation, profiling integration, and schema generation tools.

## Features

- **Type-Safe UMF Models** -- Pydantic-based models with runtime validation
- **Schema Generation** -- Generate SQL DDL, PySpark schemas, and JSON schemas from UMF
- **Great Expectations Integration** -- Baseline expectation generation and constraint extraction
- **Profiling** -- Native Spark profiles feed GX validation; schema reflection
  handles UMF creation for bootstrap
- **Validation** -- Table validation against UMF specifications with Great Expectations
- **Type Mappings** -- Convert between UMF, PySpark, JSON, and Great Expectations types
- **LLM Prompt Generation** -- Generate structured prompts for documentation, validation rules, relationships, and survivorship logic
- **CLI** -- Typer-based command-line interface with Rich output for schema management and conversion
- **Excel Conversion** -- Bidirectional Excel export/import for domain expert collaboration
- **Split-Format UMF** -- Git-friendly directory-based storage with automatic format detection
- **Sample Data Generation** -- Healthcare-specific, constraint-aware sample data from UMF specs
- **Domain Type Inference** -- Automatic detection of domain types (SSN, NPI, phone, state codes, etc.)
- **Change Management** -- UMF diffing, atomic change application, and git-based changelogs

## Installation

```bash
# Using uv (recommended)
uv add tablespec --index-url https://easel.github.io/tablespec/simple/

# With Spark support
uv add tablespec[spark] --index-url https://easel.github.io/tablespec/simple/

# Using pip
pip install tablespec --index-url https://easel.github.io/tablespec/simple/
```

**Note**: This package is distributed via GitHub Pages. The `--index-url` flag is required.

## Quick Start

```python
from tablespec import load_umf_from_yaml, save_umf_to_yaml, UMF

# Load UMF from YAML
umf = load_umf_from_yaml("examples/schema.yaml")

# Access metadata
print(f"Table: {umf.table_name}")
print(f"Columns: {len(umf.columns)}")

# Generate SQL DDL
from tablespec import generate_sql_ddl
ddl = generate_sql_ddl(umf.model_dump())
print(ddl)
```

## User Guide

Learn how to use each feature of tablespec:

- **[UMF Format](guide/umf-format.md)** -- YAML schema structure and supported data types
- **[Schema Generation](guide/schema-generation.md)** -- UMF models, schema generators, and type mappings
- **[Great Expectations](guide/great-expectations.md)** -- Baseline generation, constraint extraction, and GX mapping
- **[Profiling](guide/profiling.md)** -- Native Spark profiling that feeds GX validation
- **[Bootstrap](guide/bootstrap.md)** -- One-shot Spark-table bootstrap into compiled artifacts
- **[LLM Prompts](guide/llm-prompts.md)** -- Generate prompts for documentation, validation, and relationships
- **[CLI](guide/cli.md)** -- Command-line schema management and conversion
- **[Excel Conversion](guide/excel.md)** -- Round-trip Excel export/import for domain experts
- **[Split-Format UMF](guide/split-format.md)** -- Directory-based storage with format auto-detection
- **[Sample Data](guide/sample-data.md)** -- Healthcare-specific, constraint-aware data generation
- **[Domain Inference](guide/domain-inference.md)** -- Automatic domain type detection
- **[Change Management](guide/change-management.md)** -- UMF diffing and git-based changelogs

## API Reference

- **[Models](api/models.md)** -- UMF, UMFColumn, ValidationRules, and other Pydantic models
- **[Schema Generators](api/generators.md)** -- SQL DDL, PySpark, and JSON Schema generation
- **[Type Mappings](api/type_mappings.md)** -- Type system conversions
- **[Great Expectations](api/gx.md)** -- GX integration classes
- **[CLI](api/cli.md)** -- Command-line interface reference
