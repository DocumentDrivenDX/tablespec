# gold_first_record

First-record-per-key selection. Exercises
`SQLPlanGenerator._generate_first_record_join` (strategy resolves to
`first`/`first_record` from the 1:N cardinality -> ROW_NUMBER partitioned dedup,
keep `rn = 1`).

Target: `first_detail.umf.yaml`; sources: `hub.umf.yaml` (1) -> `detail.umf.yaml`
(N). Golden status: **executed** (committed Spark-oracle golden, enforced on both
DuckDB and the Spark session).

## What it pins

* `detail` has NO single-column PK -- `parent_id` is a 1:N FOREIGN key. (If it were
  declared the PK, the ingest staging model would dedup to one row per parent and
  collapse the N detail rows before the first-record ranking even runs.)
* The first-record ROW_NUMBER ranking is a TOTAL ORDER: the generator's heuristic
  discriminator (`record_type`) plus a stable tiebreak over the remaining columns
  (`detail_value`, `updated_date`). Parent 1 carries two rows tied on
  `record_type='A'` with different `detail_value` (`zeta`, `alpha`); the tiebreak
  deterministically selects `alpha` on BOTH backends. Without the tiebreak the
  "first" row would be undefined and DuckDB and Spark could disagree.

Golden: parent 1 => `alpha`, parent 2 => `gamma`.
