---
ddx:
  id: ADR-019
---

# ADR-019: App Configuration Precedence and Provisioning Authority

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-07-12 | Proposed | Gary Fischer | FEAT-034, ADR-013 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The guidebook + profiling application must deploy into any Databricks environment as a step of the tablespec process. Two architecture-significant questions had to be settled: (1) **where configuration authority lives** — how the application learns which catalog, schema, volume, and compute it owns, and which source wins when they disagree; and (2) **what the application is allowed to create** — whether it may bring its own metadata home into existence, and what it must do when it lacks the rights to do so. |
| Current State | The metadata substrate is already location-parameterized (`delta_repo.ensure_tables(catalog, schema)`, `VolumeRef(catalog, schema, volume)`), but the application binds itself to one workspace through literals in application source and a checked-in connection registry naming a single catalog. Standing the app up in its current environment required hand-run `CREATE SCHEMA`, `CREATE VOLUME`, and `GRANT` statements, and a missing grant on compute surfaced as a driver traceback on a user's first click rather than at startup. |
| Requirements | FEAT-034; PRD FR-23.1–FR-23.6. |
| Decision Drivers | One source tree must serve many environments; the active `unity-catalog` concern already forbids hardcoded catalogs in emitted artifacts and the same principle should hold for the application; a first deploy into an empty environment must not depend on undocumented manual SQL; and an operator who cannot grant permissions must be told exactly what to ask for rather than reading a stack trace. |

## Decision

1. **Configuration resolves through one declared precedence, into one object.**
   Deployment-supplied settings win over the checked-in connection registry,
   which wins over built-in defaults. Every surface — metadata reads, metadata
   writes, volume I/O, and workspace links — derives from that single resolved
   object, so no two surfaces can disagree about the environment.
2. **The metadata home is a declared address, never a discovered one.** The
   application is told its `(catalog, schema, volume)`; it does not infer the
   location by scanning for a naming convention. An address the operator
   declared is auditable; an address the app guessed is a silent write to
   someone else's schema.
3. **Provisioning is an explicit, idempotent, additive deployment step.** A
   named step creates or verifies the schema, the volume, and the governance
   tables and reports what it created. It adds absent tables and absent columns;
   it never drops or rewrites existing data. It is not lazy creation on first
   write.
4. **The application validates at startup and reports grants; it never
   escalates.** Resolved configuration is checked before the app presents a
   usable surface. When the running identity lacks a required grant, the app
   names the resource and the grant an administrator must apply. It does not
   attempt to acquire privileges the deploying identity does not hold.

**Key Points**: deployment inputs beat checked-in config | declared address, not discovered | additive idempotent provisioning | fail fast, report the grant, never escalate

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Per-environment source (status quo) | Nothing to build; each deployment is self-evident | Source diverges per environment; every new workspace is a tracked-source edit; the literal set must be found by reading code | **Rejected**: makes environments a source-control problem and is the failure this feature exists to remove |
| Discover the metadata home by convention at runtime | Zero configuration for the happy path | Ambiguous when several candidates match; a wrong guess writes governance data into someone else's schema; the authority for the choice is invisible to reviewers | **Rejected**: silent, unauditable writes are a worse failure than a missing setting |
| Checked-in per-environment config files | Versioned and reviewable; no runtime guessing | Puts workspace identity into tracked source; N environments means N committed files carrying another team's catalog names | **Rejected**: relocates the literals rather than removing them |
| Lazy auto-create on first write | No extra deployment step | Failure appears on a user's first action, not at deploy; a mistyped schema is created rather than rejected | **Rejected** (provisioning axis): defers discovery of misconfiguration to the least useful moment |
| **Deployment-input precedence + registry fallback, with an explicit idempotent provisioning step** | Environment values travel with the deployment, not the source; local and default runs still work through the registry; provisioning is deterministic, reviewable, and re-runnable; faults are named at startup | Two configuration sources to reason about; the provisioning step must be wired into the deployment path | **Selected**: it removes the literals without moving them, and it makes both creation and failure explicit |

## Consequences

| Type | Impact |
|------|--------|
| Positive | One source tree deploys to any environment by changing declared inputs; a first deploy into an empty environment needs no hand-run SQL; configuration faults are named at startup with the grant required; the `unity-catalog` "no hardcoded catalogs" practice now holds for the application as well as emitted artifacts |
| Negative | Two configuration sources must be documented and their order understood; the provisioning step is an additional deployment obligation; additive-only migration means removing an obsolete governance column is an out-of-band operation |
| Neutral | Local and mock development continue to work through registry values and built-in defaults; sharing one metadata home between two deployments remains permitted rather than prevented |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| The deploying identity cannot issue a required grant | H | M | Provisioning reports the exact grant and the identity needing it and does not report success; the app names the same grant at startup. Observed in practice: the app's service principal could not be granted compute access by the deployer |
| Two deployments share one metadata home and confuse run attribution | M | M | Sharing is permitted by design; each recorded run stays attributable to the deployment that produced it |
| Additive-only migration drifts from the current model (an obsolete column lingers) | M | L | Provisioning reports extra and missing columns rather than silently reconciling; removal is a deliberate migration |
| A default value silently masks a missing setting | M | M | The resolved location is displayed by the app, and the resolution source is reported, so a default is visible rather than assumed |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| A second environment deploys with zero tracked-source differences | Any environment that requires editing tracked application source |
| Zero environment-identifying literals remain in tracked application source | A literal reappears in application source |
| 100% of configuration faults are reported at startup | A configuration fault first observed during a user action |
| Re-running provisioning reports zero changes | A repeat provisioning run alters an object |

## Supersession

- **Supersedes**: None
- **Superseded by**: None

## Concern Impact

- **Concern selection**: This ADR constrains the active `unity-catalog` concern.
  Its recorded practice — *"no hardcoded catalogs in emitted artifacts"* — is
  extended here from emitted artifacts to the application itself: the app
  addresses Unity Catalog through a declared three-part location on the same
  principle.
- **Practice override**: None. This decision tightens an existing practice
  rather than overriding one.
- **Concern drift surfaced (not resolved here)**: `concerns.md` predates the
  data-profiling application entering this repository and no longer describes
  it. Two slot records are now inaccurate: `deploy-target` records *"Python
  package plus GitHub Pages docs/package index"* and does not include a
  Databricks App; `frontend-framework` records that *"the product remains a
  non-UI library"* and that the framework applies *"for that site only"*, which
  the Streamlit operational UI contradicts. `e2e-framework` likewise has no
  coverage story for that UI. Correcting the slot table is a concern-selection
  act reserved for a Frame pass and is deliberately **not** performed by this
  ADR; it is recorded here so the gap is visible.

## References

- PRD — Subsystem: App Deployment & Configuration (FR-23.1–FR-23.6)
- [FEAT-034 — App Deployment & Configuration](../../01-frame/features/FEAT-034-app-deployment-configuration.md)
- [US-047](../../01-frame/user-stories/US-047-deploy-app-new-environment.md), [US-048](../../01-frame/user-stories/US-048-provision-metadata-home.md), [US-049](../../01-frame/user-stories/US-049-diagnose-misconfigured-deployment.md)
- [ADR-013 — Target-agnostic core seam and sibling emitters](ADR-013-target-agnostic-core-seam-sibling-emitters.md)
- `concerns.md` — active `unity-catalog` concern
