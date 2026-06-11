---
ddx:
  id: ADR-001
---

# ADR-001: DATE Type Maps to StringType (YYYYMMDD Strings)

## Status

Accepted — scoped by ADR-015 (2026-06-10) to **text-landed sources only**
(delimited files, database dumps). Typed sources (parquet, JDBC) map DATE
natively under the kind-dependent raw contract; the YYYYMMDD-string
convention below applies where data lands as text.

## Context

The tablespec library commonly processes data from legacy systems, EDI transactions, and flat-file extracts where date values are stored as YYYYMMDD strings (e.g., `"20260315"`) rather than as native date types. This pattern is widespread in healthcare (CMS, Medicaid/Medicare), financial services (SWIFT messages, FIX protocol), and government data systems.

When mapping UMF column types to PySpark and Great Expectations type systems, a choice must be made: should `DATE` columns be mapped to native date types (e.g., PySpark `DateType`) or to string types that preserve the original YYYYMMDD representation?

## Decision

The `DATE` UMF type maps to `StringType` in both PySpark and Great Expectations contexts. DATE columns additionally receive a `expect_column_values_to_match_strftime_format` expectation with `%Y%m%d` format to enforce the YYYYMMDD pattern.

Specifically:

- In `type_mappings.py`, both `map_to_gx_spark_type()` and `map_to_pyspark_type()` map `"DATE"` to `"StringType"` / `"StringType()"` (with an inline comment: "Dates stored as YYYYMMDD strings").
- In `gx_baseline.py`, `BaselineExpectationGenerator.generate_baseline_column_expectations()` adds a `expect_column_values_to_match_strftime_format` expectation with `strftime_format: "%Y%m%d"` for any column with `data_type == "DATE"`.
- In `type_mappings.py`, `map_to_json_type()` maps `"DATE"` to `"string"` in JSON Schema output.

## Consequences

### Positive

- Faithfully represents how date data actually exists in legacy source systems (healthcare, financial services, government), avoiding lossy or error-prone date parsing at the schema level.
- Validates the specific YYYYMMDD format via Great Expectations, catching malformed date strings (e.g., `"2026-03-15"`, `"03152026"`) that would silently succeed with a permissive DateType.
- Avoids PySpark date parsing issues with non-standard formats, timezone ambiguity, and null handling differences between `DateType` and `StringType`.
- Consistent with upstream data contracts where dates are defined as fixed-length character fields.

### Negative

- Consumers of generated PySpark schemas cannot use native Spark date functions (e.g., `datediff`, `date_add`) directly on DATE columns without an explicit cast.
- SQL DDL generation maps DATE to a SQL `DATE` type, creating a mismatch between the SQL schema (native date) and the PySpark/GX schema (string). Consumers must be aware of this distinction.
- The `%Y%m%d` format is hardcoded; if a future use case requires a different date string format (e.g., `MMDDYYYY`), the baseline generator would need to be extended.
