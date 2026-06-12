---
ddx:
  id: ADR-005
---

# ADR-005: Unified Expectation Model

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | — | ADR-017 | High |

## Status

Accepted (Phase C — consumers migrated to ExpectationSuite; legacy fields emit DeprecationWarning)

## Context

Currently `validation_rules` (for Bronze.Raw) and `quality_checks` (for Bronze.Ingested) use different data models for the same underlying thing: Great Expectations expectations. The inconsistencies are:

- **ValidationRules** stores expectations as flat dicts with severity embedded in `meta`.
- **QualityChecks** wraps each expectation in a `QualityCheck` object with `severity`, `blocking`, and `tags` as top-level fields.
- Storage is scattered across 3 files in split format (`validation_rules.yaml`, `quality_checks.yaml`, plus column-level expectations).
- Severity location is inconsistent (meta vs top-level).
- No executor exists for `validation_rules` -- only `quality_checks` has one (`quality/executor.py`).
- `classify_validation_type()` exists but is never called by the validation pipeline.

This creates duplicate models, asymmetric execution, and confusion about where to add new expectations.

## Decision

Replace the dual `validation_rules` + `quality_checks` fields on UMF with a single `ExpectationSuite` model where stage (raw/ingested) is a field on each expectation, not a container boundary.

### New Model

```python
class Expectation(BaseModel):
    type: str                    # GX expectation type
    kwargs: dict[str, Any]       # GX kwargs
    meta: ExpectationMeta        # Structured metadata

class ExpectationMeta(BaseModel):
    stage: Literal["raw", "ingested"]  # From classify_validation_type()
    severity: Literal["critical", "error", "warning", "info"] = "warning"
    blocking: bool = False
    description: str | None = None
    tags: list[str] = []
    generated_from: str | None = None  # "baseline", "profiling", "llm", "user"

class ExpectationSuite(BaseModel):
    expectations: list[Expectation]
    thresholds: dict[str, Any] | None = None
    alert_config: dict[str, Any] | None = None
    pending: list[Expectation] = []
```

### Migration Strategy

Phased rollout to avoid breaking consumers:

1. **Phase A**: Add new model alongside old fields.
2. **Phase B**: Loader populates new model from old format on read.
3. **Phase C**: Update consumers to read from new model.
4. **Phase D**: Saver writes new format.
5. **Phase E**: Deprecate old fields.

Column-specific expectations in split format stay in column YAML files; the loader merges them into the suite with stage auto-classified via `classify_validation_type()`. Unknown expectation types get `stage="unknown"` and produce a warning rather than silently defaulting.

### ExpectationMeta Conversion Layer

When handing expectations to GX for execution, `ExpectationMeta` serializes to a plain dict for the GX `meta` field. When reading results back, the dict is parsed into `ExpectationMeta`. GX preserves unknown keys in meta dicts, so custom fields (stage, severity, blocking, generated_from, etc.) survive round-trips through GX execution without data loss.

### Storage

In split format, `expectations.yaml` replaces `validation_rules.yaml` + `quality_checks.yaml`. This is a deliberate tradeoff: one file is simpler but loses the merge-conflict isolation of separate files. The `stage` field provides programmatic separation when needed.

## Consequences

### Positive

- Single model for all expectations eliminates duplicate data structures.
- Stage classification is explicit and queryable, not implicit from file location.
- One executor handles all expectations, filtered by stage at runtime.
- Severity, blocking, and tags are consistently structured across all expectations.
- `generated_from` field enables provenance tracking for LLM, profiling, and baseline sources.

### Negative

- 12+ modules need updating (`gx_baseline.py`, `quality/executor.py`, `gx_constraint_extractor.py`, `gx_wrapper.py`, `umf_loader.py`, `sync_baseline.py`, `models/umf.py`, `prompts/`, `validator.py`, `completeness_validator.py`, CLI commands).
- Backward-compatible reading of old format required indefinitely -- old UMF files must continue to load.
- External pipeline (pulseflow) needs coordinated update to consume the new model.
- Losing separate files means merge conflicts are more likely when multiple developers edit expectations concurrently.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep `validation_rules` and `quality_checks` as separate models | No migration work | The same expectation concepts remain duplicated and asymmetric; consumers must keep learning two shapes | Rejected: the split model is the source of the confusion this ADR addresses |
| Introduce a single model but keep both legacy container fields forever | Easier backward compatibility | Preserves the old model split at the container level and leaves the public surface muddy | Rejected: a new unified model should actually unify the entry point |
| **Adopt `ExpectationSuite` with phased compatibility and deprecation (selected)** | One canonical model; stage becomes an expectation attribute; old files still load while consumers migrate | Requires a multi-phase rollout and long-lived compatibility handling | **Selected: this is the only path that unifies the model without breaking existing UMFs** |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Consumers keep reading legacy fields after the new model exists | M | M | The deprecation warnings and phased rollout make the migration path explicit |
| Backward compatibility becomes permanent technical debt | H | M | Treat the legacy fields as compatibility only and keep the new model as the source of truth |
| External integrations lag behind the model change | M | M | Keep loader/saver conversion paths stable until downstream consumers migrate |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| New `ExpectationSuite` round-trips through loader/saver and executor tests | A consumer path still depends on the legacy split model as a first-class API |
| Legacy fields emit `DeprecationWarning` while continuing to load | A legacy file stops loading before the migration window is complete |

## Supersession

- **Supersedes**: The split `validation_rules` / `quality_checks` model.
- **Superseded by**: None

## Concern Impact

- **No concern impact**: This ADR changes the validation data model and does not override a library concern practice.

## References

- `src/tablespec/models/umf.py`
- `src/tablespec/gx_baseline.py`
- `src/tablespec/quality/executor.py`
- `src/tablespec/validation/gx_constraint_extractor.py`
- `tests/unit/test_expectation_suite.py`, `tests/unit/test_expectation_consumers.py`

## Review Checklist

- [x] Context names a specific problem — two models for the same expectation concepts
- [x] Decision statement is actionable — move to a single `ExpectationSuite`
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with the unified expectation rollout
