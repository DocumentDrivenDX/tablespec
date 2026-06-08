# Execution Report

Bead: `tablespec-0b146671`

## Code Changes

- Added `src/tablespec/dialects.py` as the shared source of truth for cast dialect
  aliases and dbt profile targets.
- Routed `cast_column_sql`, `build_ingest_select`, `contract_sql_type`, and
  `render_profiles_yml` through the shared dialect helper.
- Kept `databricks` as a public cast spelling while normalizing it to the
  Spark-family render path.

## Acceptance Evidence

- `tests/unit/test_casting_utils.py`
  - Verifies `databricks` matches `spark` for INTEGER, DECIMAL, DATE with format,
    TIMESTAMP without format, BOOLEAN, `EPOCH_MS_FORMAT`, and
    `EXCEL_SERIAL_FORMAT`.
  - Verifies unsupported cast dialect errors report the shared accepted values.
- `tests/unit/test_ingest_generator.py`
  - Verifies `build_ingest_select(..., dialect="databricks")` succeeds and emits
    the same `select_block` as `dialect="spark"`.
  - Verifies unsupported ingest dialects fail before any column processing and use
    the shared accepted-values text.
- `tests/dbt_roadmap/test_contracts_functional.py`
  - Verifies dbt contract helpers accept `databricks` and reject unsupported
    dialects with the shared cast-dialect accepted-values text.
  - Verifies profile helper validation reports the shared profile-target values.

## Verification

- `uv run pytest tests/unit/test_casting_utils.py tests/unit/test_ingest_generator.py tests/dbt_roadmap/test_contracts_functional.py`
  - Passed: `120 passed`.
- `go test ./...`
  - Failed at repository root because this worktree has no Go module or Go
    sources.
