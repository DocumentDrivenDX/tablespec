---
ddx:
  id: FEAT-016
---

# FEAT-016: Testing Infrastructure for Agentic Development

**Status**: Approved
**Priority**: P0
**Feature ID**: FEAT-016
**Owner**: Engineering Productivity
**Covered PRD Subsystem(s)**: Runtime Platform
**Covered PRD Requirements**: None — meta-feature anchored to the Product Vision and Principles per the traceability convention (principles.md §Tension Resolution, decided 2026-06-10); provides the evidence tier for FR-20.3's serverless/Connect target without owning runtime behavior.
**Cross-Subsystem Rationale**: Verification support feature: test infrastructure proves supported runtime targets without owning runtime behavior.

## Description

Foundational testing infrastructure enabling fast iteration, property-based testing, and test-first development workflows. All components are additive -- existing tests remain unchanged.

## Components

### GX Test Harness (`tests/conftest.py`)

Execute GX expectations against Spark or Sail backends. Wraps GX context/datasource/validator setup behind a simple API.

Returns structured `GXTestResult` objects with:
- Pass/fail status per expectation
- Observed values
- Unexpected counts
- Sample unexpected values

```python
harness = GXTestHarness(backend="sail")  # or "spark"
result = harness.run(expectations, data_path="test.csv", stage="raw")
assert result.all_passed
assert result["expect_column_to_exist"]["column_name"].success
```

### UMF Builder DSL (`tests/builders.py`)

Composable builder for test fixtures replacing ad-hoc `_make_umf()` helpers and raw dict construction across test files.

```python
umf = (UMFBuilder("test_table")
    .column("id", "INTEGER", nullable=False)
    .column("name", "VARCHAR", length=100)
    .column("amount", "DECIMAL", precision=10, scale=2)
    .build())  # Returns UMF object

ddl = generate_sql_ddl(umf.as_dict())  # .as_dict() for dict consumers
```

- `.build()` returns UMF model objects (for UMFDiff, compatibility checker).
- `.as_dict()` returns dicts (for `generate_sql_ddl`, `generate_pyspark_schema`).

### Golden File Runner (`tests/golden/`)

Auto-discovers test cases from directory structure:

```
tests/golden/{feature}/{case}.input.yaml
tests/golden/{feature}/{case}.expected.sql
tests/golden/{feature}/{case}.expected.json
```

Parametrized via pytest. Failure produces unified diff. Used only for short, human-verifiable outputs (~30 lines max). Complex outputs use property tests instead.

### Hypothesis Strategies (`tests/strategies.py`)

`tests/strategies.py` with composable strategies for property-based testing:

- `umf_column()` -- generates valid UMFColumn instances
- `umf_dict()` -- generates valid UMF dicts
- `umf_object()` -- generates valid UMF model objects

Every generated value passes Pydantic validation. Extends existing Hypothesis usage in `tests/unit/test_yaml_formatter_fuzzing.py`.

### Fast Test Marker (`pyproject.toml`)

`@pytest.mark.fast` for tests completing in <100ms with no I/O, no Spark, no network. Registered in `pyproject.toml` markers. Agent runs `pytest -m fast` during iteration for sub-second feedback.

### Test Discovery Convention (`tests/`)

Source file `src/tablespec/foo.py` maps to test file `tests/unit/test_foo.py`.

For new features: write test file first with `@pytest.mark.xfail` tests as the executable spec. Implementation removes `xfail` by making tests pass.
## User Stories

- [US-029 — Maintain Agentic Test Infrastructure](../user-stories/US-029-maintain-agentic-test-infrastructure.md)

## Source

- `tests/conftest.py` (harness fixtures, builder, markers)
- `tests/strategies.py` (Hypothesis strategies)
- `tests/golden/` (golden file test cases)
- `pyproject.toml` (marker registration)

## Dependencies

- `tablespec[lite]` (Sail backend) or `tablespec[spark]` (Spark backend) for GX harness
