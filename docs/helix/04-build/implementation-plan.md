---
ddx:
  id: implementation-plan
---

# Implementation Plan: tablespec

**Version**: 2.0
**Status**: Updated for post-merge codebase
**Last Updated**: 2026-03-16

**Requirements**: [../01-frame/prd.md](../01-frame/prd.md)
**Architecture**: [../02-design/architecture.md](../02-design/architecture.md)
**Test Plan**: [../03-test/test-plan.md](../03-test/test-plan.md)

## Build Tooling

- **Package manager**: uv
- **Build system**: Hatchling with uv-dynamic-versioning
- **Formatter**: Ruff (opinionated, no config)
- **Linter**: Ruff with autofix
- **Type checker**: Pyright (basic mode, src/ only)
- **Pre-commit**: ruff-format, ruff check, pyright, pytest

## Development Workflow

```bash
make install-dev    # Install with dev dependencies
make check          # Run canonical tracked-file lint + type-check + tests
make format         # Format code with ruff
```

## Artifact Handoff Validation

The development pipeline has a separate artifact-handoff check from the runtime
itself:

```bash
uv build
uv run pytest tests/e2e/test_bootstrap_from_specs.py -k compile_persists_every_seam
```

`uv build` produces the installable wheel/sdist, and the `test_bootstrap_from_specs`
contract validates the JSON pipeline artifacts expected by production: the
serialized `manifest.json`, the compiled `validation/*.suite.json` files, and the
rest of the pinned artifact tree that `CompiledArtifacts.load()` resolves from disk.

## Quality Gates

All of the following must pass before merge:
1. `ruff format` - No formatting changes
2. `make lint` - Ruff passes on tracked `src/` and `scripts/` Python files only
3. `make type-check` - Pyright passes with the minimized `pyrightconfig.json` ignore list for remaining legacy/optional modules
4. `make test` - Pytest passes on tracked test modules, excluding only golden `.expected.py` fixtures
5. CI: GitHub Actions coverage pipeline

## Module Implementation Order (Historical)

### Phase 1: Original Codebase
1. `models/umf.py` - Core Pydantic models
2. `type_mappings.py` - Type conversion hub
3. `schemas/generators.py` - Schema generation (SQL, PySpark, JSON)
4. `gx_baseline.py` - GX baseline expectations
5. `gx_constraint_extractor.py` - GX constraint extraction
6. `gx_schema_validator.py` - GX schema validation
7. `profiling/` - Profiling mappers
8. `prompts/` - LLM prompt generators
9. `validation/` - Table and UMF validation
10. `umf_validator.py` - UMF file validation

### Phase 2: Post-Merge Additions (~50 new source files)
11. `naming.py` - Naming utilities (to_spark_identifier, position_sort_key)
12. `date_formats.py` - Date format definitions and conversion
13. `formatting/` - YAML formatter package (ruamel.yaml-based)
14. `umf_loader.py` - Split/JSON format loading with auto-detection
15. `umf_diff.py` - UMF version comparison
16. `umf_change_applier.py` - Atomic change application
17. `excel_converter.py` - Excel bidirectional conversion
18. `excel_import_git.py` - Git-integrated Excel import
19. `changelog_generator.py`, `changelog_diff_parser.py`, `changelog_formatter.py` - Git changelog
20. `models/changelog.py` - Changelog models
21. `inference/domain_types.py` - Domain type registry and inference
22. `sample_data/` - Sample data generation package (12 modules)
23. `quality/` - Quality baseline package (4 modules)
24. `merge.py` - Spark-based table merge
25. `sync_baseline.py` - Baseline synchronization
26. `dependency_resolver.py` - Pipeline dependency resolution
27. `cli.py` - Typer CLI
28. `validator.py`, `completeness_validator.py`, `relationship_validator.py`, `naming_validator.py` - Extended validators
29. `casting_utils.py`, `format_utils.py`, `output_formatting.py` - Utility modules
30. `spark_factory.py` - Spark session factory
31. `gx_wrapper.py` - GX wrapper utilities
32. `survivorship_display.py` - Survivorship display

## Build Dependencies

### Core
- pydantic, pyyaml

### Extended (included by default)
- typer, rich (CLI)
- openpyxl (Excel)
- ruamel.yaml (split-format, formatting)
- gitpython (changelog)

### Optional
- `[spark]`: pyspark (profiling, validation, quality, merge)

## Adding New Functionality

See `CONTRIBUTING.md` for step-by-step guides:
- Adding a new UMF field
- Adding a new schema generator
- Adding a new type mapping
- Working with Great Expectations
- Adding Spark-dependent features
