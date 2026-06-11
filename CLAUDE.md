# tablespec - Development Guide

Python library for working with table schemas in Universal Metadata Format (UMF). Provides type-safe models, validation, profiling integration, and schema generation tools.

## Project Architecture

### Core Modules

- **`models/`** - Pydantic models for UMF format (UMF, UMFColumn, ValidationRules, etc.)
- **`schemas/`** - Schema generators (SQL DDL, PySpark, JSON Schema)
- **`type_mappings.py`** - Type conversions between UMF, PySpark, JSON, and Great Expectations
- **`gx_baseline.py`** - Generate baseline Great Expectations from UMF metadata
- **`gx_constraint_extractor.py`** - Extract constraints from existing GX suites into UMF
- **`gx_schema_validator.py`** - Validate schemas using Great Expectations
- **`profiling/`** - Convert profiling results (Spark DataFrame, Deequ) to UMF format
- **`validation/`** - Table validation engine with Great Expectations (requires PySpark)
- **`prompts/`** - LLM prompt generators for documentation, validation rules, relationships

### Optional Dependencies

- **`[spark]`** - PySpark support for SparkToUmfMapper and TableValidator
  - Install: `uv sync --extra spark`
  - Required for: Spark profiling and validation features

## Development Workflow

Run `make help` to see all available commands. Key targets:

```bash
make install-dev  # Install with dev dependencies
make check        # Run lint, type-check, and tests
make format       # Format code with ruff
make test         # Run all tests
make coverage     # Run tests with coverage report
```

## Testing Strategy

- **Unit tests**: `tests/unit/` - Pure Python logic, UMF models, type mappings
- **Integration tests**: `tests/integration/` - Tests requiring external dependencies
- Run specific tests: `uv run pytest tests/unit/test_gx_baseline.py`
- Coverage target: Use `make coverage` for HTML reports in `htmlcov/`

## Key Conventions

### Code Style

- **Formatter**: Ruff (opinionated, no config needed)
- **Linter**: Ruff with autofix via `make lint-fix`
- **Type checking**: pyright for `src/` directory
- **Python version**: 3.12+ (specified in pyproject.toml)

### UMF Format

- YAML-based schema format with Pydantic validation
- Column types: VARCHAR, CHAR, TEXT, INTEGER, DECIMAL, FLOAT, DATE, DATETIME, BOOLEAN
- Nullable configuration per LOB (MD/MP/ME for Medicaid/Medicare)
- See README.md for full UMF structure and examples

### Type Mappings

All type conversions go through `type_mappings.py`:
- UMF → PySpark: `map_to_pyspark_type()`
- UMF → JSON Schema: `map_to_json_type()`
- UMF → GX Spark: `map_to_gx_spark_type()`

### Module Import Pattern

Public API defined in `src/tablespec/__init__.py`. Conditional imports for Spark-dependent features:

```python
# Always available
from tablespec import UMF, load_umf_from_yaml, generate_sql_ddl

# Available only with tablespec[spark]
from tablespec import SparkToUmfMapper, TableValidator
```

## Project Structure

```
src/tablespec/
├── __init__.py              # Public API exports
├── models/
│   └── umf.py              # Pydantic UMF models
├── schemas/
│   ├── generators.py       # SQL, PySpark, JSON schema generators
│   └── *.schema.json       # JSON schemas for validation
├── type_mappings.py        # Type system conversions
├── gx_*.py                 # Great Expectations integration (baseline, extract, validate)
├── profiling/
│   ├── types.py            # Profile result types
│   ├── spark_mapper.py     # Spark → UMF (requires PySpark)
│   └── native_profiler.py  # Connect-safe Spark-SQL profiler (ADR-009 removed the Deequ mapper)
├── prompts/                # LLM prompt generators
└── validation/             # Table validation (requires PySpark)

tests/
├── unit/                   # Pure Python tests
└── integration/            # Tests with external deps
```

## Common Tasks

### Adding a New UMF Field

1. Update `models/umf.py` with new Pydantic field
2. Update schema generators in `schemas/generators.py` if applicable
3. Add tests in `tests/unit/`
4. Update JSON schema in `schemas/umf.schema.json`

### Adding a New Schema Generator

1. Create function in `schemas/generators.py`
2. Export in `schemas/__init__.py` and top-level `__init__.py`
3. Add corresponding type mapping in `type_mappings.py` if needed
4. Add unit tests

### Working with Great Expectations

- **Baseline generation**: Use `BaselineExpectationGenerator` for deterministic expectations from UMF
- **Constraint extraction**: Use `GXConstraintExtractor` to reverse-engineer UMF from existing suites
- **Validation**: Use `TableValidator` (requires Spark) to validate DataFrames against UMF specs

## Notes for AI Assistants

- This is a **pure Python library** focused on schema metadata, not data processing
- Spark is an **optional dependency** - check if PySpark features are needed before suggesting
- UMF is the **single source of truth** - all conversions should be bidirectional when possible
- Great Expectations integration is **read/write** - both generate and extract constraints
- Keep the **Makefile self-documenting** - use `## comments` for help text
