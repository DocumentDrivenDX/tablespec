---
ddx:
  id: ADR-004
---

# ADR-004: Unify DATETIME and TIMESTAMP as Equivalent UMF Types

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
