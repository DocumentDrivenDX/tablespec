# gold_join

Multi-table sequential join (member x claims). Exercises the
`SQLPlanGenerator._generate_join_step` path (direct/sequential join) via
`generate_sql_plan(target_umf, related_umfs)`.

Files:
- `claims.umf.yaml`, `member.umf.yaml` — source tables (with the FK relationship
  that drives the join plan).
- `claim_enriched.umf.yaml` — the gold target whose derivation pulls
  `member_name` from `member` via the claims->member foreign key.
- `claims.raw.csv`, `member.raw.csv` — real source rows.

The claims batch carries an ORPHAN claim (`claim_id=104`, `member_id=9` with no
matching member row) so the LEFT-join semantics are non-vacuous: row 104 survives
with a NULL `member_name`, which the committed golden pins on both backends. The
INNER + `join_filter` contrast (where that orphan and a filtered-out member are
DROPPED) lives in the sibling `gold_inner_join_filter` case — the matrix derives
exactly one golden per case id, so LEFT and INNER cannot share one case.

Golden status: **EXECUTED** — `tests/golden/ingest_parity/gold_join.spark.expected.json`
is the Spark-backend `SQLPlanGeneratorGold` oracle output (written under
`--update-golden`). The matrix runs the generated gold project on BOTH the Spark
session AND DuckDB and asserts byte-identical agreement with that golden.
