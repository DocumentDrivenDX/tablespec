# Contributing to tablespec

Thank you for your interest in contributing to tablespec! This guide will help you get started with developing and contributing to the project.

## Table of Contents

- [Welcome](#welcome)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)
- [Project-Specific Guidelines](#project-specific-guidelines)
- [Getting Help](#getting-help)

## Welcome

tablespec is a Python library for working with table schemas in Universal Metadata Format (UMF). We welcome contributions of all kinds:

- Bug fixes and feature enhancements
- Documentation improvements
- Test coverage additions
- Schema generators for new formats
- Type system mappings
- Great Expectations integrations
- Profiling adapters

### Project Philosophy

- **UMF as single source of truth** - All schema conversions should be bidirectional when possible
- **Pure Python library** - Focus on metadata, not data processing
- **Optional dependencies** - PySpark is optional; core features work without it
- **Type safety** - Leverage Pydantic models and pyright for runtime and static validation
- **Great Expectations** - Support both generating and extracting constraints

## Getting Started

### Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager (recommended) or pip
- Git
- Familiarity with Pydantic, YAML, and data schemas

### Setting Up Your Development Environment

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/your-username/tablespec.git
   cd tablespec
   ```

2. **Install with development dependencies**

   ```bash
   # With uv (recommended)
   uv sync --all-extras --group dev

   # Or with pip
   pip install -e ".[spark]"
   pip install pytest pytest-mock anyio
   ```

3. **Verify installation**

   ```bash
   make check  # Runs lint, type-check, and tests
   ```

4. **Explore available commands**

   ```bash
   make help  # Display all available Makefile targets
   ```

### Repository Structure

```
src/tablespec/
├── __init__.py              # Public API exports
├── models/
│   └── umf.py              # Pydantic UMF models
├── schemas/
│   ├── generators.py       # SQL, PySpark, JSON schema generators
│   └── *.schema.json       # JSON schemas
├── type_mappings.py        # Type system conversions
├── gx_baseline.py          # Generate baseline Great Expectations
├── gx_constraint_extractor.py  # Extract constraints from GX suites
├── gx_schema_validator.py  # Schema validation with GX
├── profiling/
│   ├── types.py            # Profile result types
│   ├── spark_mapper.py     # Spark → UMF (requires PySpark)
│   └── deequ_mapper.py     # Deequ → UMF
├── prompts/                # LLM prompt generators
└── validation/             # Table validation (requires PySpark)

tests/
├── unit/                   # Pure Python tests
└── integration/            # Tests requiring external dependencies
```

## Development Workflow

### Branching Strategy

- **main** - Stable branch, always deployable
- **feature/** - New features (e.g., `feature/json-schema-generator`)
- **fix/** - Bug fixes (e.g., `fix/nullable-validation`)
- **docs/** - Documentation updates (e.g., `docs/contributing-guide`)

### Commit Conventions

Use clear, descriptive commit messages:

```
Add: New JSON Schema generator for UMF
Fix: Nullable validation for Medicaid LOB
Update: Enhance type mapping for DECIMAL precision
Docs: Add examples for Spark profiling
Test: Add coverage for GX constraint extraction
```

### Development Cycle

1. Create a feature branch from `main`
2. Make your changes following code standards
3. Add/update tests for your changes
4. Run quality checks: `make check`
5. Commit with descriptive messages
6. Push and open a pull request

## Code Standards

### Formatting

We use **Ruff** for code formatting (opinionated, zero-config):

```bash
make format  # Auto-format all code
```

### Linting

Ruff also handles linting with autofix:

```bash
make lint      # Check for issues
make lint-fix  # Auto-fix issues
```

### Type Checking

We use **pyright** for static type analysis:

```bash
make type-check  # Type check src/ directory
```

**Important**: All public functions and methods should have type hints.

### Code Style Guidelines

- **Line length**: 88 characters (Ruff default)
- **Imports**: Sorted automatically by Ruff
- **Docstrings**: Use Google-style docstrings for public APIs
- **Type hints**: Required for function signatures
- **Naming**:
  - `snake_case` for functions and variables
  - `PascalCase` for classes
  - `UPPER_CASE` for constants

### Example

```python
from typing import Dict, List, Optional

from tablespec.models import UMF, UMFColumn


def generate_sql_ddl(umf_dict: Dict, dialect: str = "spark") -> str:
    """Generate SQL DDL from UMF dictionary.

    Args:
        umf_dict: Dictionary representation of UMF model
        dialect: SQL dialect ('spark', 'postgres', 'mysql')

    Returns:
        SQL DDL CREATE TABLE statement

    Raises:
        ValueError: If umf_dict is missing required fields
    """
    # Implementation
    pass
```

## Making Changes

### Adding a New UMF Field

1. Update `models/umf.py` with new Pydantic field
2. Update schema generators in `schemas/generators.py` if applicable
3. Update JSON schema in `schemas/umf.schema.json`
4. Add unit tests in `tests/unit/`
5. Update README.md with examples if user-facing

### Adding a New Schema Generator

1. Create function in `schemas/generators.py`
2. Add corresponding type mapping in `type_mappings.py` if needed
3. Export in `schemas/__init__.py` and top-level `__init__.py`
4. Add unit tests with sample UMF inputs and expected outputs
5. Document in README.md API Reference section

### Adding a New Type Mapping

1. Add mapping function to `type_mappings.py`
2. Follow existing patterns: `map_to_<target>_type(data_type, **kwargs)`
3. Handle all UMF data types: VARCHAR, CHAR, TEXT, INTEGER, DECIMAL, FLOAT, DATE, DATETIME, BOOLEAN
4. Add unit tests for each data type
5. Document in README.md Type Mappings section

### Working with Great Expectations

- **Baseline generation**: Use `BaselineExpectationGenerator` for deterministic expectations
- **Constraint extraction**: Use `GXConstraintExtractor` to reverse-engineer UMF
- **Validation**: Ensure Spark-dependent features use conditional imports

### Adding Spark-Dependent Features

Features requiring PySpark should:

1. Be in `profiling/spark_mapper.py` or `validation/` modules
2. Use conditional imports in `__init__.py`:

```python
try:
    from tablespec.profiling.spark_mapper import SparkToUmfMapper
    __all__.append("SparkToUmfMapper")
except ImportError:
    pass  # PySpark not installed
```

3. Include clear error messages if Spark is not available
4. Be documented as requiring `umf-tablespec[spark]` installation

## Testing

### Testing Strategy

- **Unit tests** (`tests/unit/`) - Pure Python logic, no external dependencies
  - UMF model validation
  - Type mappings
  - Schema generators
  - GX baseline generation

- **Integration tests** (`tests/integration/`) - Tests requiring external dependencies
  - PySpark integration
  - Great Expectations validation
  - Deequ profiling

### Running Tests

```bash
# Run all tests
make test

# Run only unit tests (fast)
make test-unit

# Run only integration tests
make test-integration

# Run specific test file
uv run pytest tests/unit/test_gx_baseline.py

# Run with verbose output
uv run pytest -v

# Run with coverage
make coverage  # Generates HTML report in htmlcov/
```

### Writing Tests

#### Unit Test Example

```python
import pytest
from tablespec import UMF, UMFColumn, Nullable


def test_umf_validation():
    """Test UMF model validates required fields."""
    umf = UMF(
        version="1.0",
        table_name="Test_Table",
        columns=[
            UMFColumn(
                name="test_col",
                data_type="VARCHAR",
                length=100,
                nullable=Nullable(MD=False, MP=False, ME=False)
            )
        ]
    )
    assert umf.table_name == "Test_Table"
    assert len(umf.columns) == 1
```

#### Integration Test Example

```python
import pytest
from tablespec import SparkToUmfMapper

@pytest.mark.skipif(not SPARK_AVAILABLE, reason="PySpark not installed")
def test_spark_profiling(spark_session):
    """Test Spark DataFrame profiling to UMF."""
    # Test requires PySpark
    mapper = SparkToUmfMapper()
    # ... test implementation
```

### Coverage Requirements

- Aim for **80%+ coverage** on new code
- All public API functions should have tests
- Critical paths (type mappings, schema generation) require 100% coverage

## Documentation

### When to Update Documentation

- **README.md** - Update for new features, API changes, or usage examples
- **CLAUDE.md** - Update for architecture changes, new modules, or development patterns
- **Docstrings** - Required for all public functions and classes
- **Type hints** - Required for all function signatures

### Docstring Format

Use Google-style docstrings:

```python
def generate_pyspark_schema(umf_dict: Dict, include_nullable: bool = True) -> str:
    """Generate PySpark StructType schema code from UMF.

    Converts a UMF dictionary into executable PySpark schema code that can be
    used to define DataFrame schemas programmatically.

    Args:
        umf_dict: Dictionary representation of UMF model
        include_nullable: Whether to include nullable parameters (default: True)

    Returns:
        String containing PySpark StructType schema code

    Raises:
        ValueError: If umf_dict is missing required fields
        KeyError: If column data_type is invalid

    Example:
        >>> umf = load_umf_from_yaml("schema.yaml")
        >>> schema_code = generate_pyspark_schema(umf.model_dump())
        >>> print(schema_code)
        StructType([StructField("claim_id", StringType(), False), ...])
    """
```

## Pull Request Process

### Before Submitting

Complete this checklist:

- [ ] Code follows project style (run `make format`)
- [ ] All linting passes (run `make lint`)
- [ ] Type checking passes (run `make type-check`)
- [ ] All tests pass (run `make test`)
- [ ] New tests added for new functionality
- [ ] Documentation updated (README.md, docstrings)
- [ ] Commits are clear and descriptive
- [ ] No unnecessary files committed (check `.gitignore`)

### Submitting a Pull Request

1. **Push your branch**

   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a pull request** on GitHub with:
   - Clear title describing the change
   - Description of what changed and why
   - Reference any related issues
   - Screenshots/examples if applicable

3. **PR template**

   ```markdown
   ## Description
   Brief description of changes

   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Refactoring

   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests added/updated
   - [ ] All tests pass locally

   ## Checklist
   - [ ] Code formatted with Ruff
   - [ ] Linting passes
   - [ ] Type checking passes
   - [ ] Documentation updated
   ```

### Review Process

- Maintainers will review within 3-5 business days
- Address feedback with new commits (no force-push)
- Once approved, maintainers will merge

### Merge Criteria

Pull requests must:

- Pass all CI checks (lint, type-check, tests)
- Have at least one approving review
- Have no unresolved conversations
- Be up-to-date with main branch

## Project-Specific Guidelines

### UMF Format Conventions

- **Version**: Always `"1.0"` for current spec
- **Table names**: Use `PascalCase` (e.g., `Medical_Claims`)
- **Column names**: Use `snake_case` (e.g., `claim_id`)
- **Nullable**: Always specify per LOB (MD, MP, ME)
- **Data types**: Use uppercase (VARCHAR, INTEGER, etc.)

### Type Mappings Principles

All type conversions go through `type_mappings.py`:

- **Bidirectional**: Support both UMF → Target and Target → UMF when possible
- **Lossless**: Preserve precision, length, scale information
- **Explicit**: Require all necessary parameters (length for VARCHAR)
- **Consistent**: Use same function signature pattern across all mappers

### Great Expectations Integration

- **Baseline generation**: Must be deterministic (same UMF = same expectations)
- **Constraint extraction**: Reverse-engineer UMF from existing suites
- **Validation**: Integrate with TableValidator for DataFrame validation

### Optional Dependencies

- **PySpark features**: Must gracefully handle missing PySpark
- **Conditional imports**: Use try/except in `__init__.py`
- **Clear errors**: Guide users to install `umf-tablespec[spark]` when needed
- **Documentation**: Mark Spark-dependent features in README

### Makefile Guidelines

- Keep the Makefile self-documenting
- Use `## comments` for help text
- Targets should be simple, readable commands
- Group related targets (setup, code quality, testing, etc.)

## Getting Help

### Resources

- **Issues**: [GitHub Issues](https://github.com/harmonycares/tablespec/issues) for bugs and feature requests
- **Discussions**: [GitHub Discussions](https://github.com/harmonycares/tablespec/discussions) for questions
- **Documentation**: README.md and CLAUDE.md for detailed guides

### Reporting Issues

When reporting bugs, include:

- Python version (`python --version`)
- tablespec version
- Minimal reproducible example
- Expected vs actual behavior
- Full error traceback

### Feature Requests

When requesting features, describe:

- Use case and motivation
- Proposed API or interface
- Examples of how it would be used
- Any alternatives you've considered

### Contact

- **Team**: HarmonyCares CHA Platform Team
- **Email**: cha-platform@harmonycares.com

---

Thank you for contributing to tablespec! Your efforts help improve schema metadata management for the entire community.
