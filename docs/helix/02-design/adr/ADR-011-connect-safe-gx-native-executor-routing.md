---
ddx:
  id: ADR-011
---

# ADR-011: Connect-Safe GX Suite Execution via Per-Expectation Native-Executor Routing

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Erik LaBianca | FEAT-025, FEAT-007, ADR-005, ADR-010 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | GX 1.x `add_spark` / `SparkDFExecutionEngine` silently returns wrong answers on Spark Connect (Sail, Databricks serverless): every data-scanning expectation reports `success=False` / `result={}`, so a clean DataFrame fails validation and dirty data can be masked by a uniform false-negative. |
| Current State | `GXSuiteExecutor` built a GX Spark datasource (`context.data_sources.add_spark`) and ran the whole suite through `SparkDFExecutionEngine`. That engine uses classic `pyspark.sql.functions` (`F.lit`, `F.count`) which assert `SparkContext._active_spark_context is not None`. On Connect there is no JVM `SparkContext`; the assertion fails, the error is swallowed, and the suite returns garbage. See `src/tablespec/validation/native_executor.py:1-31`. |
| Requirements | PRD FR-7.7 (Connect-safe suite execution with per-expectation routing) and FR-20.4 (Connect-safe validation path). A compiled GX suite must run with identical verdicts on classic Spark and on Spark Connect / serverless. |
| Decision Drivers | Connect-safe-by-construction (principle 3); validation must "test exactly what ingestion does" on the same engines production runs on; a silent false-negative in validation is the worst possible failure mode for a data-quality contract. |

## Decision

We will route GX suite execution per-DataFrame-engine: Spark **Connect** DataFrames are evaluated by a native DataFrame-API executor (`tablespec.validation.native_executor`), and **classic** Spark DataFrames keep the unchanged GX `add_spark` path. The routing key is the DataFrame itself, never a process-global flag.

**Key Points**: Detect Connect by the DataFrame's own module (`type(df).__module__.startswith("pyspark.sql.connect")`, `gx_executor.py:211-220`) | Native executor re-implements each baseline expectation type with engine-correct `functions` selected from the DataFrame (`_functions_for`) and bound columns (`df[col]`), returning the SAME `ExpectationResult` shape so downstream consumers are unaffected | Custom tablespec expectations (cast-to-type, column-pair date order, date-in-current-year, domain-type) have Connect-safe native handlers; GX-dropped results are re-evaluated standalone and fail closed (`gx_executor.py:411-489`).

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Keep GX `add_spark` everywhere | No new code; single execution path | Silently returns wrong answers on Connect/serverless — the platforms production is migrating to | Rejected: defeats the validation contract; the failure is silent |
| Global `is_remote()` flag selecting native vs GX for the whole suite | Simple single branch | Wrong when a classic and a Connect session coexist (the local Sail test lane); violates principle 3 (key off the DataFrame, not a process global) | Rejected: misbehaves with mixed sessions; not engine-correct |
| Convert Connect DataFrames to pandas and run GX pandas engine | Reuses GX semantics | Materializes the full dataset to the driver — defeats the point of validating in-engine; OOMs on real tables | Rejected: not scalable; loses in-engine execution |
| **Per-expectation native executor + classic `add_spark`, routed by DataFrame engine** | Connect-safe; classic path unchanged; same result shape; mixed-session-safe; in-engine | Maintains a second evaluator per baseline expectation type that must stay semantically in parity with GX | **Selected: only option that is correct on Connect, preserves the classic path, and stays engine-correct under mixed sessions** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Compiled GX suites run with correct verdicts on classic Spark, Sail (local Connect), and Databricks serverless; the cross-engine conformance harness can assert parity; no silent false-negatives; downstream consumers (`report.py`, `quality/executor.py`, `table_validator.py`) need no change because the native path emits the identical `ExpectationResult` shape. |
| Negative | The native executor must re-implement each baseline expectation type (`native_executor.py:553-568` dispatch tables) and keep GX-semantic parity (mostly threshold, non-null population, partial-unexpected sampling); adding a new baseline expectation type requires a native evaluator or the native route reports an unsupported expectation as `success=False`. |
| Neutral | The native path materializes only aggregates / small samples (`.count()`, `limit(_SAMPLE_LIMIT)`), not full datasets; the `_reconcile_dropped` re-evaluation runs the native validators even on the classic path when GX collates same-type results. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Native evaluator semantics drift from GX `add_spark` | M | H | Cross-engine conformance harness asserts classic-vs-Connect parity; native result dict mirrors GX BASIC `result_format` (`native_executor.py:46-93`). |
| A baseline expectation type added without a native evaluator fails closed as "unsupported" | M | M | Unsupported types surface an explanatory `observed_value` and `success=False`; the `is_natively_supported()` predicate (`native_executor.py:587-589`) lets callers assert coverage in tests. |
| GX drops same-type custom expectations from its results, masking a real failure | L | H | `_reconcile_dropped` re-evaluates each missing `(type, column)` standalone via the native validators and fails closed when it cannot (`gx_executor.py:411-489`). |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Connect lane (`tests/unit/test_validation_connect_sail.py`) passes every baseline + custom expectation type with verdicts equal to the classic `add_spark` path | A GX upgrade makes `add_spark` Connect-safe, or a new baseline expectation type is added without a native evaluator |
| Conformance harness shows identical suite verdicts across classic Spark / Sail / serverless | Native-vs-GX result divergence detected for any expectation type |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **No concern impact**: This ADR selects an execution-routing strategy within the existing Table Validation subsystem and does not override a library concern practice.

## References

- PRD FR-7.7 (Connect-safe suite execution with per-expectation routing), FR-7.8 (staged raw/ingested execution), FR-20.4 (Connect-safe validation path).
- FEAT-025 (Connect-safe GX validation), FEAT-007 (Table Validation).
- ADR-010 (Spark Connect / serverless runtime model — the platform contract this applies to GX execution), ADR-005 (unified expectation model — Bronze.Raw/Ingested stages).
- `src/tablespec/validation/gx_executor.py:211-409`, `src/tablespec/validation/native_executor.py:1-589`.

## Review Checklist

- [x] Context names a specific problem — not "we need to decide about X"
- [x] Decision statement is actionable — "we will" not "we should consider"
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons, not vague assessments
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation section defines how we'll know if the decision was right
- [x] Review triggers define conditions for reconsidering the decision
- [x] Concern impact section is complete (or explicitly marked as no impact)
- [x] ADR is consistent with governing feature spec and PRD requirements
