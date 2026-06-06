---
ddx:
  id: ADR-010
---

# ADR-010: Spark Connect / Databricks-Serverless Is a First-Class Runtime, Never Assume a JVM SparkContext

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-06 | Accepted | Erik LaBianca | FEAT-007, FEAT-025, ADR-003, ADR-011 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | Databricks serverless and Spark Connect (env-v3, Python 3.12) have no JVM `SparkContext` on the client. Library code that assumes one — PyDeequ profiling, GX `add_spark`, `F.lit`/`F.count` that assert `SparkContext._active_spark_context is not None` — fails silently on Connect, often as a swallowed error that yields wrong results rather than an exception. |
| Current State | Spark-dependent code historically assumed classic Spark. `tablespec.session` now centralizes obtaining a session and probing per-session capabilities (`get_capabilities`, `get_session`, `session.py:47-66`). The native profiler and native GX executor select their `functions` module from the DataFrame in hand (`_functions_for`) instead of a process global. Proven on real Databricks serverless and on the local Sail (Spark Connect) test lane. |
| Requirements | PRD FR-20.1 (per-session capability probing), FR-20.2 (engine-correct functions dispatch), FR-20.3 (first-class serverless / Connect target), FR-20.4 (Connect-safe validation path). Vision: "the same UMF runs first-class on both classic Spark and Databricks serverless / Spark Connect." |
| Decision Drivers | Connect-safe-by-construction (principle 3); the "why now" of the vision — the JVM-bound, library-coupled runtime model is untenable on the platforms teams are migrating to; mixed classic+Connect sessions coexist in the same process during the Sail test lane. |

## Decision

We will treat classic Spark and Spark Connect / Databricks serverless as **co-equal first-class runtimes**, and forbid any code path from assuming a JVM `SparkContext`. Engine-correct behavior is keyed off the DataFrame (or session) in hand, with capabilities probed per session and cached.

**Key Points**: No process-global `is_remote()` gate — dispatch the `functions` module / Column engine from the DataFrame itself (`_functions_for`, FR-20.2) | Capabilities that vary across builds (e.g. `try_to_timestamp` with a format on classic Spark 4.0 vs. some Connect builds) are detected by probing a tiny expression, cached per session (`session.get_capabilities`, FR-20.1) | Mixed sessions are first-class: a classic and a Connect session may coexist (the local Sail test lane), so behavior cannot be selected from a single global flag.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Classic Spark only; treat Connect as unsupported | Simplest; no probing | Contradicts the vision and the platform teams already run on; silent failures on serverless | Rejected: the target market runs on serverless/Connect |
| Single process-global `is_remote()` flag | One branch; easy to read | Wrong when classic and Connect sessions coexist (Sail test lane); a static flag cannot capture per-session capability differences across builds | Rejected: not engine-correct under mixed sessions; misses per-build capability variance |
| Require classic Spark via a runtime shim that forces a local JVM | Reuses classic code paths | Defeats serverless (no JVM available); heavy; not possible on Databricks serverless | Rejected: not feasible on the target platform |
| **Per-session capability probing + DataFrame-keyed engine dispatch; no SparkContext assumption** | Correct on classic and Connect; mixed-session-safe; behavior tracks the actual session build | Each Spark-touching path must select `functions` from the DataFrame and respect probed capabilities | **Selected: only model that is correct on both runtimes and under coexisting sessions** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | The same UMF and the same compiled artifacts execute correctly on classic Spark (CI), Sail (local Connect test lane), and Databricks serverless (production); silent false-results on Connect are eliminated; the cross-engine conformance harness can assert parity. |
| Negative | Every Spark-touching module must obtain its `functions` via `_functions_for(df)` and respect probed capabilities rather than calling classic globals directly; a capability the runtime lacks requires a Connect-safe fallback (e.g. format-less `try_to_timestamp` behind a structural prefilter, `native_executor.py:424-445`). |
| Neutral | A small per-session probe runs once per session (cached by `id(spark)`, `session.py:47-65`); PyDeequ profiling and GX `add_spark` remain available on classic Spark but are no longer assumed available on Connect (see FR-5.5 legacy profiler note). |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| A new Spark path calls a classic global and fails silently on Connect | M | H | Connect-safe-by-construction principle; Sail test lane exercises every path on a real Connect session; `_functions_for` is the single dispatch seam. |
| A probed capability differs between the test-lane Connect build and the Databricks serverless build | M | M | Probe per session and cache per `id(spark)`; fallbacks are gated on the probe result, not on the engine name. |
| Cached capability becomes stale if a session is reconfigured | L | L | Cache keyed by `id(spark)`; a new session re-probes. |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| Conformance harness shows identical results across classic Spark / Sail / Databricks serverless | A path is found that branches on a process-global engine flag, or a silent Connect failure is observed |
| Sail Connect lane passes profiling + validation with verdicts equal to classic Spark | A new Spark build exposes a capability the probe does not cover |

## Supersession

- **Supersedes**: None (extends ADR-003 — the optional-PySpark boundary — with a per-session, Connect-safe execution model).
- **Superseded by**: None

## Concern Impact

- **Practice override**: Establishes the Runtime-Platform contract (PRD subsystem FR-20.x) that all Spark-touching code must follow; downstream ADRs (e.g. ADR-011) apply this contract to specific subsystems. No `concerns.md` library-practice override.

## References

- PRD FR-20.1 / FR-20.2 / FR-20.3 / FR-20.4 (Runtime Platform), FR-7.7 (Connect-safe suite execution).
- FEAT-007 (Table Validation), FEAT-025 (Connect-safe GX validation), ADR-003 (optional PySpark dependency), ADR-011 (Connect-safe GX native-executor routing).
- `src/tablespec/session.py:1-98`, `src/tablespec/profiling/native_profiler.py` (`_functions_for`), `src/tablespec/casting_utils.py` (Connect-awareness).

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
