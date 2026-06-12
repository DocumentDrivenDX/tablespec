---
ddx:
  id: deployment-checklist
---

# Deployment Checklist: tablespec

**Version**: 1.0
**Status**: Backfilled from CI/CD configuration
**Last Updated**: 2026-03-15

## Release Process

tablespec is distributed as a Python package via a GitHub Pages PyPI-compatible index.

### Prerequisites

- All CI checks pass (lint, type-check, tests, coverage)
- Version tag follows semver: `v*.*.*`
- Pre-release tags may include `rc`, `alpha`, `beta` suffixes

### Automated Pipeline (`.github/workflows/release.yml`)

Triggered by pushing a version tag (`v*.*.*`):

1. **Build** - `uv build` produces wheel and sdist in `dist/`
2. **Release** - Creates GitHub Release with artifacts and installation instructions
3. **Build Index** - Generates PEP 503 simple index with SHA256 hashes
4. **Deploy Pages** - Publishes index to GitHub Pages at `https://documentdrivendx.github.io/tablespec/simple/`
5. **Verify** - Waits 60s for propagation, then verifies `pip install` from the index

### Post-Release Verification

```bash
pip install tablespec --index-url https://documentdrivendx.github.io/tablespec/simple/
python -c "import tablespec; print(tablespec.__version__)"
```

### Rollback

- Delete the GitHub Release and tag
- Redeploy the previous version's GitHub Pages index

## CI Pipelines

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `test.yml` | push/PR to main | Coverage pipeline with Codecov |
| `pre-commit.yml` | push/PR to main | Code quality (ruff, pyright) |
| `release.yml` | version tag push | Build, release, deploy to GitHub Pages |

## Future: PyPI Distribution

The long-term plan is to publish tablespec to PyPI as the primary distribution channel. GitHub Pages serving a PEP 503 simple index is the interim distribution mechanism. Once PyPI publication is established, the GitHub Pages index may be retained as a secondary mirror or deprecated.
