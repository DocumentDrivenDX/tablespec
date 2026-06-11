---
ddx:
  id: US-037
---

# US-037: Engine-Correct Runtime Dispatch Across Classic and Connect Sessions

**Feature**: FEAT-029 — Runtime Platform (Capability Probing & Engine-Correct Dispatch)
**Feature Requirements**: CAP-01, CAP-02, CAP-03, FUNC-01, FUNC-02, SESS-01, SESS-02
**PRD Requirements**: FR-20.1, FR-20.2
**Priority**: P0
**Status**: Approved

## Story

**As a** data engineer running tablespec on both classic Spark (CI) and Spark
Connect / Databricks serverless (production)
**I want** sessions, capabilities, and column expressions to be resolved from
the session and DataFrame I actually hold
**So that** the same code yields correct results on every runtime — including
when a classic and a Connect session coexist in one process — without my
branching on engine type or paying a re-probe on every call

## Context

`pyspark.sql.functions` dispatches on process-global remote state, so in the
Sail test lane (classic JVM session + Connect session in one process) global
functions yield classic `Column` objects that fail inside a Connect plan with
`'Column' object is not callable`
(`src/tablespec/profiling/native_profiler.py:61-76`). Separately, Spark builds
differ in capability — `try_to_timestamp(col, fmt)` works on classic Spark 4.0
but not on some Connect builds (`src/tablespec/session.py:26-31`) — so
consumers need a probed, cached, per-session answer rather than an engine-name
guess. This story exercises the probing seam (CAP-01..03), the dispatch seam
(FUNC-01/02), and session acquisition (SESS-01/02) end-to-end.

## Walkthrough

1. The engineer calls `get_session()`; the system returns the already-active
   session, or creates one via the factory (on Databricks: reuses the
   runtime's session, honoring `SPARK_REMOTE`).
2. A consumer (e.g. `safe_to_timestamp` with a format) calls
   `get_capabilities(spark)`; the system evaluates the 1-row
   `try_to_timestamp` probe once and caches the flags by session identity.
3. The consumer gates its expression on the flag: capability present → direct
   `try_to_timestamp(col, lit(fmt))`; absent → the Connect-safe regex-prefilter
   fallback.
4. Profiling and validation code build column expressions via
   `_functions_for(df)`, which resolves the Connect functions module for a
   Connect DataFrame and the classic module for a classic DataFrame — even
   with both session kinds alive in the process.
5. Subsequent calls with the same session hit the capability cache (no further
   Spark work); a different session re-probes — the outcome: engine-correct
   behavior everywhere, probed once per session.

## Acceptance Criteria

- [ ] **US-037-AC1** — Given an active Spark session, when
  `get_capabilities(spark)` is called twice, then the probe expression is
  evaluated exactly once and the second call returns the cached flags without
  re-probing; a different session object triggers a fresh probe
  (`tests/unit/test_safe_timestamp.py:309-342`).
- [ ] **US-037-AC2** — Given a classic JVM session and a Connect (Sail)
  session coexisting in one process, when column expressions are built for a
  Connect DataFrame, then the `functions` module is resolved from the
  DataFrame's own session and the plan executes without
  `'Column' object is not callable`
  (`tests/unit/test_profiler_connect_sail.py:33-65,86-128`,
  `tests/unit/test_validation_connect_sail.py:30-61`).
- [ ] **US-037-AC3** — Given a session whose probe reports
  `try_to_timestamp_with_format=True`, when `safe_to_timestamp(col,
  spark_format=..., spark=...)` runs, then it uses `try_to_timestamp` with the
  format directly, with no regex prefilter
  (`tests/unit/test_safe_timestamp.py:206-244`).
- [ ] **US-037-AC4** — Given a session whose probe reports
  `try_to_timestamp_with_format=False`, when the same call runs, then it takes
  the Connect-safe fallback (structural regex prefilter + `to_timestamp`) and
  never calls the format-taking `try_to_timestamp`
  (`tests/unit/test_safe_timestamp.py:246-307`).
- [ ] **US-037-AC5** — Given an active session in the process, when
  `get_session()` is called, then the active session is returned rather than a
  new one being built; with none active, the factory creates one (on
  Databricks: reuse runtime session / `SPARK_REMOTE`, never a new local
  session) (`src/tablespec/session.py:66-94`,
  `src/tablespec/spark_factory.py:202-233`; exercised by the GX test harness,
  `tests/conftest.py:470-473`).

## Edge Cases

- **Probe raises (capability genuinely absent or session broken)**: flag is
  `False`, never an exception (`src/tablespec/session.py:41-44`); consumers
  fall back, they do not crash.
- **Session stopped and recreated**: new object identity → fresh probe; no
  stale capability is reused.
- **`spark=None` passed to a capability-gated consumer**: falls back to
  Column-module detection instead of probing
  (`tests/unit/test_safe_timestamp.py:344-374`).
- **PySpark not installed**: `import tablespec.session` still succeeds;
  session/probe calls require PySpark at call time
  (`src/tablespec/session.py:7-9`).

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Probe cached per session | US-037-AC1 | fresh session, empty cache | `get_capabilities(spark)` twice, then once with a second session | probe count 1 after both calls on session 1; count 2 after session 2 |
| Coexisting sessions | US-037-AC2 | classic session active; Sail Connect session created alongside; 10-row mixed-type Connect `df` | profile / validate the Connect `df` | expressions run on the Connect engine; full profile / verdicts returned, no `Column` error |
| Capability present | US-037-AC3 | probe flag `True`; col value `"2020-01-01"`, format `"yyyy-MM-dd"` | `safe_to_timestamp(col, fmt, spark)` | direct `try_to_timestamp(col, lit(fmt))`, no `rlike` |
| Capability absent | US-037-AC4 | probe flag `False`; same input | `safe_to_timestamp(col, fmt, spark)` | `rlike` prefilter + `to_timestamp`; format-taking `try_to_timestamp` never called |
| Session reuse | US-037-AC5 | an active session exists | `get_session("gx-test-harness")` | the active session object is returned |

## Dependencies

- **Stories**: none upstream; US-021 (FEAT-024) and US-022 (FEAT-025) consume
  this contract.
- **Feature Spec**: FEAT-029
- **Feature Requirements**: CAP-01, CAP-02, CAP-03, FUNC-01, FUNC-02, SESS-01,
  SESS-02
- **PRD Requirements**: FR-20.1, FR-20.2
- **External**: `pyspark` (and its Spark Connect client); pysail for the local
  Connect coexistence lane (dev group).

## Out of Scope

- Connect-safe GX expectation evaluation and routing verdicts (US-022 /
  FEAT-025, FR-20.4).
- Native profiler statistics behavior (US-021 / FEAT-024).
- The Sail / serverless test-infrastructure tier itself (US-029 / FEAT-016,
  FR-20.3).

## Review Checklist

- [x] Stored as its own file `US-037-<slug>.md`
- [x] Covers one persona (data engineer) completing one goal (engine-correct
  runtime behavior across sessions)
- [x] Links to parent FEAT-029 and names PRD FR-20.1 / FR-20.2
- [x] Every acceptance criterion is independently testable with a stable
  `US-037-ACm` ID
- [x] Walkthrough traces trigger → outcome; edge cases documented
- [x] No exact API/CLI surface defined inline beyond citing shipped evidence
