---
ddx:
  id: deployment-checklist
---

# Deployment Checklist: tablespec

**Version**: 2.0
**Status**: Execution-ready template for the next release
**Last Updated**: 2026-06-12

This checklist is the release-day operating template for the current tag-driven
package workflow and the GitHub Pages package index. Keep it aligned with
`.github/workflows/release.yml` and `.github/workflows/publish-microsite.yml`.

## release_scope

### In scope

- Tag-triggered release for semver tags matching `v*.*.*`.
- Package build with `uv build` producing the wheel and sdist under `dist/`.
- GitHub Release publication for the tagged commit.
- GitHub Pages publication of the microsite plus the preserved `/simple/`
  package index.
- Post-deploy install verification from
  `https://documentdrivendx.github.io/tablespec/simple/`.

### Out of scope

- Runtime behavior changes.
- New packaging channels or a PyPI-primary rollout.
- Docs-only deploys that do not preserve the package index.
- Untracked hotfixes, release branches, or version bumps outside the tag.

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
