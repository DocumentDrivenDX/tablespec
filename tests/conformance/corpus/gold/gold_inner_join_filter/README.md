# gold_inner_join_filter

INNER-join + `join_filter` variant of the direct sequential join (sibling of
`gold_join`). Exercises `SQLPlanGenerator._generate_direct_join` with
`join_type=inner` AND `_rewrite_join_filter`.

Files:
- `claims.umf.yaml`, `member.umf.yaml` — source tables. The claims FK declares
  `join_type: inner`. `member` carries `plan_type` / `region` for the filter.
- `claim_ppo_enriched.umf.yaml` — the gold target. The `member_name` derivation
  candidate carries the adversarial `join_filter`
  `plan_type = 'PPO' AND UPPER(region) <> 'no region here'`.
- `claims.raw.csv`, `member.raw.csv` — real source rows (claim 104 is an orphan;
  member 2 is HMO).

## What it proves

1. **INNER vs LEFT contrast.** `join_type=inner` DROPS the orphan claim
   (`member_id=9`, no member row), and the filter `plan_type='PPO'` DROPS the HMO
   member's claim (101). Surviving rows are claims 100, 102, 103 — observably
   different from the LEFT base (`gold_join`), so neither branch is vacuous.

2. **`_rewrite_join_filter` quote-span correctness.** The filter contains a
   both-sides-ambiguous bare column (`plan_type`), a function call
   (`UPPER(region)`), AND the column-name token `region` INSIDE a string literal
   (`'no region here'`). The rewriter must qualify the bare tokens
   (`target.plan_type`, `target.region`) while leaving the literal verbatim. The
   pre-fix rewriter corrupted the literal to `'no target.region here'` on BOTH
   backends; the fixed (quote-span-aware) rewriter preserves it.

## Golden

The committed golden `tests/golden/ingest_parity/gold_inner_join_filter.spark.expected.json`
is the Spark-backend `SQLPlanGeneratorGold` oracle output, produced under
`--update-golden`. The matrix runs the generated gold project on BOTH DuckDB and
the Spark session and asserts byte-identical agreement with that golden.
