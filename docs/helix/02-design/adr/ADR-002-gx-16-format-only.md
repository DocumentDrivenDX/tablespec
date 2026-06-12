---
ddx:
  id: ADR-002
---

# ADR-002: Only Great Expectations 1.6+ Format Is Supported

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | — | High |

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

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Support both legacy and 1.6+ GX formats | Easier migration for existing users | Doubles the code path surface; requires format detection, conversion, and dual tests everywhere GX is consumed | Rejected: the extra complexity is not justified when the supported format already exists |
| Auto-convert legacy suites on read | Hides the migration burden from users | Loses explicitness, makes round-trips harder to reason about, and can mask malformed legacy inputs | Rejected: migration should be visible and actionable |
| **Require GX 1.6+ format and reject legacy input (selected)** | One format contract; fast failure with clear migration guidance; simpler validation and schema handling | Existing legacy suites must be updated first | **Selected: the library already generates the modern shape, so a single format contract is the safest boundary** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Existing suites in the wild fail to load until migrated | M | M | Emit explicit rename/remove messages so migration is mechanical |
| GX upstream changes the 1.6+ shape again | L | M | Keep the JSON schema and `_validate_gx_format()` in lockstep with the supported GX release range |
| Broader dependency pins allow users onto an older GX runtime that still satisfies `>=0.18.0` | M | L | The explicit format validator catches mismatches before execution |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Legacy indicators (`expectation_suite_name`, `data_asset_type`, `expectation_type`) are rejected in `tests/unit/test_gx_processor.py` | A legacy suite is accepted without the migration hint |
| Generated suites continue to serialize and validate in 1.6+ format | GX emits a new required field or renames the supported fields |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **No concern impact**: This ADR narrows the accepted GX wire format and does not override a library concern practice.

## References

- `src/tablespec/validation/gx_processor.py`
- `src/tablespec/models/umf.py`
- `tests/unit/test_gx_processor.py`, `tests/unit/test_expectation_suite.py`

## Review Checklist

- [x] Context names a specific problem — legacy GX wire-format support
- [x] Decision statement is actionable — only 1.6+ format is accepted
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with the shipped GX integration path
