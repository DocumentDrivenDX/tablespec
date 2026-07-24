# Development

## Setup

```bash
# Clone repository
git clone <repository-url>
cd tablespec

# Install with development dependencies
uv sync --all-extras

# Install with Spark support
uv sync --extra spark
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/tablespec --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_gx_baseline.py
```

## Product microsite (Playwright)

The Hugo microsite under `website/` has two Playwright suites:

| Suite | Command | What it proves |
|-------|---------|----------------|
| Content | `make website-test-content` | Navigation, screenshots, key page copy (`e2e/microsite.spec.ts`) |
| Links | `make website-test-links` | Crawl every internal link under production base path `/tablespec/` and check required content (`e2e/link-check.spec.ts`) |
| Both | `make website-test` | Content then links |

First-time setup (Hugo extended + Node required):

```bash
make website-install   # npm ci + Chromium
make website-test      # or: cd website && npm run test:all
```

From `website/` directly:

```bash
npm ci
npm run install:browsers   # local; use install:browsers:ci in CI
npm run test:content
npm run test:links
```

The link suite serves Hugo with `--baseURL http://127.0.0.1:1314/tablespec/` so
root-absolute hrefs that drop the project path fail the same way they do on
GitHub Pages. CI runs both suites in `.github/workflows/microsite.yml` and as a
pre-deploy gate in `publish-microsite.yml`.

### App smoke (no workspace)

```bash
make app-smoke   # FR-23 mock config/provision/diagnostics stack
```

### Link convention (do not work around baseURL)

Site lives under `/tablespec/`. Prefer root-absolute site paths in content:

```markdown
{{< card link="/demos/" title="Demos" >}}
[Getting Started](/getting-started/)
```

Shortcodes resolve those through `website/layouts/_partials/utils/site-href.html`
(Hextra overrides under `website/layouts/`). Do not use `../section/` relative
card links to paper over missing baseURL handling — fix the shortcode via
`site-href` instead. See `website/README.md`.

## Project Structure

```
src/tablespec/
├── __init__.py                  # Public API exports
├── cli.py                       # Typer CLI (validate, info, convert, excel, domains)
├── models/
│   ├── umf.py                   # Pydantic UMF models
│   ├── changelog.py             # Changelog entry models
│   └── pipeline.py              # Pipeline configuration models
├── schemas/
│   ├── generators.py            # Schema generation (SQL, PySpark, JSON)
│   ├── umf.schema.json          # JSON Schema for UMF validation
│   ├── gx_expectation_suite.schema.json
│   ├── expectation_categories.json
│   └── expectation_parameters.json
├── type_mappings.py             # Type system conversions
├── date_formats.py              # Date/datetime format definitions
├── naming.py                    # Naming utilities (to_spark_identifier, position_sort_key)
├── naming_validator.py          # Column naming convention validation
├── gx_baseline.py               # GX baseline expectation generation
├── gx_constraint_extractor.py   # Extract constraints from GX suites
├── gx_schema_validator.py       # Schema validation with GX
├── gx_wrapper.py                # GX utility wrapper
├── excel_converter.py           # Bidirectional Excel <-> UMF conversion
├── excel_import_git.py          # Git-integrated Excel import with atomic commits
├── umf_loader.py                # Split/JSON format loader with auto-detection
├── umf_diff.py                  # UMF version diffing
├── umf_change_applier.py        # Atomic change application for per-change commits
├── umf_validator.py             # UMF structural validation
├── changelog_generator.py       # Git-based changelog generation
├── changelog_diff_parser.py     # YAML diff parsing for change detection
├── changelog_formatter.py       # Changelog output formatting
├── inference/
│   └── domain_types.py          # Domain type registry and inference engine
├── sample_data/
│   ├── engine.py                # Main sample data generation engine
│   ├── config.py                # Generation configuration
│   ├── generators.py            # Healthcare-specific data generators
│   ├── column_value_generator.py # Per-column value generation
│   ├── constraint_handlers.py   # Validation constraint handling
│   ├── foreign_keys.py          # FK relationship-aware generation
│   ├── graph.py                 # Dependency graph for generation order
│   ├── filename_generator.py    # Filename pattern generation
│   ├── date_processing.py       # Date format handling
│   ├── registry.py              # Key registry for uniqueness
│   └── validation.py            # Validation rule processing
├── quality/
│   ├── baseline_service.py      # Baseline capture and comparison
│   ├── baseline_storage.py      # Baseline persistence
│   ├── executor.py              # Quality check execution
│   └── storage.py               # Quality result storage
├── profiling/
│   ├── types.py                 # Profiling result types
│   ├── spark_mapper.py          # Spark DataFrame -> UMF (requires PySpark)
│   └── deequ_mapper.py          # Deequ profile -> UMF
├── prompts/
│   ├── documentation.py         # Documentation enrichment prompts
│   ├── validation.py            # Table-level validation rule prompts
│   ├── validation_per_column.py # Per-column validation prompts
│   ├── column_validation.py     # Column-specific validation prompts
│   ├── relationship.py          # Relationship detection prompts
│   ├── survivorship.py          # Survivorship logic prompts
│   ├── filename_pattern.py      # Filename pattern prompts
│   ├── expectation_guide.py     # GX expectation reference
│   └── utils.py                 # Prompt utilities
├── formatting/
│   ├── constants.py             # Formatting constants
│   └── yaml_formatter.py        # YAML output formatting
├── validation/
│   ├── gx_processor.py          # GX expectation processing
│   ├── table_validator.py       # Table validation engine (requires PySpark)
│   └── custom_gx_expectations.py # Custom GX expectation types
├── casting_utils.py             # Type casting utilities
├── completeness_validator.py    # Data completeness validation
├── dependency_resolver.py       # Module dependency resolution
├── format_utils.py              # Format conversion utilities
├── merge.py                     # Table merge with survivorship (requires PySpark)
├── relationship_validator.py    # FK relationship validation
├── spark_factory.py             # SparkSession factory (requires PySpark)
├── survivorship_display.py      # Survivorship rule display
├── sync_baseline.py             # Baseline synchronization
├── output_formatting.py         # Output display formatting
├── validator.py                 # Pipeline-level validation orchestration
└── domain_types.yaml            # Domain type registry definitions
```
