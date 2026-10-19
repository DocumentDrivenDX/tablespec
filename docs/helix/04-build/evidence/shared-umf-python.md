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


## Current core cut — 2026-10-19

The current binding emits and accepts UMF core 0.10.0 only. The official source
pin and generated lock now name `4cdddceaceded64e59ac24b65f106e9610f90653`;
that source commit still awaits upstream publication. Lock resolution used a
command-local Git URL mapping to that exact local commit and fetched dependency
metadata normally. Only the umf-core lock entry changed (0.8.0 to 0.10.0); this
is not evidence that the commit is remotely available.

Qualification uses the official built 0.10.0 wheel, SHA-256
`692271d23216241e60c83296ce70bdb1021928c1751362f55d4b120d6cb9acaa`,
in an isolated Python 3.12.15 environment with Pydantic 2.11.10 and explicit
source PYTHONPATH. All 21 shared-binding tests pass, including public-loader
refusal of 0.7/0.8/0.9 documents. Native TableSpec authoring version 1.0 and
TableSpec extension version 0.1.0 remain independent of the shared core version.

All 18 consumer ontology snapshots were refreshed from the matching canonical
UMF `spec/domain-packs/<pack>/ontology.json` exports. Each matches its canonical
source byte for byte; one census test validates and exactly round-trips all 18
through the official core model with complete validation and zero diagnostics.
The core header is the only changed ontology content.

The initial broader regression found 361 passing tests and 12 golden mismatches
caused by repository license headers in expected SQL/Python/dbt files. The
integration branch excludes only those fixture header lines from expected
output; its 17 golden/schema-sync checks pass. Combined integrated qualification
is recorded below when completed; these results do not qualify Spark or remote
Databricks. The original dated 0.8 results above remain historical evidence.
