---
name: tablespec-validation
description: Managing Great Expectations validation suites for UMF tables - generating baseline expectations, syncing suites after schema changes (tablespec validation-sync), previewing merged suites, applying reviewed expectation lists (apply-response), and running staged raw/ingested validation with GXSuiteExecutor. Use when creating, editing, syncing, or executing data-quality expectations for UMF-described tables.
---

# Tablespec Validation

Expectations are authored in UMF (per-column `validations:` lists plus the
table's `expectations.yaml` in split format) and compiled into one suite file
per table. This skill covers generating, syncing, previewing, applying, and
executing those expectations.

## The Staging Model

A compiled suite is a single `validation/<table>.suite.json` holding the FULL
expectation list — raw-stage (string landing) and ingested-stage (typed)
expectations co-mingled. Classification into stages happens at EXECUTE time,
not in the file: the executor honors an explicit `meta.validation_stage`
first, then falls back to type-based classification. Redundant and unknown
expectations are skipped, not failed.

```python
from tablespec.validation.gx_executor import GXSuiteExecutor

executor = GXSuiteExecutor(spark)
result = executor.execute_staged(raw_df, ingested_df, expectations)
# result.raw / result.ingested are SuiteExecutionResults; result.skipped lists
# redundant/unknown expectations with reasons.
```

Do not pre-split a suite into raw and ingested files; keep one suite and let
`execute_staged` route each expectation.

## Baseline Generation

`BaselineExpectationGenerator.generate_baseline_expectations(umf_dict)`
derives deterministic expectations from UMF metadata alone — no Spark, no
profiling run required:

- Structural: column count and ordered column list (table-level).
- Nullability: not-null checks from `nullable`, including per-context
  `row_condition` checks when the table declares a context column.
- Length: `expect_column_value_lengths_to_be_between` from `max_length`/`length`.
- Casting: DATE/TIMESTAMP/INTEGER/numeric cast checks plus strftime format
  checks driven by the column `format`.
- Cross-column: date-range ordering for detected start/end column pairs.
- Domain types: expectations from the domain-type registry per `domain_type`.
- Profiling-derived (when profiling data is attached to columns): uniqueness,
  min/max ranges, value sets, completeness, string lengths, regex patterns.

Column-existence and column-type expectations are intentionally NOT generated —
they are redundant with schema metadata. Sources that land native-typed raw
(jdbc/parquet/json `source.kind`) have raw-stage string-shape checks withheld
at composition time; delimited and legacy UMFs are unaffected.

## Order of Operations Gotcha

Set domain types BEFORE syncing, or the domain-derived expectations are
missed:

```bash
tablespec domains-set tables/claims/ --column gender_cd --type gender_code
tablespec validation-sync tables/claims/
```

`domains-set` validates the type against the registry; use `-c`/`-t` as short
flags for `--column`/`--type`.

## Sync After Schema Changes

`tablespec validation-sync PATH` regenerates baseline + domain-type
expectations from the current UMF and reconciles them with what is already in
the column YAML files. It is idempotent, matches on
`meta.generated_from: baseline|domain_type`, and reports added / upgraded /
conflicts / severities preserved. User-authored expectations are never
touched; a user-changed severity on a matching rule is preserved; a rule whose
kwargs differ from canonical is kept as-is and reported as a conflict.

- `--dry-run` — show what would change without writing; run this first.
- `--clean-outdated` — remove baseline/domain expectations the generator no
  longer produces (e.g. after a column or format change); without it they are
  kept.
- `--aggressive` — adopt unmarked expectations that structurally match a
  canonical rule, stamping them as generated (use once when migrating
  hand-written suites).

## Preview

`tablespec preview PATH` renders every expectation classified by stage: RAW,
INGESTED, REDUNDANT, or UNKNOWN, with severity and `generated_from` source.

GOTCHA: preview MERGES freshly generated baseline expectations with the
authored ones from the UMF. It shows what would execute, not what is stored —
do not diff preview output against the suite file expecting equality.

## Apply Reviewed Expectations

`tablespec apply-response PATH RESPONSE.json [--dry-run]` merges a reviewed
(e.g. LLM-produced) expectation list into the table. The JSON may be a bare
list or an `{"expectations": [...]}` envelope; anything else is rejected.
Duplicates of existing expectations are deduplicated and reported; malformed
entries are rejected individually with reasons rather than aborting the run.

## Custom Expectations

tablespec ships three custom GX expectation classes in
`tablespec.validation.custom_gx_expectations`:

- `ExpectColumnValuesToCastToType`
- `ExpectColumnDateToBeInCurrentYear`
- `ExpectColumnValuesToMatchDomainType`

On the classic-Spark GX engine path these must be registered with the GX
registry before executing a suite that uses them —
`tablespec.gx_wrapper.get_gx_wrapper()` performs the registration. The Spark
Connect / native execution path inside `GXSuiteExecutor` evaluates them
directly and needs no registration.

## Which Validator for Which Job

- `tablespec validate PATH` — validates UMF STRUCTURE (schema, naming,
  expectation-type compatibility, relationships); it does not touch data.
- `TableValidator` (`tablespec.validation.table_validator`, requires Spark) —
  validates a DataFrame against a UMF spec and returns a structured error
  DataFrame.
- `GXSuiteExecutor` — runs compiled suites, staged, inside the end-to-end
  backbone.

## Constraint Round-Trip

`GXConstraintExtractor` reads an existing expectation suite (from UMF
validation rules or a standalone expectations YAML) and extracts usable
constraints — value sets, regex patterns, strftime formats, max lengths,
not-null flags — so existing suites can seed UMF enrichment and constraint-
honoring sample data.

## Related

- `tablespec-pipeline` — compiling artifacts and running the backbone that
  executes these suites.
- `tablespec-umf-authoring` — where expectations live in the split format
  (per-column `validations:` and `expectations.yaml`).
- docs/guide/great-expectations.md and
  https://documentdrivendx.github.io/tablespec/
