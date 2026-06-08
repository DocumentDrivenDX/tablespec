# Implementation Notes: tablespec-b9dec718

## Scope

Aligned the documentation and Databricks try-it-out instructions with the
installed-artifact production contract:

- production runs from the committed artifact tree plus the published
  `tablespec` wheel
- development bootstrap produces the artifact tree and validates the JSON
  pipeline artifacts
- Databricks notebook instructions distinguish development bootstrap from
  production install/run

## Files Updated

- `README.md`
- `docs/guide/bootstrap.md`
- `docs/helix/02-design/architecture.md`
- `docs/helix/04-build/implementation-plan.md`
- `scripts/run_integration_tests_databricks.ipynb`

## Verification

```bash
uv build
uv run pytest tests/e2e/test_bootstrap_from_specs.py -k compile_persists_every_seam
python3 -m json.tool scripts/run_integration_tests_databricks.ipynb
```

Results:

- `uv build` succeeded and produced the wheel/sdist artifacts in `dist/`
- `tests/e2e/test_bootstrap_from_specs.py::test_compile_persists_every_seam`
  passed
- the Databricks notebook JSON remained valid

## Acceptance Coverage

- AC1: `docs/helix/02-design/architecture.md`, `README.md`, `docs/guide/bootstrap.md`
- AC2: `docs/helix/04-build/implementation-plan.md`
- AC3: `docs/helix/04-build/implementation-plan.md`, `tests/e2e/test_bootstrap_from_specs.py`
- AC4: `docs/guide/bootstrap.md`, `README.md`
- AC5: `scripts/run_integration_tests_databricks.ipynb`
