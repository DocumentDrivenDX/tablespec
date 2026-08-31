# gold_union_branches

Exercises `_generate_union_branch_base_view` — the `base_table_strategy:
union_branches` path where the base table and each `union_base_tables` entry
become one UNION ALL branch projecting the TARGET column set through that
source's own derivation candidates.

The shape mirrors a real generation cutover: a legacy snapshot feed
(`inventory_legacy`) is superseded by a daily feed (`inventory_daily`) on
2026-07-20, expressed as complementary per-branch `row_filter`s on a DATE-typed
`file_date` column (kept portable — no `to_date` format parsing — because gold
SQL executes verbatim on BOTH DuckDB and Spark).

Per branch, the case pins:

- **row_filter**: legacy branch keeps `file_date < DATE '2026-07-20'` (drops
  A3, filed 2026-07-25); daily branch keeps `>=` (drops A5, filed 2026-07-15).
- **dedup latest**: `ROW_NUMBER() OVER (PARTITION BY arbit_id, cpt, dos,
  snapshot_date ORDER BY meta_load_dt DESC NULLS LAST) ... WHERE __rn = 1`.
  A1's legacy snapshot carries two loads (2026-07-01 / 2026-07-02) — the later
  one (charges 110, fee 55) survives. A4's daily rows carry two loads — L4B
  (charges 410) survives.
- **union_value**: `source_generation` is `'legacy_snapshot'` on the legacy
  branch and `'daily'` on the daily branch.
- **NULL alignment**: `fee_amount` (legacy-only) is `CAST(NULL AS INT)` on the
  daily branch; `licn` (daily-only) is `CAST(NULL AS STRING)` on the legacy
  branch.
- **UNION ALL semantics**: A1 appears in BOTH generations with different
  snapshot_dates (part of the pk) — both rows survive; no exclude/coalesce is
  configured.

Expected output: 4 rows — (A1 legacy, fee 55, licn NULL), (A2 legacy),
(A1 daily, licn L1, fee NULL), (A4 daily, licn L4B, fee NULL).
