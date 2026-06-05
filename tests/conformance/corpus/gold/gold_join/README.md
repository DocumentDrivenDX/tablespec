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

Golden status: **pending** (declared in `cases.yaml` with `pending: true`). The
canonical golden is produced by the executed-gold phase, which runs the generated
gold SQL on BOTH the Spark session AND DuckDB (via the dbt-generated gold project)
and writes `tests/golden/ingest_parity/gold_join.spark.expected.json` under
`--update-golden`. Phase 2 ships the source fixtures + pins the generator path;
it does not fabricate a golden it cannot yet execute.
