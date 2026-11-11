# Releasing tablespec

1. Bump the three plugin manifests (`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`,
   `.claude-plugin/marketplace.json`) to the new version and add a section to `CHANGELOG.md`.
2. Merge to `main`, then push a tag `vX.Y.Z`. The package version comes from the tag (uv-dynamic-versioning).
3. `.github/workflows/release.yml` runs the lint and fast suites, builds the wheel and sdist, checks the plugin manifests
   against the tag, smoke-installs the wheel in a fresh venv and runs the README quickstart, runs the shared-UMF/conformance/golden
   tests against the latest `umf-core` in range, publishes to PyPI with trusted publishing (environment `pypi`) and creates the
   GitHub Release with `SHA256SUMS` and a build-provenance attestation.
4. Publishing the release triggers `.github/workflows/pages.yml`, which rebuilds the microsite stamped with the tag.

A manual dispatch of `release.yml` is a dry run: it builds and smoke-tests and never publishes.
PyPI trusted publisher: project `umf-tablespec`, repository `DocumentDrivenDX/tablespec`, workflow `release.yml`, environment `pypi`.
