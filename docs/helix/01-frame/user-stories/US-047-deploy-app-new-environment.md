---
ddx:
  id: US-047
---

# US-047: Deploy the App into a New Environment

**Feature**: FEAT-034 — App Deployment & Configuration
**PRD Requirements**: FR-23.1, FR-23.2, FR-23.4
**Priority**: P1
**Status**: Specified

## Story

**As an** operator rolling tablespec out to a new Databricks environment,
**I want** to point the guidebook and profiling app at a metadata location I declare,
**So that** I can stand it up without editing application source.

## Context

This story covers the configuration-resolution and deployment-packaging areas of
FEAT-034. It is the portability slice: the same tracked source must serve two
environments that differ only in declared inputs. Provisioning behavior is
US-048; startup diagnostics are US-049.

## Walkthrough

1. Operator declares the metadata catalog, metadata schema, output volume, and
   compute for the target environment as deployment inputs.
2. Operator deploys the application without modifying tracked source.
3. System resolves each setting through the declared precedence — deployment
   inputs over the connection registry over built-in defaults.
4. Application starts and displays the metadata location it resolved.
5. Operator repeats steps 1–2 against a second environment with different
   inputs and both deployments run side by side against their own locations.

## Acceptance Criteria

- [ ] **US-047-AC1** — Given deployment inputs naming a catalog, schema, volume, and compute, when the app is deployed, then it reads and writes metadata only at the declared location.
- [ ] **US-047-AC2** — Given two deployments targeting different environments, when both are deployed from the same commit, then the tracked application source is byte-identical between them and only declared inputs differ.
- [ ] **US-047-AC3** — Given a setting supplied both as a deployment input and in the connection registry, when the app resolves configuration, then the deployment input wins.
- [ ] **US-047-AC4** — Given a setting absent from both deployment inputs and the connection registry, when the app resolves configuration, then the built-in default is used and the resolved value is reported.
- [ ] **US-047-AC5** — Given a search of tracked application source for environment-identifying literals (catalog, schema, volume, compute identifier, workspace URL), when the search runs, then it returns no matches.
- [ ] **US-047-AC6** — Given a running deployment, when the operator views the app, then the resolved metadata location is displayed without opening source or configuration files.

## Edge Cases

- **only some inputs supplied**: unsupplied settings fall through the precedence chain rather than failing the deployment.
- **connection registry names a catalog the deployment input overrides**: the registry entry is ignored for that setting and no warning is required.
- **second deployment against the same metadata location**: permitted; both deployments operate on the same governance tables.

## Test Scenarios

- Deploy to environment A, then to environment B with different inputs; assert both resolve their own locations and the source diff between deployments is empty.
- Assert precedence by supplying a conflicting value in each source and checking the resolved value.
- Grep tracked application source for known environment literals; assert zero matches.
