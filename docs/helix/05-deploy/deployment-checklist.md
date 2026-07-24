---
ddx:
  id: deployment-checklist
---

# Deployment Checklist: tablespec

**Version**: 2.2
**Status**: Execution-ready template for package+Pages release; app deploy section is the FR-23 operator procedure
**Last Updated**: 2026-07-23

This checklist is the release-day operating template for the current tag-driven
package workflow and the GitHub Pages package index, plus the procedure for
deploying the first-party Databricks App. Keep package/Pages steps aligned
with `.github/workflows/release.yml` and `.github/workflows/publish-microsite.yml`.
App steps implement FR-23 / FEAT-034 / ADR-019; the product microsite Getting
Started pages are the human-facing walkthrough of the same procedure.

## release_scope

### In scope

- Tag-triggered release for semver tags matching `v*.*.*`.
- Package build with `uv build` producing the wheel and sdist under `dist/`.
- GitHub Release publication for the tagged commit.
- GitHub Pages publication of the microsite plus the preserved `/simple/`
  package index.
- Post-deploy install verification from
  `https://documentdrivendx.github.io/tablespec/simple/`.
- Deploy the guidebook + profiling Databricks App into a target workspace using
  only declared inputs (FR-23); see microsite Getting Started → Deploy the app.

### Out of scope

- Runtime behavior changes unrelated to the release tag.
- New packaging channels or a PyPI-primary rollout.
- Docs-only deploys that do not preserve the package index.
- Untracked hotfixes, release branches, or version bumps outside the tag.
- General-purpose SaaS multi-tenant hosting (not a product surface).

### Release inputs

- The release tag exists and matches `v*.*.*`.
- CI for the tagged commit is green.
- `uv build` produces exactly one wheel and one sdist for the tagged version.
- Pages artifact inspection confirms these files exist:
  - `pages/index.html`
  - `pages/simple/index.html`
  - `pages/simple/tablespec/index.html`

## rollout_plan

1. Freeze the candidate at the release tag.
2. Build the distribution artifacts with `uv build`.
3. Publish the GitHub Release from the tagged commit.
4. Build the microsite with `hugo --gc --minify`.
5. Generate the combined Pages artifact with
   `scripts/build_pages_artifact.py --include-github-releases`.
6. Verify the Pages artifact contains the three required HTML entry points.
7. Deploy the Pages artifact to GitHub Pages.
8. Wait 60 seconds for propagation.
9. Verify installability with:
   `pip install --index-url https://documentdrivendx.github.io/tablespec/simple/ tablespec==$VERSION`
10. Confirm the installed package reports the tagged version.

### Success thresholds

- Build step exits zero.
- Pages artifact inspection exits zero.
- Install verification exits zero for the tagged version.
- One retry is allowed after the 60-second propagation wait if the first install
  attempt fails.
- The release remains go only when all required checks complete in the same
  release run.

## rollback_triggers

- `uv build` fails.
- The build output does not contain both the wheel and the sdist for the tagged
  version.
- The combined Pages artifact is missing any of the required HTML entry points.
- The install verification fails twice, including once after the propagation
  wait.
- The package index resolves a version other than the release tag.
- A critical or security regression is found before the verification step
  finishes.

### Rollback action

1. Stop the release flow.
2. Delete the GitHub Release and the release tag.
3. Redeploy the last known-good tag by rebuilding the Pages artifact from the
   previous release assets.
4. Do not cut a new tag until the previous version installs successfully from
   the Pages index again.

## go_or_no_go_decision

| Owner | Check | Pass rule | Window |
| --- | --- | --- | --- |
| Release owner | Tag and build | The tag matches `v*.*.*` and `uv build` completes with exactly one wheel and one sdist | From tag push through build completion |
| Docs owner | Pages artifact | The microsite build succeeds and `pages/index.html`, `pages/simple/index.html`, and `pages/simple/tablespec/index.html` exist | Before deploy-pages starts |
| CI owner | Install verification | `pip install` from the Pages index succeeds for `tablespec==$VERSION` and reports the tagged version | After the 60-second propagation wait, with one retry allowed |
| Release manager | Final call | No open P0/P1 release blocker remains and every required check above passed in the same run | Before announcing the release |

### Decision rule

- Go when every owner row passes.
- No-go when any row fails, when a required file is missing, or when the tagged
  version cannot be installed from the Pages index within the same release run.

## app_deploy (FR-23 / FEAT-034)

Operating procedure for standing up `apps/data-profiling/` in a target
Databricks environment. Config, provision, and startup fail-fast are
implemented; **local mock smoke** (no workspace) is the automated gate
(`make app-smoke`). Full workspace steps are on the product microsite
(`getting-started/deploy-the-app/`). Do not edit tracked application
source for environment identity.

### App deploy inputs

- Metadata catalog, metadata schema, and output volume (declared triple).
- Warehouse / compute identifier the app identity can use.
- Optional: dashboard URL, Genie space, pre-generated UMF volume (absent-tolerant).
- Deployment-supplied environment variables take precedence over
  `connections.yaml`, which takes precedence over built-in defaults (ADR-019).

### App rollout plan

1. Declare the metadata home and compute for the target environment as
   deployment inputs (never as literals in tracked app source).
2. **Agent smoke (no workspace)** — must exit 0 before claiming FR-23 unit path:
   ```bash
   cd apps/data-profiling
   PROFILER_RUNTIME=mock \
     PROFILER_METADATA_CATALOG=main \
     PROFILER_METADATA_SCHEMA=tablespec_profiler \
     uv run pytest tests/test_fr23_stack.py tests/test_config.py tests/test_provision.py tests/test_diagnostics.py -q
   # or: PROFILER_RUNTIME=mock python scripts/fr23_smoke.py
   ```
3. Run (or re-run) the idempotent provision step against the target warehouse:
   `python scripts/provision.py` (second run is a no-op).
4. Deploy the Databricks App artifact from `apps/data-profiling/`, installing
   `tablespec` as a dependency rather than shipping the full monorepo.
5. Start the app and confirm startup validation: missing warehouse, unreachable
   location, or missing grant surfaces one actionable error naming the setting
   and the grant required.
6. Confirm the UI displays the resolved metadata location without opening source
   files.
7. Open guidebook/profile surfaces against the declared location (see microsite
   Getting Started → Deploy the app; not a default CI step).

### App success thresholds

- Provision re-run exits zero with no destructive changes.
- App process starts only when required configuration is usable.
- Optional integrations unset do not crash the process.
- Grep/test gate: no environment-identifying literals in tracked app source
  (fixtures may use synthetic names).

### App rollback

1. Stop the app deployment for the target environment.
2. Leave the provisioned schema/volume in place unless a deliberate teardown
   is approved (provisioning is additive; teardown is out of band).
3. Do not hot-edit tracked source to retarget; fix inputs or grants instead.
