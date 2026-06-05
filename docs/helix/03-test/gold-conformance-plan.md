# Gold Conformance Completion — Per-Item Plan

Branch: `feat/gold-conformance-completion` (off `main`).

This plan promotes the four remaining `pending: true` Gold cases in
`tests/conformance/corpus/cases.yaml` to REAL executed conformance cases, folds
in the generator-branch variants Codex flagged as "insufficient for INTENSIVE",
resolves the single remaining pre-existing xfail, and hardens the opt-in
`databricks_e2e` tier. Each item lists acceptance criteria (Given/When/Then with
the expected canonical result and any negative), the `SQLPlanGenerator` path
exercised, and the LIKELY divergence/bug risk to watch.

## Phase-0 investigation findings (ground truth)

- The matrix (`tests/conformance/test_engine_matrix.py`) has NO `pending` gate.
  It runs every gold case on `SQLPlanGeneratorGold[duckdb]` AND
  `SQLPlanGeneratorGold[spark]` via `engines.py`, then compares each backend's
  canonical output to the golden derived by `_golden_for` →
  `tests/golden/ingest_parity/<case>.spark.expected.json`, and asserts pairwise
  agreement.
- **Verified by running the matrix** on the 4 pending cases
  (`pytest test_engine_matrix.py -k "gold_join or gold_unpivot or gold_first_record or gold_fk_integrity"`):
  `gold_join`, `gold_unpivot`, `gold_first_record` ALREADY PASS on BOTH backends
  against their committed (hand-seeded) goldens (9 passed). `gold_fk_integrity`
  is SKIPPED in the matrix (engines.py:826 — `relationships_schema_test` is not a
  row case) and is ALREADY executed+gating in
  `tests/conformance/test_fk_orphan_enforcement.py` (clean passes, orphan
  `member_id=7` fails via `relationships_claims_member_id` → `FAIL 1`).
- "Promote" therefore means: (a) regenerate each row-gold golden from the Spark
  oracle under `--update-golden` so the committed golden is provably the oracle
  output (not a hand seed), (b) flip `pending: true → false` and pin the
  `golden:` path in `cases.yaml` so `test_corpus_manifest.py` (lines 126-139)
  treats them as EXECUTED/PROMOTED, and (c) add the branch variants — that is
  where new generator bugs are expected to surface (as the first 3 fixed cases
  did).
- `gold_fk_integrity` STAYS relationships-test-only (Codex-confirmed): the matrix
  skips it at `engines.py:826` regardless of the `pending` flag, and adding a
  `claim_enriched`-style target just to force a row golden would duplicate
  `gold_join` and conflate two contracts. Its promotion = drop `pending: true`
  in a way that satisfies the manifest's pending/executed invariant for an
  FK-tier case (it pins no row golden; it is executed by the orphan-FK tier).
- The single remaining pre-existing xfail (found via `pytest -rx`, NOT a Gold
  case) is
  `tests/unit/test_gx_duckdb_spike.py::TestGxDuckdbSqlAlchemy::test_sqla_not_null`
  — a `strict=True` xfail. It STILL reproduces on gx 1.15.1 / duckdb 1.5.0 /
  sqlalchemy 2.0.48: GX's SqlAlchemy execution engine raises `list index out of
  range` inside `resolve_metric_bundle` for the DuckDB dialect, so
  `result.success` is `False` with that exception captured.
- The `databricks_e2e` tier already exists and skips correctly here
  (`databricks_e2e_availability()` → "DATABRICKS_HOST not set",
  `test_ldp_e2e_engine_is_gated_off_here` PASSES). No real cluster — must stay an
  honest skip.

### Verified dialect fact (grounds the GREATEST variant)

Probed locally on duckdb 1.5.0: `GREATEST(10, NULL) → 10`, `GREATEST(NULL, NULL)
→ NULL`, `GREATEST(10, 5) → 10`. DuckDB SKIPS nulls, matching Spark's documented
`greatest` null-skipping. So a GREATEST variant over CONSISTENT numeric types
should AGREE across backends and is a genuine executable case (not a forced
divergence). The residual divergence risk is TYPE COERCION (mixed INT/DECIMAL
candidates) and ordering rules, not the null contract — see item 5 risk.

---

## Item 1 — gold_join (promote + LEFT/INNER + join_filter variant)

`SQLPlanGenerator` path: `_generate_join_step` → `_generate_direct_join`
(sql_generator.py:1309); `join_type.upper()` at :1354; `_rewrite_join_filter`
(:1635) when a `join_filter` is present.

Existing base case (`claim_enriched`, claims→member FK, LEFT join, no filter):
already passes both backends.

- **Given** the committed `gold_join` sources (claims 100/101/102/103 →
  member_id 1/2/1/3; member 1=Alice,2=Bob,3=Carol),
  **When** the generated gold project runs on duckdb AND spark,
  **Then** the canonical `gold_claim_enriched` is exactly the committed golden
  (claim_id, member_id, member_name) = (100,1,Alice),(101,2,Bob),(102,1,Alice),
  (103,3,Carol), byte-identical on both backends and equal to the Spark oracle.

- **LEFT vs INNER + join_filter variant** (new gold case
  `gold_inner_join_filter`, generator `_generate_join_step`; Codex: a SEPARATE
  case, not folded destructively into the base, since the matrix is one
  target-per-case): add an orphan claim whose `member_id` has no member row, and
  a target UMF with `join_type: inner` + a `join_filter` on a member column.
  - **Given** claims with one orphan member_id (e.g. claim 104 → member_id 9, no
    member 9) and a member-side `join_filter` (e.g. `member_status = 'ACTIVE'`),
    **When** run with `join_type: left`,
    **Then** the orphan row survives with NULL member columns AND the filtered-out
    member contributes NULLs (LEFT keeps base rows; filter is in the ON clause).
  - **When** the SAME shape runs with `join_type: inner`,
    **Then** the orphan row and the filtered-out member's claims are DROPPED.
  - Both backends byte-identical; committed golden = Spark oracle output.

**Likely divergence/bug to watch:** `INNER JOIN` itself is low risk (both
dialects accept it). The HIGH risk is `_rewrite_join_filter` (:1635): it blindly
regex-prefixes bare target-column tokens with `target.`. Keep the filter free of
string literals that collide with column names and of bare columns present on
BOTH sides (ambiguous-column error on one dialect). If a filter token is rewritten
inside a quoted literal or becomes ambiguous, FIX the rewrite (skip quoted spans /
qualify both sides) rather than skip — do not paper over.

## Item 2 — gold_unpivot (promote + dedup-latest variant)

`SQLPlanGenerator` path: `_generate_unpivot_base_view` (sql_generator.py:598).
Base path emits `UNPIVOT EXCLUDE NULLS (score FOR source_column IN (q1,q2,q3))`.

- **Given** wide_scores (M1: q1=10,q2=20,q3=30; M2: q1=5,q2=NULL,q3=15),
  **When** the gold project runs on duckdb AND spark,
  **Then** canonical `gold_long_scores` (member_id, source_column, score) =
  (M1,q1,10),(M1,q2,20),(M1,q3,30),(M2,q1,5),(M2,q3,15) — the q2 NULL row for M2
  is EXCLUDED (EXCLUDE NULLS), byte-identical on both backends.

- **dedup-latest variant** (exercises the `dedup_strategy == "latest"` branch at
  sql_generator.py:629, which emits `SELECT * EXCEPT (rn)` after a ROW_NUMBER —
  an UNTESTED branch): add a target with `dedup_strategy: latest` + a PK +
  `meta_load_dt`, and two wide rows per key with different load dates.
  - **Given** two snapshots of M1 with different `meta_load_dt`,
    **Then** only the latest snapshot's unpivoted rows survive, identical on both
    backends.

**Likely divergence/bug to watch:** `UNPIVOT EXCLUDE NULLS` syntax (DuckDB) vs
Spark's `UNPIVOT ... EXCLUDE NULLS`, and especially `SELECT * EXCEPT (rn)` — DuckDB
column-exclusion is `EXCLUDE (col)`, Spark is `EXCEPT (col)`. The dedup branch
emits `* EXCEPT (rn)`; confirm BOTH backends accept it or the generator emits an
explicit column list (the generator already prefers explicit lists elsewhere,
sql_generator.py:1223-1224). If one backend rejects the star-exclusion, FIX the
generator to emit an explicit projection on both.

## Item 3 — gold_first_record (promote + ordering/derived variant)

`SQLPlanGenerator` path: `_generate_first_record_join` (sql_generator.py:1445),
ROW_NUMBER partitioned dedup, `ORDER BY` inferred from target columns (:1481).

- **Given** hub (parent 1,2) and detail (1→first-for-1 [2024-01-01], 1→
  second-for-1 [2024-02-01], 2→only-for-2 [2024-03-01]),
  **When** the gold project runs on duckdb AND spark,
  **Then** canonical `gold_first_detail` (parent_id, detail_value) =
  (1,first-for-1),(2,only-for-2) — first record per parent — byte-identical on
  both backends and equal to the committed golden.

- **deterministic-ordering variant:** the current fixture's "first" is decided by
  the inferred ORDER BY (`_generate_first_record_join` picks a non-PK column when
  no type/name column exists — here `detail_value` or `updated_date`). Pin the
  fixture so the ORDER BY is UNAMBIGUOUS (distinct `updated_date` per row) so the
  "first" is deterministic and identical across backends; add a tie row only if
  the generator's ORDER BY makes it deterministic, else document why ties are
  out of scope (no stable secondary key in the generator).

**Likely divergence/bug to watch:** ROW_NUMBER tie-breaking. If the inferred
ORDER BY is non-unique, duckdb and spark may pick different "first" rows → pairwise
divergence. Keep the order key unique in the fixture. NULLS FIRST/LAST default
ordering differs between dialects on a nullable order column — keep the order
column non-null in the fixture, or assert the generator pins NULLS LAST.

## Item 4 — gold_fk_integrity (promote as relationships-tier, NOT a row case)

`SQLPlanGenerator` path: NONE — `generator: relationships_schema_test`. FK
metadata in `generate_sql_plan` only drives join planning, never an orphan check
(README + acceptance Section 4.3 #10). The orphan check is the dbt `relationships`
schema test emitted by `generate_dbt_dag_project`.

- **Given** claims + member with the `member_id → member.member_id` FK,
  **When** `dbt build` runs the generated project on `claims.clean.csv`,
  **Then** it PASSES and the `relationships_claims_member_id` test executes
  (positive, already in `test_fk_orphan_enforcement.py`).
- **Negative — Given** `claims.orphan.csv` (injected `member_id=7`),
  **When** `dbt build` runs,
  **Then** it FAILS via the relationships test with exactly `FAIL 1` / `Got 1
  result, configured to fail if != 0` (already gating).

**Promotion mechanics:** the matrix (engines.py:826) skips this case as a row
case unconditionally, and `test_corpus_manifest.py` (line 126) forbids a non-
pending gold case from having a `None` golden UNLESS it is `divergence`-gated.
Resolution to KEEP it relationships-only AND non-pending: either (a) keep it
`pending: true` permanently with a manifest note that an FK-tier case is
"executed elsewhere" (least churn but conflates the pending semantics), OR
(b) relax `test_gold_case_sources_present` to treat a `relationships_schema_test`
generator as a THIRD valid non-pending state (executed by the orphan-FK tier, no
row golden). Plan: implement (b) — it is the honest encoding ("executed, not a
row case"), keeps `pending` meaning "golden not yet produced", and the orphan-FK
tier remains the executor. Confirm no other test assumes pending⊕golden for this
case.

**Likely divergence/bug to watch:** none on rows (no row comparison). Watch that
the manifest-invariant change does not let a genuinely-pending row case slip
through ungated — scope the new branch strictly to
`generator == "relationships_schema_test"`.

## Item 5 — gold_survivorship_max_across_sources / GREATEST variant (NEW)

`SQLPlanGenerator` path: `_generate_member_universe_view` (union base) +
`_generate_column_mapping` (:1741) → `max_across_sources` dispatch (:1786) →
`_generate_greatest_mapping` (:1919) which emits `GREATEST(...)` (:1949) or
`COALESCE(GREATEST(...), default)`.

New gold case `gold_survivorship_max_across_sources`, modeled on
`gold_survivorship_priority` (union_sources over system_a/system_b keyed by
member_id) but with a NUMERIC surviving column and `survivorship.strategy:
max_across_sources` over two same-type candidates.

- **Given** system_a (M1:risk_score=10, M3:risk_score=30) and system_b
  (M1:risk_score=25, M2:risk_score=5),
  **When** the gold project runs on duckdb AND spark,
  **Then** canonical `gold_member_universe` (member_id, risk_score) =
  (M1,25),(M2,5),(M3,30) — GREATEST across the two sources per member —
  byte-identical on both backends and equal to the Spark oracle.
- **Negative / edge rows:** include a member present in only ONE source (NULL on
  the other) → GREATEST skips the NULL (verified: duckdb & spark both keep the
  non-null) → that source's value survives; and (optionally) a member NULL in
  both → result NULL. These pin the null contract that is the headline risk.

**Likely divergence/bug to watch:** TYPE COERCION (Codex). `_generate_greatest_
mapping` emits raw `GREATEST(a, b)` with NO per-argument cast (:1949). If the two
candidates resolve to DIFFERENT types (e.g. one INT staging column, one DECIMAL),
duckdb and spark may coerce/round differently → divergent canonical. Mitigation:
keep both candidate columns the SAME declared type in the fixture; if the
generator must support mixed types, FIX it to cast each argument to the target
type before GREATEST (dialect-safe `CAST(... AS <type>)`). Also watch string vs
numeric GREATEST (lexical vs numeric max) — keep the column numeric.

## Item 6 — pivot max_records / ties / NULL-exclusion variant (where natural)

`SQLPlanGenerator` path: `_generate_pivot_join` (sql_generator.py:1367),
`max_records` overflow handling (:1382, :1393, `WHERE rn <= max_records` :1435),
`ROW_NUMBER ... ORDER BY value ASC NULLS LAST` (:1428), `MAX(CASE WHEN rn=i ...)`
(:1397).

Fold into a `gold_pivot`-style variant (the base `gold_pivot` already passes):

- **max_records overflow** — **Given** a key with MORE source records than
  `max_records` (e.g. 5 diagnoses, max_records=3), **Then** only the first 3
  (by the pivot ORDER BY) populate diagnosis_1..3; the overflow is dropped, same
  on both backends.
- **NULL exclusion** — the pivot ORDER BY uses `NULLS LAST`; a key with a NULL
  value column should rank NULLs last so they fall outside `rn <= max_records`
  when there are enough non-nulls.
- **ties** — equal values under the ORDER BY are a determinism risk; pin a unique
  tiebreak in the fixture OR document ties as out of scope (the generator's
  ROW_NUMBER has no secondary key, so an exact tie is non-deterministic across
  backends — keep values distinct in the executable fixture).

**Likely divergence/bug to watch:** `pivot` is a DuckDB RESERVED word — already
fixed (the join CTE is aliased `pivoted`, see cases.yaml gold_pivot note). For
the variant: NULLS LAST ordering parity and tie non-determinism. Reserved-word
re-check for any new target column names (avoid `value`, `pivot`, `order`, etc.).

## Item 7 — MAX_BY / non-window pre-aggregation variant (where natural)

`SQLPlanGenerator` path: `_generate_pre_aggregation_views` (sql_generator.py:816),
`MAX_BY` branch (:834), and the non-window SUM/COUNT/MIN/MAX GROUP BY aggregation
(distinct view name `<t>_agg_grouped`, per the gold_window_aggregation note).

Fold into a `gold_window_aggregation`-style variant (base already passes):

- **non-window SUM/COUNT/MIN/MAX** — **Given** claims per member, **Then** the
  pre-agg view computes e.g. `claim_count = COUNT(*)`, `total_amount = SUM(amount)`,
  `min/max_amount` per member via GROUP BY; joined back to the member universe;
  identical on both backends.
- **MAX_BY** — **Given** claims with an amount + a service_date, **Then**
  `MAX_BY(<col>, amount)` selects the column value at the max amount per member.

**Likely divergence/bug to watch:** `MAX_BY` exists in BOTH duckdb and spark but
TIE behavior (two rows sharing the max `amount`) is implementation-defined and
may diverge — keep the max-key UNIQUE per group in the fixture. SUM over INTEGER
may widen to BIGINT differently; declare the agg column type explicitly and
canonicalize at the declared scale (the engines already pin decimal scale via
`decimal_scales`). Empty-group COUNT (a member with no claims) → 0 vs NULL parity:
the LEFT join + COALESCE must render the same on both backends.

## Item 8 — Resolve the remaining pre-existing xfail (NOT a Gold case)

File: `tests/unit/test_gx_duckdb_spike.py::TestGxDuckdbSqlAlchemy::
test_sqla_not_null` — `@pytest.mark.xfail(strict=True, reason="GX SqlAlchemy
engine MetricResolutionError with DuckDB dialect")`.

Confirmed STILL failing on gx 1.15.1 / duckdb 1.5.0 / sqlalchemy 2.0.48: GX's
`SqlAlchemyExecutionEngine.resolve_metric_bundle` raises `list index out of
range`; `validate(...).success` is `False` with that exception captured in the
result.

- **Given** the DuckDB-backed SqlAlchemy GX batch fixture,
  **When** `ExpectColumnValuesToNotBeNull(column="id")` is validated,
  **Then** the spike's documented finding is asserted POSITIVELY: the validation
  returns `success is False` AND the result carries the `list index out of range`
  / metric-resolution exception (the documented GX-DuckDB dialect gap).

**Resolution:** replace the indefinitely-deferred `strict=True` xfail with a
test that ASSERTS the documented behavior (success False + the captured GX
exception substring). This "resolves" the xfail by pinning the real current GX
behavior with a passing assertion instead of a perpetual expected-failure
placeholder — if a future GX upgrade fixes the dialect, the assertion flips and
forces an intentional update (same gate value as a strict xpass, but green now
and self-documenting). The working Pandas-fallback tests are unchanged.

**Likely risk to watch:** GX result-object shape — assert on the public
`result.success` and the serialized exception text (stable substring `index out
of range`), not on private internals, so the assertion is robust to GX patch
noise.

## Item 9 — Harden the opt-in databricks_e2e tier (must SKIP cleanly here)

Wiring: `databricks_e2e_availability()` (engines.py:242) gates on
`DATABRICKS_HOST`; `LdpDatabricksE2EEngine` (tier `e2e`, engines.py:1307) is
enumerated by `all_engines()`; `test_ldp_databricks_e2e` (parametrized over
ingest cases) and `test_ldp_e2e_engine_is_gated_off_here` already exist; the
`databricks_e2e` marker is registered in `pyproject.toml`. Confirmed PASSING:
the gate test passes and the e2e parametrizations SKIP with the DATABRICKS_HOST
reason.

- **Given** no `DATABRICKS_HOST` in the env (this harness),
  **When** the e2e tier is collected/run,
  **Then** every e2e leg SKIPS with an explicit reason mentioning
  `DATABRICKS_HOST` (never silently passed, never claims real cluster execution),
  AND `test_ldp_e2e_engine_is_gated_off_here` asserts the gate is real.
- **Negative regression guard — Given** the gate were accidentally made
  "available" without a workspace, **Then** the gate test FAILS loudly.

**Hardening planned:** (a) keep the honest-skip contract; (b) ensure the NEW gold
cases are NOT silently outside any e2e/coverage accounting — extend the e2e
gate's reason and the gating guard so the tier's skip is asserted to cover the
gold corpus too (or explicitly document that gold e2e is out of scope for the LDP
ingest-only e2e engine, so a reader is not misled into thinking gold runs on a
cluster). Do NOT implement real cluster execution (no workspace).

**Likely risk to watch:** a green-on-nothing illusion — the existing
`test_required_engine_actually_executed` / skipped-but-green guards must continue
to prove the LOCAL row engines actually executed; the e2e tier must remain
skipped-with-reason, not flipped to a no-op pass.

---

## Cross-cutting policy (all items)

- When a promoted case or variant FAILS on a backend, FIX the generator
  (dialect-safe SQL, correct semantics on duckdb AND spark) and make it PASS on
  both — do NOT skip or add a permanent xfail. Only `divergence`-gate (strict
  xfail) a genuinely documented, out-of-scope limitation, with an explicit
  justification in `cases.yaml`.
- Reuse the shared `tests/ingest_parity/canonical.to_json` at each case's pinned
  `ts_precision`; no per-engine canonicalization drift.
- Keep lint (ruff) + pyright + the FULL suite green; preserve
  `tests/test_core_encapsulation.py`.
- Commit per item.
- Goldens are written ONLY by the oracle engine under `--update-golden`
  (SparkDirect for ingest; `SQLPlanGeneratorGold[spark]` for gold).
