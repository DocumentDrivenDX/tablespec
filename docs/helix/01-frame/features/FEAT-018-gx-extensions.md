---
ddx:
  id: FEAT-018
---

# FEAT-018: Custom GX Extensions

**Status**: Implemented
**Priority**: P0
**Feature ID**: FEAT-018
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Table Validation
**Covered PRD Requirements**: FR-7.5
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Custom Great Expectations expectation classes that bridge tablespec domain concepts into GX execution.

## Implemented Components

### ExpectColumnValuesToMatchDomainType (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Loads the domain type registry (`src/tablespec/domain_types.yaml`), validates that column values match the validation spec for the assigned domain type (regex patterns, value sets, format constraints).

Works on Spark and Sail execution backends. Bridges domain types from FEAT-013 into the GX validation pipeline.

```python
# Usage in expectation suite
{
    "type": "expect_column_values_to_match_domain_type",
    "kwargs": {"column": "gender_cd", "domain_type": "gender_code"}
}
```

### ExpectColumnValuesToCastToType (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Validates actual Spark casting (not just pattern matching). Catches edge cases like "2023-02-30" (format-valid but date-invalid). Supports flexible date/timestamp parsing with fallback formats. Skips validation if column is already the target type (pre-typed Gold tables).

### ExpectColumnDateToBeInCurrentYear (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Validates date values fall within current calendar year using dynamic Spark SQL DATE_TRUNC for year bounds. Supports mostly threshold.

### ExpectColumnPairDateOrder (`src/tablespec/validation/custom_gx_expectations.py`) -- DONE

Cross-column date ordering for start_date < end_date patterns common in temporal data (eligibility spans, enrollment periods, contract dates, event ranges). Supports `or_equal` flag and null pair handling.

### Standalone Validators -- DONE

- `validate_domain_type()` — PySpark DataFrame validator for domain types (usable without GX framework)
- `validate_column_pair_date_order()` — PySpark DataFrame validator for date ordering

## Acceptance Criteria

| # | Criterion | Test Evidence |
|---|-----------|---------------|
| AC-1 | Domain type value set validation (state codes, gender, LOB) | `test_domain_type_expectation.py::test_*_valid/invalid` |
| AC-2 | Domain type regex validation (email, NPI, ZIP, phone) | `test_domain_type_expectation.py::test_*_regex*` |
| AC-3 | Domain type length validation | `test_domain_type_expectation.py::test_*_length*` |
| AC-4 | Mostly threshold support | `test_domain_type_expectation.py::test_*_mostly*` |
| AC-5 | Null handling (all nulls pass, mixed nulls excluded) | `test_domain_type_expectation.py::test_*_null*` |
| AC-6 | Unknown domain type fails with clear message | `test_domain_type_expectation.py::test_*_unknown*` |
| AC-7 | Date pair ordering with valid/invalid data | `test_date_order_expectation.py` |
| AC-8 | Date pair or_equal flag (>= vs >) | `test_date_order_expectation.py` |
| AC-9 | Result structure includes element_count, unexpected_count, partial_unexpected_list | `test_domain_type_expectation.py::test_*_result*` |
## User Stories

- [US-031 — Validate Custom GX Expectations](../user-stories/US-031-validate-custom-gx-expectations.md)

## Source

- `src/tablespec/validation/custom_gx_expectations.py`

## Dependencies

- FEAT-013 (domain type registry)
- FEAT-024 (Spark/Sail session for execution)
