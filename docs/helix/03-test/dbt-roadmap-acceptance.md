# dbt Roadmap — Acceptance Criteria & Test Matrix

Status: Approved for implementation on `feat/dbt-roadmap`.
Scope: roadmap items 2–5 of ADR-008 §4 (schema tests `accepted_values`+single-table
`relationships`, model contracts, `state:modified` CI selection, sample_data→seeds).

This document defines **unambiguous, machine-checkable** Given/When/Then acceptance
criteria for each roadmap item, and the concrete automated tests (labeled
**e2e / functional / integration**) that prove each criterion. Every criterion has
at least one automated test; negative paths are explicit tests that **must fail**
(orphan FK, out-of-set value, contract drift, wrong seed type) and must be asserted as
failing.

> **Phase note (criteria-first):** This is the acceptance-definition phase. Every
> module, fixture, and test named below as `(NEW)` — `core/schema_facts.py`,
> `core/selection.py`, `dbt/schema_tests.py`, `dbt/contracts.py`, `dbt/selection.py`,
> `dbt/seeds.py`, the `tests/fixtures/dbt_roadmap/*` fixtures, and the `test_*`
> functions — does **not** exist yet and is the deliverable of the later
> implementation phases on `feat/dbt-roadmap`. Criteria are written against the
> CURRENT real APIs (`UMFDiff(old,new)` per-table; `ForeignKey` scalar columns;
> `Column.length`/`precision`/`scale`; `SampleDataGenerator(input_dir,output_dir,
> config).generate()` writing `|`-delimited files) so the to-be-built code has an
> exact, verifiable target.

## Conventions used by every test

- **Run prefix** (all python/dbt/uv):
  `UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 uv run <cmd>`
- **e2e** = UMF → `generate_dbt_project` / `generate_dbt_dag_project` → real `dbt`
  (`parse`/`compile`/`seed`/`build`/`test`) on **real duckdb** → query the warehouse
  → assert on actual rows / on dbt's pass/fail exit code. dbt invoked via
  `subprocess.run(["dbt", ...,"--profiles-dir",p,"--project-dir",p], env={...DBT_DUCKDB_PATH})`,
  mirroring `tests/ingest_parity/test_dbt_duckdb_parity.py` and
  `tests/dbt_dag/test_dbt_dag_gold_chain.py`. Skips if `shutil.which("dbt") is None`;
  marked `no_spark` + `slow`.
- **functional** = the emitter behaves over real UMF input, including negative paths,
  asserting on returned `{path: contents}` (parsed YAML, not substring greps where
  structure matters). No mocks for the behavior under test.
- **integration** = real dbt + real duckdb (and, where a Spark truth-gate applies,
  real Spark under the resolved JDK). Distinguished from e2e by asserting on dbt
  artifacts (manifest, `run_results.json`, catalog) rather than warehouse rows.
- **Encapsulation gate** (applies to ALL items, asserted by the existing
  `tests/test_core_encapsulation.py`, extended as needed): every new emitter module
  lives under `src/tablespec/dbt/`; the derivation facts live under
  `src/tablespec/core/schema_facts.py` / `core/selection.py`; nothing in
  `tablespec.core` imports `tablespec.dbt`; generating a project imports **no**
  `dbt` package (the `[dbt]` extra is only touched by an execution runner).

## Real data fixtures (reused, not hand-rolled per assertion)

| Fixture | Path | Shape relevant here |
|---|---|---|
| `member_claims` (multi-table DAG) | `tests/fixtures/dbt_dag/{member,claims,member_claims}.umf.yaml` + `*.raw.csv` | `claims.member_id` and `member_claims.*` FK → `member.member_id`; `member` is a landing table (has `ingested_member`). Single-pipeline FK that already drives the DAG-path `relationships`. |
| `gold_chain` | `tests/fixtures/dbt_dag_gold_chain/*` | gold→gold edge (`summary`→`enriched`); used to confirm `relationships` can point at a gold node, and the contract/seed e2e on a chain. |
| New: `fk_referential` | `tests/fixtures/dbt_roadmap/fk_referential/` (NEW, committed) | a parent table + child table with a single-pipeline FK, **plus** two raw CSV variants: `*.valid.csv` (all child FKs resolve, includes a NULL nullable-FK row) and `*.orphan.csv` (one child row references a non-existent parent key). Drives the relationships PASS/FAIL e2e. |
| New: `accepted_values` | `tests/fixtures/dbt_roadmap/accepted_values/` (NEW) | a table whose UMF column carries an `expect_column_values_to_be_in_set` expectation (value_set e.g. `["MD","MP","ME"]`), plus `*.valid.csv` (in-set only) and `*.bad.csv` (one out-of-set value). |
| New: `contract_drift` | `tests/fixtures/dbt_roadmap/contract_drift/` (NEW) | a table with INTEGER/DECIMAL/DATE columns and a not-null column; a model variant whose SELECT casts a column to the WRONG type to drive the contract-violation negative path. |
| `sample_data` driver | existing `SampleDataGenerator` (`src/tablespec/sample_data/engine.py`) run over a roadmap fixture UMF set | produces **real generated CSVs** consumed as seeds — no hand-written seed fixtures. |

Fixture UMFs are minimal but **realistic** (typed columns, primary_key, FK,
in-set expectation) and are committed so tests are deterministic.

---

## Item (1) relationships_accepted_values

FK `relationships` + `accepted_values` generic tests in `schema.yml` on
`ingested_`/`gold_` models. The derivation lives in `core/schema_facts.py`
(`ColumnTest.relationship(...)`, `ColumnTest.accepted_values(...)`); the
`schema.yml` text lives in `dbt/schema_tests.py`, consumed by **both**
`single_table.py` (NEW relationships path) and `project.py` (complete
accepted_values; relationships already present on the DAG path).

### Acceptance criteria

- **AC1.1 (relationships emitted, DAG path) — Given** the `member_claims` UMF set
  where `member_claims` has a single-pipeline FK `member_id → member.member_id` and
  `member` is a landing table, **When** `generate_dbt_dag_project` runs, **Then**
  `models/schema.yml` contains a `relationships` `data_test` on the
  `gold_member_claims` column `member_id` whose `arguments.to` is
  `ref('ingested_member')` and `arguments.field` is `member_id`. (This is exactly the
  current committed golden `tests/golden/dbt_dag_project/member_claims/models/schema.yml`
  — preserve it byte-for-byte; only landing-table tables that become `gold_<t>` carry
  the test, so there is NO `gold_claims` model/test in this set.)
- **AC1.2 (relationships emitted, single-table path) — Given** a single UMF whose
  `relationships.foreign_keys` references another table, **When** `generate_dbt_project`
  runs, **Then** the model's `schema.yml` carries a `relationships` test pointing at
  `ref('<referenced_table>')`/`field: <references_column>`. Because the single-table
  emitter today receives ONE `umf_data` dict and no UMF set (see
  `single_table.py:214`), the implementation MUST add an explicit way to resolve the
  FK target — either a new optional `related: list[UMF] | None` (or `NodeRegistry`)
  parameter, OR (when no set is supplied) emit the `relationships` `to:` as a bare
  `ref('<references_table>')` literal and rely on `dbt parse` to validate the ref
  exists. The acceptance asserts the emitted `to:`/`field:` for the FK target named in
  the UMF; resolving to a missing model is a `dbt parse` failure (covered by the e2e).
- **AC1.3 (multiple single-column FKs) — Given** a UMF table with TWO separate
  `foreign_keys` entries (UMF `ForeignKey` is scalar `column`/`references_column`;
  there is no composite-FK structure in the model today, and dbt-core core
  `relationships` is single-column only), **When** the project is generated, **Then**
  each FK yields its OWN `relationships` test on its column and `dbt parse` accepts the
  schema.yml. (Composite/multi-column referential integrity as a single test is
  explicitly OUT OF SCOPE — not expressible without dbt-utils, which ADR-008 declines.)
- **AC1.4 (nullable FK does not false-fail) — Given** a child table whose FK column is
  nullable and a valid dataset containing a row with NULL FK, **When** `dbt test`
  runs the relationships test, **Then** the test PASSES (dbt `relationships` ignores
  NULLs). NEGATIVE-OF-NEGATIVE: a NULL must NOT be reported as orphan.
- **AC1.5 (cross-pipeline/external skipped) — Given** a UMF FK with
  `cross_pipeline: true` or referencing a table not in the UMF set, **When** the
  project is generated, **Then** NO `relationships` test is emitted for that column
  (and no `ref()` to a non-existent model is produced).
- **AC1.6 (accepted_values emitted) — Given** a UMF column carrying an
  `expect_column_values_to_be_in_set` expectation with `value_set=[...]`, **When** the
  project is generated, **Then** `schema.yml` carries an `accepted_values` test on
  that column with `arguments.values` equal to that set.
- **AC1.7 (no spurious accepted_values) — Given** a column with no set-membership
  expectation, **When** generated, **Then** NO `accepted_values` test is emitted for
  it.
- **AC1.8 (orphan FK FAILS — NEGATIVE) — Given** `fk_referential` loaded with
  `*.orphan.csv`, **When** `dbt build` then `dbt test` runs, **Then** the
  relationships test FAILS (non-zero exit; `run_results.json` shows that test
  `status == "fail"` / `failures >= 1`).
- **AC1.9 (valid referential set PASSES) — Given** `fk_referential` loaded with
  `*.valid.csv` (including the NULL nullable-FK row), **When** `dbt test` runs,
  **Then** the relationships test PASSES (exit 0).
- **AC1.10 (out-of-set value FAILS — NEGATIVE) — Given** `accepted_values` fixture
  loaded with `*.bad.csv`, **When** `dbt test` runs, **Then** the `accepted_values`
  test FAILS; with `*.valid.csv` it PASSES.

### Test matrix — item (1)

| Test | Kind | Real data / invocation | Proves |
|---|---|---|---|
| `test_schema_tests_relationships_single_table` | functional | parse emitted `schema.yml` from `generate_dbt_project` over `fk_referential` child UMF (FK target resolved via the new `related`/registry param) | AC1.2, AC1.3 (two FKs → two tests), AC1.5 |
| `test_schema_tests_relationships_dag_preserved` | functional | parse `schema.yml` from `generate_dbt_dag_project` over `member_claims` set | AC1.1, AC1.5 |
| `test_schema_tests_accepted_values_emitted` | functional | parse `schema.yml` from `accepted_values` fixture UMF; negative: column without in-set has none | AC1.6, AC1.7 |
| `test_relationships_orphan_fails_valid_passes` | e2e | `fk_referential` → `generate_dbt_*` → load `*.valid.csv` / `*.orphan.csv` into duckdb → `dbt seed`/`build` + `dbt test`; assert exit code AND `run_results.json` status per dataset | AC1.4, AC1.8, AC1.9 |
| `test_accepted_values_bad_fails_valid_passes` | e2e | `accepted_values` fixture, two CSV variants → `dbt test`; assert fail vs pass | AC1.10 |
| `test_relationships_manifest_edge` | integration | `dbt parse` on `member_claims`; load `target/manifest.json`; assert the relationships test node exists and its `depends_on` includes `ingested_member` | AC1.1 (dbt understood the ref, not just text) |

Negative paths required-failing and asserted-as-failing: AC1.8, AC1.10.

---

## Item (2) model_contracts

`config(contract={enforced: true})` + per-column `data_type` + `constraints:` in
`schema.yml`, derived from the UMF column set via `core/schema_facts.py`
(`ColumnContract(name, data_type, nullable, constraints)`) and emitted by
`dbt/contracts.py`. SQL types map per dialect reusing the type/column derivation
that `generate_sql_ddl` already performs (`type_mappings` + the UMF `Column.length`
[VARCHAR size] / `Column.precision` / `Column.scale` fields — note the field is
`length`, NOT `max_length`), targeted at duckdb adapter types.

### Acceptance criteria

- **AC2.1 (contract enforced) — Given** a UMF table, **When** the project is
  generated, **Then** the model's `config` sets `contract: {enforced: true}` and
  `schema.yml` lists every column with a `data_type` (e.g. `INTEGER`, `DECIMAL(18,2)`,
  `VARCHAR(n)`/`VARCHAR`, `DATE`, `TIMESTAMP`, `BOOLEAN`) matching the UMF
  type+precision/scale/length.
- **AC2.2 (not-null constraint) — Given** a UMF column with `nullable: false`,
  **When** generated, **Then** that column carries a `not_null` contract constraint
  (`constraints: [{type: not_null}]`), and a nullable column does not.
- **AC2.3 (matching types pass build) — Given** a model whose SELECT produces columns
  of the declared types over real seed data, **When** `dbt build` runs, **Then** it
  SUCCEEDS and the duckdb catalog column types equal the contract types.
- **AC2.4 (type drift FAILS — NEGATIVE) — Given** the `contract_drift` model variant
  whose SELECT casts a column to a type differing from the contract `data_type`,
  **When** `dbt build` runs (contracts are enforced at build/materialization time by
  the adapter, NOT at `parse`), **Then** it FAILS with a contract mismatch (non-zero
  exit; `run_results.json` shows the model `status` failed and the error text
  references the column and a type mismatch). `dbt parse` is NOT the asserted path for
  SELECT-output type drift.
- **AC2.5 (not-null violation FAILS — NEGATIVE) — Given** seed data with a NULL in a
  `not_null`-constrained contract column, **When** `dbt build` runs, **Then** it
  FAILS (constraint enforced by the adapter).
- **AC2.6 (encapsulation/import-safe) — Given** the `[dbt]` extra is NOT installed,
  **When** `dbt/contracts.py` emits the contract text, **Then** it imports no `dbt`
  package (pure text emission).

### Test matrix — item (2)

| Test | Kind | Real data / invocation | Proves |
|---|---|---|---|
| `test_contract_columns_match_umf_types` | functional | `core.schema_facts.column_contracts(umf)` + `dbt/contracts.py` over `contract_drift` UMF; assert each column's `data_type`/`constraints` vs UMF (incl DECIMAL(p,s), VARCHAR(n), not_null) | AC2.1, AC2.2 |
| `test_contract_build_passes_matching` | e2e | `contract_drift` (matching variant) → seed real CSV → `dbt build`; query duckdb `information_schema`/`PRAGMA` for column types; assert equal to contract | AC2.3 |
| `test_contract_type_drift_fails` | e2e | drift model variant → `dbt build`; assert non-zero exit and contract-mismatch error captured from stderr/`run_results.json` | AC2.4 |
| `test_contract_not_null_violation_fails` | e2e | seed with a NULL in not_null column → `dbt build`; assert failure | AC2.5 |
| `test_contracts_import_safe` | integration | import `tablespec.dbt.contracts` and generate with `dbt` uninstalled-path asserted via `sys.modules` check (extends `test_core_encapsulation.py`) | AC2.6 |

Negative paths required-failing and asserted-as-failing: AC2.4, AC2.5.

---

## Item (3) state_modified_ci

Map the `umf_diff` changed-table set to a dbt selection so CI builds/tests only
impacted models + downstream. `core/selection.py` (NEW) exposes `ChangeSet(tables: frozenset[str])` plus a
`change_set(old_dir, new_dir) -> ChangeSet` helper that **wraps the existing
per-table `UMFDiff`** (which is `UMFDiff(old_umf, new_umf)` over ONE table at a time —
there is no repo-wide diff today). The helper pairs files by `table_name` across the
two dirs and marks a table "modified" iff its `UMFDiff` yields any non-empty
`get_column_changes()` / `get_validation_changes()` / `get_metadata_changes()`;
added (NEW-only) and removed (OLD-only) tables are included in the set, with removed
tables flagged so the dbt mapping never points at a deleted model.

`dbt/selection.py` (NEW) is the ONLY dbt-aware piece and exposes the canonical
mapping `select_expression(change_set) -> str`: an explicit graph-fanout union
`<model_a>+ <model_b>+ ...` over the changed tables' models (`ingested_<t>` and, where
present, `gold_<t>`), where the trailing `+` selects descendants. (The dbt-native
`state:modified+ --state <prior-manifest>` form is documented as an EQUIVALENT
alternative for CI that has a stored manifest, but the explicit-union expression is
the asserted, deterministic mechanism so the tests do not depend on manifest state.)

### Acceptance criteria

- **AC3.1 (one changed UMF → that model + descendants) — Given** OLD vs NEW UMF dirs
  for the `member_claims` set differing in exactly one table (`member`), **When**
  `ChangeSet` is computed and mapped to a selection, **Then** the selection resolves
  (per dbt's graph) to `member`'s models AND its descendants (`gold_member_claims`,
  and any model that `ref()`s member), and EXCLUDES unrelated models with no path
  from `member`.
- **AC3.2 (unchanged-everything selects nothing) — Given** OLD == NEW, **When**
  `ChangeSet` is computed, **Then** `change_set` returns an empty set and
  `select_expression(empty)` returns the canonical empty selector `""` (empty string).
  The dbt mapping MUST translate an empty `ChangeSet` to a no-op: the test asserts
  `dbt ls --select <expr>` (with `<expr>` being whatever `select_expression` returns
  for the empty set, e.g. an unsatisfiable/empty selector) prints ZERO nodes and
  `dbt build` reports 0 models. An empty `ChangeSet` must NEVER fall through to
  selecting the whole project.
- **AC3.3 (unrelated table excluded) — Given** a change to a table with no downstream
  consumers, **When** mapped, **Then** only that table's own model(s) are selected,
  not the whole project.
- **AC3.4 (added/removed table handled) — Given** NEW adds a table absent in OLD,
  **Then** the new table is in the `ChangeSet`; a removed table does not produce a
  selection pointing at a non-existent model.
- **AC3.5 (engine-agnostic core) — Given** `core/selection.py`, **Then** it has NO
  knowledge of `state:modified`/dbt (asserted by encapsulation test); the dbt mapping
  lives only in `dbt/selection.py`.

### Test matrix — item (3)

| Test | Kind | Real data / invocation | Proves |
|---|---|---|---|
| `test_changeset_from_umf_dirs` | functional | two real UMF dirs (NEW = `member_claims` set with one edited `member` column) → `core.selection.change_set(old_dir,new_dir)`; assert `{member}`; OLD==NEW → empty | AC3.1 (set), AC3.2 (set), AC3.4 |
| `test_selection_expression_shape` | functional | `dbt/selection.py` maps `{member}` → `--select` expr; empty set → empty/`--select` that selects nothing | AC3.2, AC3.5 |
| `test_state_modified_selects_descendants` | e2e | generate `member_claims` DAG project; `dbt build` once to write a prior manifest; edit `member` UMF → regenerate; `dbt ls --select <derived>` (or `state:modified+ --state <prior>`); assert the returned node set == {member's models} ∪ descendants, and unrelated models absent | AC3.1, AC3.3 |
| `test_state_unchanged_selects_nothing` | e2e | regenerate with no UMF change; `dbt ls --select <derived>`; assert empty node list (and `dbt build --select <expr>` reports 0 models) | AC3.2 |
| `test_selection_core_has_no_dbt` | integration | extend `test_core_encapsulation.py`: assert `tablespec.core.selection` AST/import set excludes `dbt` and `state:modified` literal | AC3.5 |

---

## Item (4) sample_data_seeds

Emit the EXISTING `SampleDataGenerator` output as dbt seeds (`seeds/<t>.csv` + a
`seeds:` config in `dbt_project.yml` with `column_types` from UMF). `dbt/seeds.py`
(NEW) consumes already-generated sample files (real generated data) + the UMF
column/type facts; it does NOT re-implement generation, and `generate_dbt_project` /
`generate_dbt_dag_project` gain NO seed coupling (the seed emitter is a separate
function the caller invokes — keeping the project generators unchanged).

Reality of the generator (anchored to `sample_data/engine.py`): `SampleDataGenerator`
is constructed `SampleDataGenerator(input_dir, output_dir, config)`, and `generate()`
WRITES files into `output_dir` and returns `True` (it does NOT return per-table CSV
text). It writes delimited text using the UMF delimiter (default `|`) with a
filename derived from the UMF filename pattern, NOT necessarily `<table>.csv`, and the
header uses `canonical_name`. Therefore `dbt/seeds.py` MUST: (a) read the generated
file for each table from `output_dir` (resolving the actual generated filename), and
(b) NORMALIZE it into a dbt-seed-compatible `seeds/<table>.csv` (comma-delimited,
header = the contract column names) — seed bytes are NOT required to byte-equal the
generator's raw `|`-delimited output; they are required to be the SAME ROWS/VALUES
re-encoded as a dbt-loadable CSV.

### Acceptance criteria

- **AC4.1 (seed files emitted) — Given** a UMF set and the files written by
  `SampleDataGenerator(input_dir, output_dir, config).generate()` into `output_dir`,
  **When** the seed emitter (`dbt/seeds.py`) runs over that `output_dir` + the UMF set,
  **Then** each table yields `seeds/<t>.csv` whose ROWS/VALUES equal the generated
  data, re-encoded as a comma-delimited CSV with header = the contract column names,
  and `dbt_project.yml` gains a `seeds:` block mapping each seed to `column_types`
  derived from UMF (e.g. `{member_id: VARCHAR, amount: 'DECIMAL(18,2)'}`).
- **AC4.2 (seed loads with correct types) — Given** the emitted seeds, **When**
  `dbt seed` runs on duckdb, **Then** each seed table is created and the duckdb column
  types equal the configured `column_types` (asserted via `information_schema`).
- **AC4.3 (downstream ref builds) — Given** a model that `ref()`s a seed, **When**
  `dbt build` runs, **Then** it SUCCEEDS and querying the model returns the seeded
  rows (assert actual row count / values).
- **AC4.4 (real generated data, not hand fixtures) — Given** the seed CSVs, **Then**
  they originate from invoking `SampleDataGenerator(...).generate()` in the test (not
  committed hand-written seed CSVs) — the test runs the generator into a temp
  `output_dir` and feeds that directory to the seed emitter.
- **AC4.5 (wrong column_type FAILS — NEGATIVE) — Given** a seed whose CSV contains a
  value incompatible with the configured `column_type` (e.g. non-numeric in an
  INTEGER column), **When** `dbt seed` runs, **Then** it FAILS (load/cast error).

### Test matrix — item (4)

| Test | Kind | Real data / invocation | Proves |
|---|---|---|---|
| `test_seed_emitter_files_and_column_types` | functional | run `SampleDataGenerator(input_dir,output_dir,config).generate()` over roadmap UMF set → feed `output_dir` to `dbt/seeds.py`; assert `seeds/<t>.csv` rows == generated rows (re-encoded comma-delimited) and `dbt_project.yml` `seeds.column_types` derived from UMF | AC4.1, AC4.4 |
| `test_seed_loads_with_types` | e2e | emit seeds → `dbt seed` on duckdb → `information_schema.columns`; assert column types equal config | AC4.2 |
| `test_seed_downstream_ref_builds` | e2e | add a trivial model that `ref('<seed>')` → `dbt build` → `SELECT` from the model; assert seeded rows present | AC4.3 |
| `test_seed_wrong_type_fails` | e2e | inject a type-incompatible value into one generated CSV cell → `dbt seed`; assert non-zero exit / load error | AC4.5 |

Negative path required-failing and asserted-as-failing: AC4.5.

---

## Cross-cutting gates (every phase keeps these green)

- **Encapsulation** — `tests/test_core_encapsulation.py` (extended): no
  `core → dbt` import; the two backends never import each other; generating any
  project imports no `dbt` package (`dbt` absent from `sys.modules` after a generate
  call).
- **make check equivalent** — `ruff` (lint+format), `pyright` on `src/`, and the full
  pytest suite stay green; coverage of `tablespec.dbt` is maintained or raised
  (new modules `schema_tests.py`, `contracts.py`, `selection.py`, `seeds.py` and
  `core/schema_facts.py`, `core/selection.py` each carry direct unit tests).
- **Spark truth-gate** — where a parity/truth assertion already runs on Spark
  (ingest parity), the existing Spark baseline remains the source of truth; new dbt
  schema tests/contracts do not alter the parity goldens.
- **Golden updates** — `member_claims` golden `schema.yml` (and any DAG-path golden)
  is regenerated and committed when the schema-tests emitter changes; the golden test
  asserts byte-equality to the regenerated artifact.
