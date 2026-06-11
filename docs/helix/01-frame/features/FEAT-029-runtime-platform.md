---
ddx:
  id: FEAT-029
---

# Feature Specification: FEAT-029 — Runtime Platform (Capability Probing & Engine-Correct Dispatch)

**Feature ID**: FEAT-029
**Status**: Approved
**Priority**: P0
**Owner**: Data Platform
**Covered PRD Subsystem(s)**: Runtime Platform
**Covered PRD Requirements**: FR-20.1, FR-20.2, FR-20.3 (the first-class serverless/Connect platform posture; its test-evidence tier is provided by FEAT-016 as a meta-feature; FR-20.4 is this contract applied to GX execution, owned by FEAT-025)
**Cross-Subsystem Rationale**: None — single subsystem (Runtime Platform). This
feature *owns* the platform contract that ADR-010 records: per-session
capability probing, the engine-correct functions-dispatch seam, and session
acquisition. The profiling (FEAT-024) and validation (FEAT-025) subsystems
*apply* the contract; their application is governed by their own features.

## Overview

This feature implements PRD FR-20.1 and FR-20.2: detect per-session Spark
capabilities that vary across builds by probing a tiny expression cached per
session, and select the `functions` module / Column engine from the DataFrame
in hand rather than a process-global `is_remote()` flag. It is the
Runtime-Platform contract of ADR-010 — classic Spark and Spark Connect /
Databricks serverless are co-equal runtimes, and no code path may assume a JVM
`SparkContext`. It also owns session acquisition: a single entry point that
reuses an active session or delegates to the Delta-enabled factory.

## Ideal Future State

Any Spark-touching tablespec code path behaves identically on classic Spark in
CI, Sail (local Spark Connect) in the test lane, and Databricks serverless in
production. An engineer never branches on "am I on Connect?" — they ask the
session what it can do (`get_capabilities`) and build expressions with the
functions module that matches the DataFrame they hold. When a classic JVM
session and a Connect session coexist in one process, each DataFrame's
expressions run against its own engine, with no
`'Column' object is not callable` surprises. Obtaining a session is one call
that does the right thing locally (Delta-enabled local session) and on
Databricks (reuse the runtime's session, never fight it).

## Problem Statement

- **Current situation (pre-contract)**: Spark-dependent code assumed a classic
  JVM `SparkContext` and called `pyspark.sql.functions` globals directly;
  `pyspark.sql.functions` auto-dispatches on process-global remote state, not
  on the DataFrame (`src/tablespec/profiling/native_profiler.py:61-76`).
- **Pain points**: On Spark Connect builds, capabilities differ per build (e.g.
  `try_to_timestamp(col, fmt)` works on classic Spark 4.0 but not on some
  Connect builds — `src/tablespec/session.py:26-31`), and when classic and
  Connect sessions coexist (the Sail test lane) the global functions module
  yields classic `Column` objects that fail inside a Connect plan. Failures
  were silent or cryptic, not actionable.
- **Desired outcome**: One probing seam and one dispatch seam that every
  Spark-touching subsystem consumes, so behavior tracks the actual session
  build — verified by the Sail coexistence lanes and the capability-cache
  unit tests.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Capability probing | "Does *this* session support this expression?" | Probe a tiny expression once per session, cache by session identity, expose flags consumers gate fallbacks on |
| Engine-correct dispatch | "Which `functions` module is correct for this DataFrame?" | Provide the single `_functions_for` seam that resolves classic vs. Connect from the DataFrame's own type |
| Session acquisition | "Give me a working session anywhere" | Reuse an active session or create one via the factory; on Databricks always reuse the runtime's session |

## Requirements

### Functional Requirements by Area

#### Capability probing (FR-20.1)

CAP-01. `get_capabilities(spark)` SHALL detect capabilities that vary across
Spark builds by evaluating a tiny probe expression against the session
(currently `try_to_timestamp(col, lit(fmt))` over a 1-row DataFrame) and
return capability flags (`src/tablespec/session.py:26-63`).
CAP-02. Probe results SHALL be cached per session, keyed by `id(spark)`: a
cache hit returns without re-probing; a different session re-probes
(`src/tablespec/session.py:54-63`).
CAP-03. A probe failure (any exception) SHALL report the capability as absent
(`False`), never raise (`src/tablespec/session.py:41-44`); consumers gate
Connect-safe fallbacks on the flag, not on the engine name
(`src/tablespec/casting_utils.py:134-136`,
`src/tablespec/validation/native_executor.py:493-496`,
`src/tablespec/validation/custom_gx_expectations.py:74-76`).

#### Engine-correct dispatch (FR-20.2)

FUNC-01. The dispatch seam SHALL select the `functions` module from the
DataFrame's own type — module prefix `pyspark.sql.connect` → Connect
functions, otherwise classic — never from process-global `is_remote()`
(`src/tablespec/profiling/native_profiler.py:61-84`).
FUNC-02. The seam SHALL be the single shared dispatch point for Spark-touching
subsystems: the native profiler and the validation custom-expectation handlers
import the same `_functions_for`
(`src/tablespec/validation/custom_gx_expectations.py:69-73`), so a classic and
a Connect session may coexist in one process with each DataFrame's expressions
resolving session-correctly.

#### Session acquisition

SESS-01. `get_session()` SHALL return the active session when one exists and
otherwise delegate to the factory; `import tablespec.session` SHALL succeed
without PySpark installed (all PySpark imports are lazy,
`src/tablespec/session.py:7-9,66-94`).
SESS-02. On Databricks (detected via environment,
`src/tablespec/spark_factory.py:68-79`) the factory SHALL reuse the runtime's
session — active session first, then `getOrCreate()` honoring `SPARK_REMOTE` —
and never construct a new local session
(`src/tablespec/spark_factory.py:202-233`).
SESS-03. Locally, the factory SHALL produce a Delta-enabled session and verify
the Delta extensions are configured, failing fast with a clear error when they
are not (`src/tablespec/spark_factory.py:235-313,358-378`); when PySpark is
absent it SHALL raise an `ImportError` naming `tablespec[spark]`
(`src/tablespec/spark_factory.py:30-41`).

### Non-Functional Requirements

- **Probe cost**: At most one probe expression per capability per session
  lifetime; a cache hit SHALL perform zero Spark work
  (`src/tablespec/session.py:54-57`). Evidence:
  `uv run pytest tests/unit/test_safe_timestamp.py -k cached`.
- **Mixed-session correctness**: Zero cross-engine `Column` errors when a
  classic and a Connect session coexist. Evidence: the Sail lanes create a
  Connect session without disturbing any active classic session
  (`tests/unit/test_profiler_connect_sail.py:33-65`,
  `tests/unit/test_validation_connect_sail.py:30-61`).
- **Import weight**: `import tablespec.session` SHALL trigger no PySpark
  import at module-import time (`src/tablespec/session.py:7-9`).
- **Compatibility**: A classic DataFrame SHALL resolve to the classic
  functions module unchanged — the contract adds no behavior change on
  classic Spark (`src/tablespec/profiling/native_profiler.py:82-84`).

## User Stories

- [US-037 — Engine-Correct Runtime Dispatch Across Classic and Connect Sessions](../user-stories/US-037-engine-correct-runtime-dispatch.md)

## Edge Cases and Error Handling

- **Connect build lacks `try_to_timestamp(col, fmt)`**: probe returns `False`;
  consumers take the Connect-safe fallback (regex prefilter + format-less
  parse), gated on the flag (`src/tablespec/casting_utils.py:134-136`).
- **Session reconfigured / replaced**: cache is keyed by `id(spark)`; a new
  session object re-probes (ADR-010 risk table).
- **Databricks subprocess with no active session**: factory raises a
  `RuntimeError` advising in-process `pytest.main()` or `SPARK_REMOTE`
  (`src/tablespec/spark_factory.py:227-233`).
- **PySpark not installed**: module imports stay safe; the factory raises an
  actionable `ImportError` at call time (`src/tablespec/spark_factory.py:30-41`).
- **Local session without Delta extensions**: verification fails fast with
  `RuntimeError`, and the broken session is stopped
  (`src/tablespec/spark_factory.py:358-378`).

## Success Metrics

- `get_capabilities` runs exactly one probe per session identity: first call
  probes, second call hits the cache, a different session re-probes
  (`tests/unit/test_safe_timestamp.py:309-342`).
- The Sail coexistence lanes pass end-to-end on a real Connect session:
  `uv run pytest tests/unit/test_profiler_connect_sail.py
  tests/unit/test_validation_connect_sail.py`.
- No process-global engine gate exists in shipped code. Evidence:
  `rg -n "is_remote\(" src/tablespec` matches only the explanatory docstring
  (`src/tablespec/profiling/native_profiler.py:65`).

## Constraints and Assumptions

- The `_functions_for` dispatch seam physically resides in the profiling
  module (`src/tablespec/profiling/native_profiler.py:61-84`) and is imported
  from there by validation
  (`src/tablespec/validation/custom_gx_expectations.py:73`). This feature
  governs the seam as the platform contract; FEAT-024 hosts it.
- The capability set currently carries one flag
  (`try_to_timestamp_with_format`); a newly observed per-build variance
  requires adding a probe here, not an engine-name branch in a consumer
  (ADR-010).
- Sessions are assumed long-lived relative to the `id(spark)`-keyed cache; a
  stopped-and-recreated session is a new object and re-probes.

## Dependencies

- **Other features**: FEAT-024 (native profiler — hosts `_functions_for` and
  is the first consumer), FEAT-025 (applies this contract to GX execution,
  FR-20.4), FEAT-016 (serverless / Sail test-infrastructure tier, FR-20.3),
  FEAT-007 (table validation — consumes `get_session` / `get_capabilities`).
- **External services**: `pyspark` (and its Spark Connect client); Delta Lake
  for local factory sessions; pysail for the local Connect test lane (dev
  group only).
- **PRD requirements**: FR-20.1 (P0), FR-20.2 (P0).

## Out of Scope

- Connect-safe GX validation routing and native expectation evaluation
  (FR-20.4 / FR-7.7) — owned by FEAT-025; it applies this contract.
- The native Spark profiler itself (FR-5.x) — owned by FEAT-024; it applies
  this contract.
- The serverless / Sail test-infrastructure target and engine matrix
  (FR-20.3's evidence tier) — owned by FEAT-016 (US-029).
- Backends other than Spark for `get_session` (`backend="spark"` is the only
  supported value, `src/tablespec/session.py:79-81`).

## Review Checklist

- [x] Covered PRD Subsystem(s) and Requirements (`FR-n`) are listed; single
  subsystem, no cross-subsystem rationale needed
- [x] Functional areas are subordinate parts of this one capability
- [x] Overview connects this feature to specific PRD requirements (FR-20.1/FR-20.2)
- [x] Ideal future state describes the desired user-visible outcome
- [x] Problem statement describes what exists now and what is broken
- [x] Every functional requirement is testable
- [x] Acceptance criteria are defined in US-037, not here (ADR-009)
- [x] Non-functional requirements have specific targets
- [x] Edge cases cover realistic failure scenarios
- [x] Success metrics are specific to this feature
- [x] Dependencies reference real artifact IDs
- [x] Out of scope excludes things someone might reasonably assume are in scope
- [x] No implementation-prescription beyond citing the shipped evidence
- [x] Feature is consistent with governing PRD requirements (ADR-010 / ADR-011)
- [x] No `[NEEDS CLARIFICATION]` markers remain
