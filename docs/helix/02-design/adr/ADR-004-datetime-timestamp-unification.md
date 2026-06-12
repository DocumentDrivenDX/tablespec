---
ddx:
  id: ADR-004
---

# ADR-004: Unify DATETIME and TIMESTAMP as Equivalent UMF Types

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | — | High |

## Status

Accepted

## Context

The tablespec type system has an inconsistency in how it handles DATETIME and TIMESTAMP column types across its modules. These two type names are semantically equivalent (both represent a date-and-time value), but the codebase treats them differently depending on where they appear:

1. **Pydantic model** (`models/umf.py`): The column type regex `^(VARCHAR|DECIMAL|INTEGER|DATE|DATETIME|BOOLEAN|TEXT|CHAR|FLOAT)$` accepts DATETIME but rejects TIMESTAMP. Any UMF YAML file using `data_type: TIMESTAMP` fails Pydantic validation.

2. **Type mappings** (`type_mappings.py`): The mapping dicts (`map_to_gx_spark_type`, `map_to_pyspark_type`, `map_to_json_type`) explicitly handle TIMESTAMP but not DATETIME. A DATETIME column falls through to the default case and is mapped to `StringType`, which is incorrect -- DATETIME should map to `TimestampType`.

3. **GX baseline** (`gx_baseline.py`): This module correctly handles both DATETIME and TIMESTAMP, generating appropriate expectations for either spelling.

4. **PySpark schema generator** (`schemas/generators.py`): `generate_pyspark_schema()` maps DATETIME to `StringType` because it relies on `type_mappings.py`, which lacks a DATETIME entry. The correct mapping is `TimestampType`.

5. **SQL DDL generator** (`schemas/generators.py`): `generate_sql_ddl()` passes DATETIME through as a literal SQL type, which happens to work in most SQL dialects but is not explicitly intentional.

The net effect is that neither DATETIME nor TIMESTAMP works correctly end-to-end. DATETIME passes validation but produces wrong PySpark types. TIMESTAMP produces correct PySpark types but fails Pydantic validation. Users have no fully correct path for timestamp columns.

## Decision

Both DATETIME and TIMESTAMP will be treated as equivalent, valid UMF column types that map to `TimestampType` in PySpark and Great Expectations contexts.

The changes are:

1. **Pydantic model** (`models/umf.py`): Add TIMESTAMP to the column type regex, making it `^(VARCHAR|DECIMAL|INTEGER|DATE|DATETIME|TIMESTAMP|BOOLEAN|TEXT|CHAR|FLOAT)$`. Both spellings pass validation.

2. **Type mappings** (`type_mappings.py`): Add DATETIME as an explicit entry in all three mapping dicts, aliased to the same target as TIMESTAMP:
   - `map_to_gx_spark_type()`: DATETIME and TIMESTAMP both map to `"TimestampType"`.
   - `map_to_pyspark_type()`: DATETIME and TIMESTAMP both map to `"TimestampType()"`.
   - `map_to_json_type()`: DATETIME and TIMESTAMP both map to `{"type": "string", "format": "date-time"}`.

3. **No changes needed** to `gx_baseline.py` (already handles both) or `generate_sql_ddl()` (literal pass-through is acceptable for both DATETIME and TIMESTAMP in standard SQL dialects).

DATETIME and TIMESTAMP are interchangeable aliases, not distinct types. No canonical form is enforced -- UMF authors may use either spelling according to their preference or domain conventions.

## Consequences

### Positive

- Eliminates a class of silent bugs where DATETIME columns are mapped to `StringType` instead of `TimestampType`, causing downstream PySpark jobs to treat timestamps as strings.
- Users can use either DATETIME or TIMESTAMP in UMF YAML files and get correct behavior across all modules (validation, schema generation, GX baseline, type mappings).
- The fix is backward-compatible: existing UMF files using DATETIME continue to pass validation; the only change is that their PySpark and GX type mappings are now correct.
- Aligns with the principle that UMF is the single source of truth -- a type declared in UMF should produce correct output in every downstream generator.

### Negative

- Having two accepted spellings for the same semantic type introduces ambiguity. Different UMF files in the same project might use different spellings, reducing consistency.
- No migration or normalization is provided. Existing UMF files that relied on the (incorrect) DATETIME-to-StringType mapping will silently change behavior when the fix is applied. Consumers that depend on timestamp columns being strings will need to adapt.
- The SQL DDL generator passes both DATETIME and TIMESTAMP through literally, which may produce different behavior across SQL dialects (e.g., MySQL distinguishes DATETIME from TIMESTAMP in storage and timezone handling). This ADR does not address SQL dialect-specific semantics.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep DATETIME and TIMESTAMP separate | Preserves dialect-specific meanings | Leaves the current inconsistency in place and keeps one spelling broken in parts of the toolchain | Rejected: the code already treats them as the same semantic family |
| Canonicalize on TIMESTAMP only | One spelling to document | Forces migration of existing DATETIME UMFs even when the semantics are identical | Rejected: the ADR's goal is compatibility, not a spelling migration |
| **Treat DATETIME and TIMESTAMP as equivalent aliases (selected)** | Fixes the broken mapping without forcing a canonical rename; both spellings work end-to-end | Adds a second accepted spelling and the resulting naming ambiguity | **Selected: this is the least disruptive way to make both spellings correct across the stack** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Different projects choose different spellings for the same meaning | M | L | Document the equivalence and keep the accepted spellings explicit in the model regex and mappings |
| SQL dialects disagree on DATETIME vs TIMESTAMP storage semantics | M | M | Leave the SQL DDL generator literal and document the dialect-specific caveat rather than pretending the types are universal |
| Existing users that relied on the broken StringType mapping see changed behavior | M | M | Call out the behavior change clearly; consumers that need strings can cast explicitly |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `tests/unit/test_umf_models.py`, `tests/unit/test_type_mappings.py`, and `tests/unit/test_gx_baseline.py` accept both spellings and map them consistently | A timestamp spelling starts failing model validation or falls back to StringType again |
| SQL DDL generation remains intentionally literal for both spellings | A later change tries to infer dialect-specific semantics without a separate ADR |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **No concern impact**: This ADR standardizes a type alias; it does not override a library concern practice.

## References

- `src/tablespec/models/umf.py`
- `src/tablespec/type_mappings.py`
- `src/tablespec/gx_baseline.py`
- `src/tablespec/schemas/generators.py`
- `tests/unit/test_umf_models.py`, `tests/unit/test_type_mappings.py`, `tests/unit/test_gx_baseline.py`

## Review Checklist

- [x] Context names a specific problem — DATETIME/TIMESTAMP handling disagrees across modules
- [x] Decision statement is actionable — both spellings map to the same timestamp semantics
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with the existing timestamp generator behavior
