# gold_fk_integrity

Referential-integrity coverage. NOTE (acceptance Section 4.3 #10): orphan-FK
validation is NOT emitted by `generate_sql_plan` (FK metadata there only drives
join planning / join type). FK-integrity is therefore tested at the dbt
`relationships` schema-test tier: `generate_dbt_dag_project` emits the
`relationships` test for `claims.member_id -> member.member_id`, and `dbt
build`/`dbt test` is asserted to PASS on `claims.clean.csv` and FAIL on
`claims.orphan.csv` (the injected orphan row `member_id=7`).

The SparkDirect gold join result for the clean data is the corpus golden
(produced by the executed-gold phase); the orphan negative is a dbt-test
assertion, not a canonical-row comparison.

Golden status: **pending** (see `cases.yaml`).
