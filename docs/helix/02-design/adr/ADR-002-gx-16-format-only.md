---
ddx:
  id: ADR-002
---

# ADR-002: Only Great Expectations 1.6+ Format Is Supported

## Status

Accepted

## Context

Great Expectations underwent significant API changes between its legacy versions and the 1.6+ release. Key structural differences include:

- **Suite naming**: Legacy uses `expectation_suite_name`; GX 1.6+ uses `name`.
- **Expectation type field**: Legacy uses `expectation_type`; GX 1.6+ uses `type`.
- **Removed fields**: Legacy includes `data_asset_type` at the suite level, which no longer exists in 1.6+.

The tablespec library generates, processes, validates, and merges GX expectation suites as part of its schema validation pipeline. Supporting both legacy and modern formats would require format detection, bidirectional conversion, and dual code paths throughout the GX integration layer.

## Decision

Only Great Expectations 1.6+ format is supported. Legacy format is explicitly detected and rejected with actionable error messages.

In `validation/gx_processor.py`, the `_validate_gx_format()` method checks for legacy indicators and rejects them:

- If `expectation_suite_name` is present instead of `name`, an error is returned: "Legacy format: rename 'expectation_suite_name' to 'name'".
- If `data_asset_type` is present, an error is returned: "Legacy field 'data_asset_type' not supported (remove it)".
- If expectations use `expectation_type` instead of `type`, an error is returned: "Legacy format: rename 'expectation_type' to 'type' in expectations".
- The `name` field and `expectations` array with `type` and `kwargs` per expectation are required.

Format validation runs before schema validation and GX library validation, providing fast failure with clear guidance on how to migrate.

## Consequences

### Positive

- Eliminates the complexity of maintaining dual format support, reducing code surface area and test matrix.
- Error messages are specific and actionable, telling users exactly which fields to rename or remove.
- Aligns with the GX project's own direction; legacy format is deprecated upstream.
- Simplifies JSON Schema validation by targeting a single format definition (`gx_expectation_suite.schema.json`).
- All internally generated suites (from `UmfToGxMapper` and `BaselineExpectationGenerator`) produce 1.6+ format by default, ensuring consistency.

### Negative

- Users with existing legacy-format expectation suites must migrate them before tablespec can process them. There is no automatic conversion.
- Pinning to 1.6+ format means any future GX format changes would require updates to the format validator, JSON schema, and processors.
- The `pyproject.toml` dependency is `great-expectations>=0.18.0`, which is broader than the 1.6+ format requirement. Users on older GX versions that technically satisfy the dependency constraint may encounter format mismatches at runtime.
