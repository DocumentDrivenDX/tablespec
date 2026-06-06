---
ddx:
  id: principles
---

# Project Principles

These principles guide judgment calls across all HELIX activities. They are not
requirements, concerns, ADRs, workflow rules, or process enforcement. They are
lenses applied when choosing between two valid options.

This document was bootstrapped from HELIX defaults and then specialized for
tablespec. You own it now — add, modify, reorder, or remove any principle. The
only constraint: principles cannot negate HELIX mechanics (artifact hierarchy,
activity gates, tracker semantics).

## Principles

1. **UMF is the single source of truth.** All schema representations are derived
   from UMF; conversions should be bidirectional where possible. This changes
   decisions when a tool-specific shortcut would create a second place that
   defines a table's truth.

2. **Committed artifacts are the contract.** The compile step turns UMF into
   committed, reviewable runtime artifacts (direct SQL, dbt projects, LDP, GX
   suites); the runtime reads those artifacts and never re-derives from UMF at
   run time. This changes decisions when it would be convenient to have a
   runtime import tablespec or recompute schema on the fly — prefer emitting a
   diffable artifact and consuming it instead.

3. **Connect-safe by construction.** Engine-correct behavior is keyed off the
   DataFrame (or session) in hand, never off a process-global `is_remote()` and
   never on the assumption that a JVM `SparkContext` exists. Capabilities are
   probed per session; functions dispatch is selected from the DataFrame's own
   engine. The canonical hazard is the *silent* one: GX 1.x `add_spark` returns
   `success=False`/`result={}` on Spark Connect instead of raising, so a path
   that "works" on classic Spark can return wrong answers on serverless with no
   error. Where an engine path could fail silently, validation **fails closed** —
   a dropped or unverifiable expectation never reads as a pass. This changes
   decisions when a simpler global flag would work on classic Spark but silently
   misbehave on Spark Connect / Databricks serverless.

4. **Deterministic, lossless outputs.** Compilation (schema generation,
   transforms, baseline expectations) produces identical output for identical
   input, preserving the full information in the UMF. This changes decisions
   when a non-deterministic or lossy shortcut would make committed artifacts
   non-diffable.

5. **Pure Python core, scoped optional dependencies.** The core library
   functions without PySpark. Spark-dependent features (profiling, validation,
   merge) are opt-in via the `[spark]` extra. dbt and pysail are **dev-group /
   test-only** tooling — not user-facing extras — and back the Sail local
   Spark-Connect test lane; user runtimes consume committed dbt/SQL/LDP
   artifacts without importing tablespec or dbt. This changes decisions when a
   convenience import would pull a heavy or runtime-irrelevant dependency into
   the user-facing surface.

6. **Type safety at the boundary.** Pydantic models enforce constraints at
   runtime; invalid schemas fail fast with clear errors. This changes decisions
   when permissive parsing would defer an error to a later, less obvious place.

7. **Healthcare domain awareness.** Per-LOB nullable configuration (MD/MP/ME),
   healthcare-specific validation patterns, and domain-aware relationship
   discovery are first-class concerns. This changes decisions when a generic
   model would lose domain meaning the platform depends on.

8. **Read and write integration.** Great Expectations integration is
   bidirectional: generate expectations from UMF, extract constraints back into
   UMF. This changes decisions when a one-way conversion would strand
   information that should round-trip.

9. **Evidence over assumption.** Profiling data enriches UMF but does not
   override explicit definitions. This changes decisions when inferred values
   and authored values conflict — authored wins.

10. **Spec is the contract.** The governing artifact stack is the source of
    truth; code is a projection of it. Keep traceability bidirectional (no
    material code surface without a governing artifact; no acceptance criterion
    without an exercising test). This changes decisions when code and spec
    diverge — fix the projection or update the contract in the same change,
    rather than letting them drift.

11. **Minimal, focused API.** Each module has a clear responsibility; no
    catch-all utilities. This changes decisions when a generalized helper has no
    current requirement behind it.

## Tension Resolution

When principles pull in opposite directions, document the resolution strategy
here. Each entry should name the two principles, describe when they conflict,
and state how to decide.

- **Committed artifacts are the contract (2) vs. Minimal, focused API (11).**
  Persisting the full committed-artifact set (direct SQL + dbt + LDP + GX)
  multiplies emitters off one UMF, which can look like surface bloat. Resolve in
  favor of (2): each emitter is a sibling on the shared target-agnostic core
  seam, so the breadth lives behind one stable seam rather than ad-hoc helpers.
  Remove a backend only when no committed-artifact consumer needs it.

- **Connect-safe by construction (3) vs. Deterministic, lossless outputs (4).**
  Per-session capability probing means behavior can differ across engines (e.g.
  a timestamp expression available on classic Spark but not a Connect build).
  Resolve by making the *compiled artifact* deterministic and making the
  *executor* select an engine-correct, semantically-equivalent path — never by
  branching the artifact's content on the engine.
