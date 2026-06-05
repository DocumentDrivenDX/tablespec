# gold_first_record

First-record-per-key selection. Exercises
`SQLPlanGenerator._generate_first_record_join` (strategy resolves to
`first`/`first_record` from the 1:N cardinality -> ROW_NUMBER partitioned dedup).

Target: `first_detail.umf.yaml`; sources: `hub.umf.yaml` (1) -> `detail.umf.yaml`
(N). Golden status: **pending** (see `cases.yaml`); produced by the executed-gold
phase on both backends.
