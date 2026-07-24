---
ddx:
  id: US-049
---

# US-049: Diagnose a Misconfigured Deployment

**Feature**: FEAT-034 — App Deployment & Configuration
**PRD Requirements**: FR-23.5, FR-23.6
**Priority**: P1
**Status**: Built

## Story

**As an** operator whose deployment is not working,
**I want** the app to tell me at startup which setting is wrong and what grant it needs,
**So that** I can fix it directly instead of interpreting a stack trace mid-session.

## Context

This story covers the diagnostics-and-degradation area of FEAT-034. It exists
because configuration faults previously surfaced on first user action — a user
clicked a tab and received a driver traceback naming neither the setting nor the
remedy. Resolution precedence is US-047; object creation is US-048.

## Walkthrough

1. Operator deploys with a setting that is wrong or an identity that lacks a
   grant.
2. System validates the resolved configuration at startup: compute reachable,
   and metadata catalog, schema, and volume present and readable.
3. System reports one message naming the offending setting and the resource or
   grant required.
4. Operator applies the named fix and restarts; validation passes.
5. Operator leaves an optional link unset; the dependent control is hidden and
   every other surface continues to work.

## Acceptance Criteria

- [x] **US-049-AC1** — Given a resolved configuration whose compute is unreachable by the running identity, when the app starts, then it reports one message naming that compute and the grant required, and does not present surfaces that depend on it as usable.
  **Evidence**: `apps/data-profiling/tests/test_diagnostics.py` (`@covers US-049-AC1`).
- [x] **US-049-AC2** — Given a declared metadata schema that does not exist or is unreadable by the running identity, when the app starts, then startup validation fails naming the schema and the access required.
  **Evidence**: `test_diagnostics.py` (`@covers US-049-AC2`).
- [x] **US-049-AC3** — Given a valid configuration, when the app starts, then startup validation passes and adds no more than 2 seconds to start time.
  **Evidence**: mock runtime path returns immediately; `test_fr23_stack.py` (`@covers US-049-AC3`).
- [x] **US-049-AC4** — Given an unset optional setting (dashboard link, conversational-analytics space, or pre-generated specification volume), when the app starts, then only the dependent surface is hidden or disabled and no error is raised elsewhere.
  **Evidence**: `test_diagnostics.py` optionals disabled (`@covers US-049-AC4`); streamlit hides dashboard when unset.
- [x] **US-049-AC5** — Given any startup validation failure, when the message is produced, then it names a specific setting rather than reporting an unqualified error.
  **Evidence**: `ConfigFault.message` / diagnostics tests (`@covers US-049-AC5`).
- [x] **US-049-AC6** — Given a configuration fault, when a user interacts with the app, then the fault has already been reported at startup rather than first appearing as a runtime error during that interaction.
  **Evidence**: streamlit `_startup_faults` session cache; `test_fr23_stack.py` (`@covers US-049-AC6`).

## Edge Cases

- **compute exists but is stopped**: treated as reachable when the identity may start it; reported as a fault only when the identity is not permitted to use it.
- **metadata schema readable but a governance table missing**: reported as a provisioning gap pointing at US-048, not as a configuration fault.
- **several settings wrong at once**: all detected faults are reported together so the operator fixes them in one pass rather than one restart per fault.
- **optional setting present but invalid** (for example an unreachable link): the dependent surface is disabled with a note; startup still succeeds.

## Test Scenarios

- Deploy with an identity lacking compute access; assert the startup message names the compute and the grant.
- Deploy naming a nonexistent schema; assert the message names the schema.
- Deploy a valid configuration; assert validation passes and measure added start time is under 2 seconds.
- Unset each optional setting in turn; assert only its surface is hidden and other surfaces still function.
- Introduce two faults at once; assert both are reported in a single startup message.
