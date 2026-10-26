# tablespec Integration Tests

Integration tests that verify tablespec features requiring external dependencies like PySpark and Great Expectations.

## Running Tests

### Run all integration tests:
```bash
pytest tests/integration/ -v
```

### Run with markers:
```bash
# Run only integration tests
pytest -m integration tests/integration/

# Skip integration tests (for CI without Spark)
pytest -m "not integration"
```

## Test Requirements

Tests are automatically skipped if required dependencies are not available.

### PySpark Features

Requires PySpark installed:
```bash
pip install umf-tablespec[spark]
# or
uv sync --extra spark
```

Tests requiring PySpark:
- Spark DataFrame profiling
- SparkToUmfMapper functionality
- TableValidator with Spark DataFrames

### Great Expectations Features

Requires Great Expectations (installed by default):
```bash
pip install umf-tablespec
```

Tests using GX:
- Full validation workflow
- Expectation suite generation and execution
- Integration with data sources

## What Gets Tested

Integration tests verify:
1. End-to-end workflows (UMF → GX → validation)
2. Spark DataFrame profiling and type mapping
3. Great Expectations validation execution
4. File I/O operations with real data
5. Cross-module integration

## CI/CD Integration

Add to your CI config to run tests only when dependencies are available:

```yaml
# GitHub Actions example
- name: Run integration tests
  run: |
    pip install umf-tablespec[spark]
    pytest tests/integration/ -v
  continue-on-error: true  # Don't fail CI if Spark unavailable
```

## Adding New Integration Tests

When adding integration tests:
1. Mark with `@pytest.mark.integration` if creating markers
2. Use `@pytest.mark.skipif` for optional dependencies
3. Include docstrings explaining what's being tested
4. Clean up any temporary files created during tests
5. Use fixtures from `conftest.py` for common setup

## Current Status

⚠️ **Integration test suite is currently empty and needs to be developed.**

Planned integration tests:
- [ ] Spark DataFrame to UMF profiling
- [ ] Full GX validation workflow
- [ ] UMF model I/O operations
- [ ] Schema generation with real data
- [ ] Cross-format type conversion accuracy
