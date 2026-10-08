# Shared UMF Python binding evidence — 2026-10-07

Scope: FEAT-001 ownership amendment and CONTRACT-001. TableSpec owns its native
pipeline model, extension schemas, migration/archive and execution binding. Shared
models, schema validation and canonical serialization are imported from UMF.

The final scoped regression passes 396 tests, including 18 new shared-document
cases and existing model, loader, domain-type, source-spec, validation, schema,
golden, SQL-plan and public bootstrap tests. Runtime: Python 3.12.15, Pydantic
2.11.10, Click 8.3.1, Typer 0.24.1 and DuckDB 1.5.6. The test command includes
`test_shared_umf`, `test_umf_models`, `test_umf_loader`,
`test_domain_type_compatibility`, `test_source_spec`, `test_umf_validator`,
`test_sql_plan_consumers`, `test_loader_roundtrip`, `test_golden`,
`test_schema_generators`, `test_compiled_parser` and `test_bootstrap_from_specs_public`.

The new cases prove shared field/type consumption, explicit native bindings,
native/scalar conflict refusal, unknown-content canonical persistence, changed-view
and unsupported-core-property refusal, original UTF-8 file recovery for JSON,
inline YAML and split input, archive mutation detection, numeric-loss refusal,
existing ingest artifact equality, CLI generation and compile-orchestrator
snapshot preservation. Synthetic DuckDB integer/decimal/string rows (valid,
null and failed casts) match the native-model path. Compiled source extraction
also reads the retained shared snapshot instead of silently losing source shape.

Earlier failures: three new tests assumed a nonexistent `as_dict` method or a
version in shorthand golden fixtures; corrected tests use existing model APIs and
explicit fixture versions. A newer temporary Click version produced a warning
failure before the CLI ran; the final environment uses the repository's locked
Click/Typer/Pydantic versions. Existing compatibility tests were unchanged.

Canonical input can be authored directly with the TableSpec native type refinements.
The initial binding does not execute core nullability/cardinality/facets/keys/
relationships/examples/defaults/allowedValues. Those properties refuse explicitly;
native meanings for the corresponding legacy metadata remain in the TableSpec
extension. This is a qualified Python consumer slice, not full native-port or
Spark/Databricks end-to-end acceptance. Legacy I/O remains available.

The dependency is pinned to official UMF commit
`8d37fd1100a4d8cdefa132a3e17a924f624cd873`, Python subdirectory. The generated
lock adds `umf-core` 0.8.0 without upgrading existing package versions. Wheel
and source-distribution builds pass; the installed wheel includes both local
extension schemas and passes the 396-test regression. The final type-narrowing
change also passes all 18 shared-document tests from source.

New extension and test files pass Ruff. Touched existing files retain 15
pre-existing lint findings, compared with HEAD; no new findings were introduced.
Scoped Pyright has no new type errors, but reports three existing PySpark imports
unavailable in the temporary environment. Spark execution remains outside this
evidence scope. Upstream commit publication is pending; the lock was generated
against that exact local commit using a temporary Git URL mapping.
