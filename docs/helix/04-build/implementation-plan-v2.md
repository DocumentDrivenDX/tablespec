---
ddx:
  id: implementation-plan-v2
  kind: build-plan
  informs:
    - prd
    - FEAT-016
    - FEAT-017
    - FEAT-024
    - FEAT-026
---

# Implementation Plan v2: Replacement Note

**Version**: 2.1
**Status**: Replaced by current specs and DDx beads
**Last Updated**: 2026-06-09

**Requirements**: [../01-frame/prd.md](../01-frame/prd.md)
**Architecture**: [../02-design/architecture.md](../02-design/architecture.md)
**Test Plan**: [../03-test/test-plan.md](../03-test/test-plan.md)
**Current Build Plan**: [implementation-plan.md](implementation-plan.md)

## Purpose

This file is retained only as a pointer away from the old March 2026 phase
narrative. Do not use the previous "Design Review Improvements" phase list as an
execution plan. The shipped codebase and governing HELIX specs have moved past
that snapshot, and executable work is now tracked in DDx beads.

## Shipped Evidence

The completed work that used to appear here as future phases is now governed by
the following specs and source/test evidence:

| Area | Current status | Governing artifact | Evidence |
| --- | --- | --- | --- |
| Testing infrastructure | Implemented | [FEAT-016](../01-frame/features/FEAT-016-testing-infrastructure.md) | `tests/conftest.py`, `tests/builders.py`, `tests/strategies.py`, `tests/golden/`, `pyproject.toml` markers |
| Unified expectation model and validation pipeline | Implemented, with remaining consumer-audit work tracked separately | [ADR-005](../02-design/adr/ADR-005-unified-expectation-model.md), [FEAT-017](../01-frame/features/FEAT-017-validation-pipeline.md) | `src/tablespec/models/umf.py`, `src/tablespec/validation/gx_executor.py`, `src/tablespec/validation/native_executor.py`, `tests/unit/test_expectation_suite.py`, `tests/unit/test_validation_connect_sail.py` |
| Native Spark profiling and profile-derived GX expectations | Implemented | [FEAT-024](../01-frame/features/FEAT-024-native-spark-profiler.md) | `src/tablespec/profiling/native_profiler.py`, `src/tablespec/profiling/gx_expectation_builder.py`, `tests/unit/test_native_profiler_key_candidates.py`, `tests/unit/test_profiler_connect_sail.py` |
| Compile orchestrator and bootstrap artifact handoff | Implemented as library/API surface | [FEAT-026](../01-frame/features/FEAT-026-compile-orchestrator-bootstrap.md), [ADR-012](../02-design/adr/ADR-012-compile-orchestrator-runtime-consumes-committed-artifacts.md) | `src/tablespec/e2e/compile.py`, `src/tablespec/e2e/manifest.py`, `src/tablespec/bootstrap.py`, `tests/e2e/test_bootstrap_from_specs.py`, `tests/e2e/test_bootstrap_from_tables.py` |
| Target-agnostic direct SQL, dbt, and LDP emission | Implemented under the PRD multi-target subsystem | [PRD FR-19](../01-frame/prd.md#subsystem-multi-target-emission), [ADR-013](../02-design/adr/ADR-013-target-agnostic-core-seam-sibling-emitters.md) | `src/tablespec/core/`, `src/tablespec/dbt/`, `src/tablespec/ldp/`, `tests/dbt_dag/`, `tests/ldp/` |

## Remaining Work

Do not add planned-work prose to this document. File or update DDx beads instead.
This replacement note intentionally does not snapshot active beads, because that
inventory drifts as work closes. Use `ddx bead ready --json` for the current
execution queue, `ddx bead status --json` for tracker health, and
`ddx bead show <id> --json` for authoritative acceptance criteria.
