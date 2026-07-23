---
ddx:
  id: FEAT-034
  links:
    - ADR-019
    - US-047
    - US-048
    - US-049
---

# Feature Specification: FEAT-034 — App Deployment & Configuration

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-034
**Owner**: Platform / Developer Experience
**Covered PRD Subsystem(s)**: App Deployment & Configuration
**Covered PRD Requirements**: FR-23.1, FR-23.2, FR-23.3, FR-23.4, FR-23.5, FR-23.6
**Cross-Subsystem Rationale**: None — single subsystem.

> **Delivery (2026-07-23).** FR-23 library path is shipped and unit-gated in CI.
> Operator deploy steps for a real workspace are documented on the product
> microsite (`getting-started/deploy-the-app/`), not tracked as open residual work.
>
> | Slice | Status | Evidence |
> |-------|--------|----------|
> | CFG-01..04 config precedence | **Shipped** | `profiler/config.py` + `tests/test_config.py` |
> | PROV-01..04 idempotent provision | **Shipped** | `profiler/provision.py` + `tests/test_provision.py` |
> | PKG-01..03 declared app.yaml inputs | **Shipped** | `apps/data-profiling/app.yaml` env inputs |
> | DIAG-01..04 startup + optionals | **Shipped** | `profiler/diagnostics.py` + `tests/test_diagnostics.py` |
> | Unit whole-stack FR-23 path | **Shipped** | `tests/test_fr23_stack.py` |
> | Operator deploy walkthrough | **Documented** | Microsite Getting Started → Deploy the app |

## Overview

Make the guidebook + profiling application deployable into any Databricks
environment as a configured step of the tablespec process. The metadata location
is a declared input; an explicit provisioning step creates schema/volume/
governance tables; startup validation fails fast with actionable messages —
satisfying FR-23.1–FR-23.6.

## Ideal Future State

An operator standing up tablespec in a new environment declares where metadata
should live — a catalog, a schema, and an output volume — plus the compute the
app should use, and deploys. Provisioning creates the schema, the volume, and
the governance tables, reports what it created, and is safe to re-run. The
application starts, states which environment it is pointed at, and reads and
writes only the declared location. Standing up a second environment is the same
act with different inputs: no source edit, no hand-run SQL, and no reading of
application code to discover where its tables landed.

## Problem Statement

- **Current situation**: The application resolves its metadata home from
  literals compiled into application source and a checked-in connection
  registry that names one catalog. The metadata substrate underneath is already
  location-parameterized, so the binding is accidental rather than structural.
- **Pain points**: Deploying to a second environment requires editing tracked
  source; the target schema, volume, and governance tables must be created by
  hand before the app works; and configuration faults (an unreachable warehouse,
  a missing grant) surface as runtime errors on first user action rather than at
  startup, so the operator debugs a stack trace instead of reading a message.
- **Desired outcome**: One source tree deploys to any workspace by changing
  declared inputs only, provisions its own metadata home idempotently, and
  reports configuration faults at startup with the specific setting and grant
  required.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Configuration resolution | "Where does this deployment read and write metadata?" | Resolve every environment-specific setting through one declared precedence, with no literals in application source |
| Provisioning | "How do I stand this up in an empty environment?" | Create and verify the schema, volume, and governance tables idempotently |
| Deployment packaging | "How do I target a different workspace?" | Expose location and compute settings as declared deployment inputs |
| Diagnostics and degradation | "Why isn't it working, and what do I do about it?" | Validate configuration at startup with actionable messages; disable optional surfaces cleanly |

## Requirements

### Functional Requirements by Area

#### Configuration Resolution

CFG-01. The application must resolve every environment-specific setting —
metadata catalog, metadata schema, output volume, compute, and workspace links —
through one resolution order, with deployment-supplied settings taking
precedence over the checked-in connection registry, which takes precedence over
built-in defaults.

CFG-02. Tracked application source must contain no environment-identifying
literal: no catalog name, schema name, volume name, compute identifier, or
workspace URL.

CFG-03. Every surface that reads metadata, writes metadata, performs volume
I/O, or renders a workspace link must derive its target from the same resolved
configuration, so no two surfaces can disagree about the environment.

CFG-04. Changing a metadata location setting must change where the application
reads and writes without any change to tracked application source.

#### Provisioning

PROV-01. A provisioning step must create the target schema and output volume
when they do not already exist, and verify them when they do.

PROV-02. Provisioning must ensure every governance table exists at the declared
location, creating absent tables and adding absent columns to existing tables
without dropping or rewriting existing rows.

PROV-03. Provisioning must be idempotent: a repeat run against an already
provisioned environment must make no changes and complete successfully.

PROV-04. Provisioning must report which objects it created and which already
existed.

#### Deployment Packaging

PKG-01. The deployment artifacts must expose metadata catalog, metadata schema,
output volume, compute, and optional links as declared inputs.

PKG-02. Targeting a different workspace or environment must require changing
declared inputs only, with no edit to tracked application source.

PKG-03. The deployment artifacts must state which identity the application runs
as and which grants that identity requires on the declared metadata location and
compute.

#### Diagnostics and Degradation

DIAG-01. At startup the application must validate that its resolved
configuration is usable: the compute is reachable, and the metadata catalog,
schema, and volume exist and are readable by the running identity.

DIAG-02. A failed startup validation must produce one message naming the setting
at fault and the resource or grant required to fix it.

DIAG-03. Optional settings — dashboard link, conversational-analytics space, and
pre-generated specification volume — must be absent-tolerant: an unset value
disables or hides only the surface that depends on it, leaving every other
surface working.

DIAG-04. The application must display its resolved metadata location so an
operator can confirm which environment it is pointed at without reading source
or configuration files.

### Non-Functional Requirements

- **Performance**: Configuration resolution plus startup validation must add no
  more than 2 seconds to application start.
- **Reliability**: Provisioning must be idempotent — a repeat run performs zero
  schema changes and returns success.
- **Portability**: Deploying an additional environment must require zero changes
  to tracked application source, measured as zero source-file differences
  between two deployments that target different environments.
- **Security**: No credential and no environment-identifying literal may appear
  in tracked source; credentials are referenced by name only.
- **Observability**: 100% of startup validation failures must name a specific
  setting; none may surface only as an unqualified error.

## User Stories

- [US-047 — Deploy the app into a new environment](../user-stories/US-047-deploy-app-new-environment.md)
- [US-048 — Provision the metadata home on first deploy](../user-stories/US-048-provision-metadata-home.md)
- [US-049 — Diagnose a misconfigured deployment](../user-stories/US-049-diagnose-misconfigured-deployment.md)

## Edge Cases and Error Handling

- **Schema exists, volume missing**: provisioning creates the volume and leaves
  the existing schema untouched.
- **Governance table exists with an older column set**: provisioning adds the
  missing columns and retains existing rows; older rows carry empty values for
  the new columns.
- **Running identity lacks a grant on the declared compute**: startup validation
  fails with a message naming the compute and the grant required.
- **Deploying identity cannot issue the required grant**: provisioning reports
  the exact grant an administrator must apply and which identity needs it,
  rather than failing without direction.
- **Two deployments share one metadata location**: both read and write the same
  governance tables; each recorded run remains attributable to the deployment
  that produced it.
- **Optional link unset**: the dependent control is hidden and no error is
  raised on any other surface.
- **Declared catalog exists but schema does not**: provisioning creates the
  schema; a declared catalog that does not exist is a startup validation failure,
  because creating a catalog is outside this feature's authority.

## Success Metrics

- A deployment into a previously unused environment completes with zero edits to
  tracked application source.
- Zero environment-identifying literals remain in tracked application source.
- First deployment into an empty environment completes with no manually run SQL.
- 100% of configuration faults are reported at startup rather than on first user
  action.
- Re-running provisioning against a provisioned environment reports zero changes.

## Constraints and Assumptions

- The application is deployed from its own subdirectory, so its declared inputs
  travel with that directory rather than with the repository root.
- The application runs as a service principal unless an operator configures
  otherwise; granting that identity access to compute and metadata is an
  operator action outside the application.
- Unity Catalog is the metadata substrate, and catalog / schema / volume is the
  addressing scheme for the metadata home.
- The metadata substrate is already location-parameterized; this feature removes
  the literals and adds provisioning rather than redesigning metadata storage.

## Dependencies

- **Other features**: FEAT-033 (Guidebook — the in-application rendering surface
  that this deployment carries); FEAT-029 (Runtime Platform).
- **External services**: Databricks Apps runtime, Unity Catalog, a SQL warehouse,
  and the deployment bundle tooling.
- **PRD requirements**: FR-23.1, FR-23.2, FR-23.3, FR-23.4, FR-23.5, FR-23.6.

## Out of Scope

- Migrating or relocating metadata that already exists at a previous location —
  this feature configures where new metadata is written, not data movement.
- Escalating privileges: the feature reports the grant required; it never grants
  permissions the deploying identity does not itself hold.
- Per-user or per-tenant isolation of metadata within one environment.
- Deployment targets outside Databricks.
- Changing the governance table schemas themselves, which remain owned by the
  features that write them.
