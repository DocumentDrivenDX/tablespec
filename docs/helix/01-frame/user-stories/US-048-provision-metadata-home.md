---
ddx:
  id: US-048
---

# US-048: Provision the Metadata Home on First Deploy

**Feature**: FEAT-034 — App Deployment & Configuration
**PRD Requirements**: FR-23.2, FR-23.3
**Priority**: P1
**Status**: Specified

## Story

**As an** operator standing tablespec up in an empty environment,
**I want** the deployment to create the schema, volume, and governance tables it needs,
**So that** the app works on first deploy without hand-run SQL.

## Context

This story covers the provisioning area of FEAT-034. It is the "empty
environment" slice: everything the app writes must be created or verified by an
explicit, repeatable step. Where the app reads its settings from is US-047;
reporting an unusable configuration is US-049.

## Walkthrough

1. Operator declares a metadata location whose schema and volume do not yet
   exist.
2. Operator runs the provisioning step.
3. System creates the schema, creates the output volume, and creates every
   governance table at the declared location.
4. System reports which objects it created and which already existed.
5. Operator re-runs provisioning; system reports zero changes and succeeds.

## Acceptance Criteria

- [ ] **US-048-AC1** — Given a declared location whose schema does not exist, when provisioning runs, then the schema is created and reported as created.
- [ ] **US-048-AC2** — Given a declared location whose schema exists but whose output volume does not, when provisioning runs, then the volume is created and the existing schema is left unmodified.
- [ ] **US-048-AC3** — Given a provisioned location, when provisioning runs a second time, then no object is created or altered and the step completes successfully.
- [ ] **US-048-AC4** — Given a governance table that exists with an older column set, when provisioning runs, then the missing columns are added and every pre-existing row is retained.
- [ ] **US-048-AC5** — Given a completed provisioning run, when the app starts, then it reads and writes its governance tables with no manually executed SQL having been required.
- [ ] **US-048-AC6** — Given a deploying identity that cannot issue a required grant, when provisioning runs, then it reports the exact grant needed and the identity that needs it, and does not report success.

## Edge Cases

- **declared catalog does not exist**: provisioning stops and reports it, because creating a catalog is outside this feature's authority.
- **partial provisioning interrupted**: a re-run completes the remaining objects without duplicating those already created.
- **governance table exists with an unexpected extra column**: the extra column is left in place and reported, not dropped.

## Test Scenarios

- Provision an empty schema; assert schema, volume, and every governance table exist afterward.
- Re-run provisioning; assert a zero-change report and a success exit.
- Drop a column from one governance table, re-provision, and assert the column returns while existing rows survive.
- Run provisioning as an identity lacking grant authority; assert the required grant is named and the run does not report success.
