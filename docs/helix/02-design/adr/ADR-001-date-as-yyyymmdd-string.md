---
ddx:
  id: ADR-001
---

# ADR-001: DATE Type Maps to StringType (YYYYMMDD Strings)

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | ADR-015 | High |

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

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Map DATE to native date types everywhere | Gives Spark date arithmetic without casting; mirrors SQL engine behavior | Loses the source's string representation for text-landed files; creates parse/format drift between source bytes and schema; does not fit the legacy-file contract this ADR addresses | Rejected: the source contract here is text-landed, not typed |
| Store DATE as strings without format validation | Preserves raw text faithfully | Allows malformed dates and does not distinguish the intended YYYYMMDD contract from arbitrary text | Rejected: faithful storage alone is not enough; validation would be too weak |
| **Map DATE to StringType with `%Y%m%d` validation (selected)** | Preserves the actual source shape and enforces the fixed-width contract in GX | Requires consumers to cast before using native date functions; SQL DDL may still expose a native DATE on the database side | **Selected: this is the only option that matches the text-landed contract without losing the format guarantee** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Consumers assume DATE is native Spark date data | M | M | Call out the StringType mapping explicitly in docs; ADR-015 scopes the convention to text-landed sources only |
| The fixed `%Y%m%d` format later needs to vary by source | L | M | Treat that as a separate source-shape rule; the validation hook is the narrow seam, not the whole ADR |
| SQL DDL and Spark/GX type systems remain intentionally asymmetric | M | L | Keep the asymmetry documented; consumers that need casts can perform them explicitly |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `tests/unit/test_type_mappings.py` and `tests/unit/test_gx_baseline.py` keep DATE mapped to StringType with `%Y%m%d` validation | A date column stops round-tripping as a string in the text-landed path |
| ADR-015 remains the only scope expansion for typed sources | A new source kind tries to reuse the text-landed convention without a separate decision |

## Supersession

- **Supersedes**: None
- **Superseded by**: ADR-015 for typed-source scope expansion; this ADR remains in force for text-landed sources.

## Concern Impact

- **No concern impact**: This ADR narrows a type mapping rule and does not override a library concern practice.

## References

- ADR-015 (source-shape contract) for the typed-source scope expansion.
- `src/tablespec/type_mappings.py`, `src/tablespec/gx_baseline.py`
- `tests/unit/test_type_mappings.py`, `tests/unit/test_gx_baseline.py`

## Review Checklist

- [x] Context names a specific problem — DATE mapping inconsistency for text-landed sources
- [x] Decision statement is actionable — DATE maps to StringType with `%Y%m%d` validation
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with ADR-015's typed-source scope split
