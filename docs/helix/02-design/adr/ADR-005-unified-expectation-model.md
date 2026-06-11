---
ddx:
  id: ADR-005
---

# ADR-005: Unified Expectation Model

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
