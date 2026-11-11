# tablespec - agent guide

Python library and CLI (`umf-tablespec` on PyPI, import and CLI `tablespec`) that compiles UMF table specs into SQL DDL,
PySpark/JSON schemas, dbt/LDP projects, Great Expectations suites and Excel workbooks. It consumes UMF
([umf-core](https://pypi.org/project/umf-core/)) and never defines UMF semantics.

## Layout

- `src/tablespec/` - the library: flat modules for the CLI, loaders and validators, plus feature subpackages
  (`models/`, `schemas/`, `dbt/`, `ldp/`, `validation/`, `profiling/`, `sample_data/`, `document_loader/`, `guidebook/`, ...).
- `tests/` - unit, conformance, golden (byte-for-byte generator output; do not reformat), integration, e2e, plugin, website.
- `apps/data-profiling/` - Streamlit Databricks App (`app.yaml` + `requirements.txt` at the root deploy it). Its tests run with the library's.
- `skills/tablespec/` + `.claude-plugin/` + `.codex-plugin/` - the published agent-skill plugin. `skills/tablespec/SKILL.md` is
  the source; `.agents/skills` and `.claude/skills` entries are symlinks to it. The three manifests carry a literal
  `version` that must equal the release tag; release.yml checks it, bump them before tagging.
- `docs/` - PRD, features, ADRs, architecture, contracts, guides. `website/` - Hugo/Hextra microsite.
- `.ddx/beads.jsonl` - the issue tracker; commit subjects cite bead ids like `[tablespec-xxxxxxxx]`.

## Commands

```bash
uv sync --all-extras --group dev
uv run pytest -n auto --dist loadfile -m "not slow and not spark_only and not databricks_e2e" \
  --ignore=tests/dbt_dag --ignore=tests/dbt_roadmap --ignore=tests/ingest_parity --ignore=tests/e2e   # what PR CI runs
uv run pytest -n 2 --dist loadfile -m "not databricks_e2e"                                              # full suite (nightly)
uvx --from ruff==0.13.3 ruff check . && uvx --from ruff==0.13.3 ruff format --check .
```

Spark tests start a local JVM per xdist worker (about 2 GB each); use Java 17 and `-n 2` for the full suite.
Mark tests slower than about 5 s `@pytest.mark.slow`; mark JVM-backed ones `spark_only`.

## Conventions

- Python 3.11+, ruff for lint and format, type hints on public API, pydantic models for UMF documents.
- Keep the runtime free of dbt imports (`tests/test_core_encapsulation.py`). dbt is a test-only dependency.
- Add a test with every behaviour change. Never weaken or delete a product test to get CI green; xfail or skip with a reason.
- Generator output changes need golden files regenerated and reviewed.

## CI and releases

- `.github/workflows/ci.yml`: lint, fast suite (PR/push), nightly full suite. `pages.yml`: microsite. `release.yml`: on a `vX.Y.Z` tag,
  tests, builds, smoke-installs the wheel, publishes to PyPI (trusted publishing) and creates the GitHub Release.
- Release: bump the three plugin manifests to the new version, update `CHANGELOG.md`, tag `vX.Y.Z`. The package version
  comes from the tag (uv-dynamic-versioning). `workflow_dispatch` of release.yml is a dry run that never publishes.
- Do not commit run output, receipts, qualification packets or generated evidence. CI artifacts are uploaded, not tracked.
