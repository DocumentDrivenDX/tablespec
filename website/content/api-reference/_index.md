---
title: API Reference
weight: 4
next: /demos
---

This page is for Python users who want the importable surface of the
`tablespec` package. Most symbols below are importable from `tablespec`.
When a symbol lives in a deeper module, the table names that module path.
Symbols in the [Spark extras](#spark-extras) section require
`tablespec[spark]`.

## Loading and saving UMF specs

### `UMFLoader`

Universal Metadata Format (UMF) is tablespec's source-table contract.
`UMFLoader` is the canonical loader. It auto-detects split directories and
JSON files. It does not auto-detect legacy single-file YAML.

```python
from pathlib import Path
from tablespec import UMFLoader, UMFFormat

loader = UMFLoader()
umf = loader.load(Path("tables/medical_claims"))          # split dir or .json
loader.save(umf, Path("tables/medical_claims"))           # split (default)
loader.save(umf, Path("medical_claims.json"), format=UMFFormat.JSON)
```

| Method | Signature |
|--------|-----------|
| `load` | `(path: Path) -> UMF` |
| `save` | `(umf: UMF, path: Path, format: UMFFormat = UMFFormat.SPLIT) -> None` |
| `detect_format` | `(path: Path) -> UMFFormat` |

### Legacy single-file helpers

| Function | Signature | Notes |
|----------|-----------|-------|
| `load_umf_from_yaml` | `(yaml_path: str \| Path) -> UMF` | File paths only; a directory raises `IsADirectoryError`. |
| `save_umf_to_yaml` | `(umf: UMF, yaml_path: str \| Path) -> None` | Writes a single YAML document. |

## Core models

Pydantic models for the UMF source-table format. The main models are:

| Model | Purpose |
|-------|---------|
| `UMF` | Root table model: `table_name`, `canonical_name`, `columns`, `primary_key`, `unique_constraints`, `source`, `expectations`, `relationships`, `ingestion`, `context_column`, ... |
| `UMFColumn` | Column definition: `name`, `data_type`, `length`, `precision`, `scale`, `nullable`, `description`, `domain_type`, `aliases`, ... |
| `Nullable` | Per-context nullability with arbitrary keys (`extra="allow"`). |
| `ExpectationSuite` / `Expectation` / `ExpectationMeta` | The unified expectation suite; meta carries `stage`, `severity`, `blocking`, `generated_from`. |
| `Relationships` / `ForeignKey` | Declared keys and cross-table relationships. |
| `IngestionConfig` | Ingest behavior (mode, exclusions, post-upsert rules). |
| `JdbcSource` (in `tablespec.models.umf`) | Discriminated `source:` member, `kind="jdbc"`; credentials only via `password_secret_ref`. |

See [Universal Metadata Format](/concepts/umf/) for the format itself.

## Schema generators

These functions generate schema artifacts from one UMF spec. All three take a
plain dict; call `umf.model_dump(mode="json", exclude_none=True)` first.

| Function | Signature | Output |
|----------|-----------|--------|
| `generate_sql_ddl` | `(umf_data: dict) -> str` | Spark SQL `CREATE TABLE` for the typed ingested table. `VARCHAR` maps to `STRING`; descriptions become `COMMENT` clauses. |
| `generate_pyspark_schema` | `(umf_data: dict) -> str` | Python **source code** defining a raw-read `StructType` — not a `StructType` object. |
| `generate_json_schema` | `(umf_data: dict) -> dict` | JSON Schema (draft-07) document. |

```python
from tablespec import UMFLoader, generate_sql_ddl
from pathlib import Path

umf = UMFLoader().load(Path("tables/medical_claims"))
ddl = generate_sql_ddl(umf.model_dump(mode="json", exclude_none=True))
```

## Ingest and gold SQL

These functions generate SQL artifacts. Ingest SQL moves one source table from
raw records to a typed ingested table. Gold SQL builds modeled outputs from
related UMF specs.

| Symbol | Signature | Purpose |
|--------|-----------|---------|
| `generate_ingest_sql` | `(umf_data: dict, *, raw_table=None, ingested_table=None, dialect="spark") -> str` | Raw landing DDL + typed DDL + raw-to-ingested MERGE/INSERT transform. |
| `build_ingest_select` | `(umf_data: dict, *, dialect="spark") -> IngestSelect` | Just the typed SELECT (casts per column). |
| `generate_sql_plan` | `(table_umf: UMF, related_umfs: dict[str, UMF], *, mode="views", ...) -> str` | Single-target gold plan SQL. |
| `SQLPlanGenerator` | `.generate_for_table(table_umf, related_umfs, *, mode="views") -> str` | Class form of the above. |

## Project emitters (dbt and Lakeflow)

These functions generate project directories, not only single files. Use them
when dbt or Databricks Lakeflow should run from UMF-derived artifacts.

| Symbol | Signature | Purpose |
|--------|-----------|---------|
| `generate_dbt_project` | `(umf_data: dict, *, dialect="duckdb", target=None, out_dir=None, project_name="tablespec_ingest", related=None) -> dict[str, str]` | Single-table ingest dbt project (model SQL, contracts/tests, sources, profiles). |
| `generate_dbt_dag_project` | `(umfs: list[UMF], *, dialect="duckdb", ..., project_name="tablespec_gold") -> dict[str, str]` | Multi-table gold dbt DAG project. |
| `tablespec.ldp.generate_ldp_project` | `(umfs: list[UMF], *, dialect="spark", file_format="csv", out_dir=None) -> dict[str, str]` | Lakeflow Declarative Pipelines project (raw/ingested/gold datasets). |

Both return `{relative_path: file_content}`. Pass `out_dir` to also write the
project tree to disk. The CLI front-end is
[`tablespec emit`](/cli-reference/#emit).

## Great Expectations integration

| Symbol | Key methods | Purpose |
|--------|-------------|---------|
| `BaselineExpectationGenerator` | `()` then `.generate_baseline_expectations(umf_data: dict, include_structural=True) -> list[dict]` | Deterministic Great Expectations baseline suite from UMF metadata. |
| `GXConstraintExtractor` | `()` then `.load_expectations_for_table(table_name, relationships_dir)`, `.extract_value_sets(expectations)`, `.get_constraints_for_column(expectations, column_name)`, ... | Read constraints out of existing GX suites: value sets, regexes, lengths, and not-null rules. Returns constraint data, not a UMF. |
| `GXExpectationProcessor` | `.process_expectation_suite(...)`, `.update_umf_with_expectations(...)`, `.validate_gx_suite(...)` | Apply/validate GX suites against UMF tables. |
| `UmfToGxMapper` | — | Type mapping helper used by the baseline generator. |

## Excel conversion

| Symbol | Usage |
|--------|-------|
| `UMFToExcelConverter` | `.convert(...)` — write a reviewable workbook with dropdowns and helper columns. |
| `ExcelToUMFConverter` | `.convert(...)` — validate a workbook and convert back to UMF. |

CLI front-ends: `tablespec export-excel` / `import-excel`.

## Sample data

| Symbol | Usage |
|--------|-------|
| `SampleDataGenerator` | `(input_dir: Path, output_dir: Path, config: GenerationConfig, spark=None)` — FK-aware sample data from split-format specs (`.run_generation()`). |
| `GenerationConfig` | Row counts, seeds, and output options. |

## Change management

| Symbol | Usage |
|--------|-------|
| `UMFDiff` | `(old_umf: UMF \| None, new_umf: UMF)` — `.get_column_changes()`, `.get_metadata_changes()`, `.get_validation_changes()`. |
| `ChangelogGenerator` | `.generate_changelog(limit=None, since=None)` — change history from git for split-format specs. |
| `check_compatibility` | `(old: UMF, new: UMF) -> CompatibilityReport` — breaking-change analysis between two spec versions. |

## Type mappings

| Function | Mapping |
|----------|---------|
| `map_to_pyspark_type` | UMF type → PySpark type source string (`"StringType()"`). `DATE` maps to `StringType()` in the raw schema by design — dates land as strings and are cast at ingest. |
| `map_to_json_type` | UMF type → JSON Schema type. |
| `map_to_gx_spark_type` | UMF type → GX Spark type name. |
| `map_pyspark_to_sql_type` | PySpark type name → Spark SQL type. |

## Other

| Symbol | Purpose |
|--------|---------|
| `bootstrap_from_tables` | `(spark, table_names, out_dir, *, profile=True, dialect="duckdb", ...) -> CompiledArtifacts` — infer specs from live Spark tables and compile the full artifact set. |
| `DomainTypeRegistry` / `DomainTypeInference` | Domain type registry and inference (CLI: `domains-*`). |
| `generate_documentation_prompt`, `generate_validation_prompt`, ... | LLM prompt generators; pair with `tablespec apply-response`. |

## Spark extras

These symbols are available only with `tablespec[spark]`. Use them when the
operation needs a Spark DataFrame, JDBC discovery, Spark profiling, or
Databricks-aware Spark session creation.

| Symbol | Signature / usage |
|--------|-------------------|
| `SparkToUmfMapper` | `()` then `.map_dataframe_to_umf(df, table_name, table_type="inferred") -> dict` — infer a UMF dict from a DataFrame. |
| `JdbcToUmfMapper` | `()` then `.discover(spec: JdbcSource, spark) -> list[UMF]` — discover one validated UMF per table from a database over JDBC (INFORMATION_SCHEMA + reflected Spark schema; keys, FKs, and provenance columns included). |
| `NativeSparkProfiler` (in `tablespec.profiling`) | `(spark, low_cardinality_threshold=50, ...)` then `.profile(df, ...) -> DataFrameProfile` — Spark-SQL profiling that works on classic Spark **and** Spark Connect / Databricks serverless. |
| `TableValidator` | `(spark)` then `.validate_table(df, umf_path: Path, table_name=None) -> DataFrame` — `umf_path` is a single-file YAML spec; returns a DataFrame of validation errors (`VALIDATION_ERROR_SCHEMA`); empty means clean. |
| `SparkSessionFactory` / `create_delta_spark_session` | Session factory with Databricks detection and consistent Delta configuration. |
