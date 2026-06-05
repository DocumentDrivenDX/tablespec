# Conformance Harness — Acceptance Criteria & Engine Matrix

Status: Approved for implementation on `feat/conformance-harness`.
Scope: a cross-engine conformance harness that proves every supported execution
backend reproduces the **same** typed-ingest / gold-derivation result as the
established Spark-direct oracle, byte-for-byte, under one shared canonicalization.

This document is the **criteria-first** phase. It defines unambiguous,
machine-checkable acceptance for each engine, the canonicalization contract every
engine MUST share, the fixture corpus + tags (including the cases still to add),
and the matrix assertion the harness enforces. Items marked `(NEW)` do not exist
yet and are the deliverable of the later implementation phases on this branch.

> **Run prefix** (ALL python/pytest/dbt/uv commands):
> `UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 SPARK_LOCAL_IP=127.0.0.1 uv run <cmd>`
> PySpark 4.0 runs ONLY under `JAVA_HOME=openjdk@17` (default JDK 26 crashes in
> `getSubject`). For any `dbt-spark` (session) leg, set an **isolated**
> `spark.sql.warehouse.dir` + metastore dir per case for parallel safety.

---

## 1. The oracle (the "previous implementation")

The single source of truth is the **Spark-direct ingest baseline**:
`tablespec.generate_ingest_sql(umf)` executed on Delta-Spark
(`tests/ingest_parity/test_spark_baseline.py:210`). Its canonicalized output is
committed as the **corpus golden** under
`tests/golden/ingest_parity/<fixture>.spark.expected.json`. The gold-derivation
oracle is `SQLPlanGenerator` / `generate_sql_plan`
(`src/tablespec/schemas/sql_generator.py`), whose golden is the canonicalized
result of executing the generated gold SQL on the oracle engine.

Every engine leg compares its canonicalized output to **that same corpus
golden** (never to itself, never to a freshly-recomputed expectation), AND any
two engines that can both run a given case MUST agree **pairwise**. An engine
that cannot run a tier in this environment is `skipif`-gated with an explicit,
visible reason — it is never silently passed.

---

## 2. Engines × fidelity tier × what-it-compares-to × gate

| Engine | Fidelity tier | Executed here? | Compares to | Skip gate |
| --- | --- | --- | --- | --- |
| **SparkDirect** | Oracle / executed (result-parity) | Yes (Delta-Spark, JVM) | IS the corpus golden (writes it under `--update-golden`); all others compare to it | `spark_only`; skip if no JVM / `JAVA_HOME` not openjdk@17 |
| **DbtDuckDB** | Executed (result-parity) | Yes (in-process DuckDB) | corpus golden + pairwise vs every other available engine | `no_spark`; `importorskip("duckdb")`, `importorskip("dbt")`, skip if `dbt` CLI absent |
| **DbtSparkSession** | Executed (result-parity) | Yes (local embedded `dbt-spark[session]`, `method: session`, embedded Hive/Derby) | corpus golden + pairwise | `slow`; skip if `dbt-spark` adapter missing or JVM unavailable; per-case isolated warehouse/metastore dir |
| **SQLPlanGeneratorGold** | Executed (result-parity) — run on BOTH DuckDB AND the Spark session | Yes (both backends, via the dbt-generated gold project so the dialect layer applies) | corpus golden + Spark↔DuckDB equivalence proven pairwise (closes the "gold never run on Spark" gap) | DuckDB leg: `no_spark` + duckdb/dbt present; Spark leg: `slow` + JVM/`dbt-spark` present |
| **DbtDatabricks** | Compile-golden (no cluster) | Compile only | the committed compiled-SQL golden; cast-SQL parity to Spark via the shared renderer | `no_spark`; `dbt compile` only — `dbt run` `skipif` no Databricks workspace |
| **LDP** | Cast-parity + compile-golden + opt-in e2e | Cast-parity + emit-golden executed; e2e opt-in | (a) cast-parity: emitted cast SQL == Spark cast SQL; (b) compile-golden: emitted project text == `tests/golden/ldp/**`; (c) e2e: corpus golden | `no_spark` for (a)+(b); (c) gated behind opt-in `databricks_e2e` marker (`skipif` no Databricks) |

### 2.1 Tier definitions

- **Oracle / executed (result-parity):** generates SQL, executes it on a real
  engine against real CSV data, canonicalizes the resulting table, and that
  canonical form defines (SparkDirect) or must equal (all others) the corpus
  golden. No mocks for the behavior under test.
- **Compile-golden:** `dbt compile` (or LDP text emission) renders deterministic
  SQL/project text that is byte-compared to a committed golden. Proves the
  emitter, not a live run. Used where no cluster exists here (Databricks; LDP
  Databricks runtime).
- **Cast-parity:** the per-column cast expression the backend emits is executed
  in isolation (or string-compared) and must reproduce the EXACT value/NULL
  behavior of the Spark `try_to_timestamp` + Java-token oracle, including the
  sub-second / width-boundary cases the second-resolution canonical form would
  otherwise hide.

### 2.2 Marker plan `(NEW where noted)`

Reuse existing markers (`slow`, `fast`, `no_spark`, `spark_only`, `acceptance`,
`contract`). Add ONE new marker:

- `databricks_e2e` `(NEW)` — opt-in; `skipif` unless a real Databricks workspace
  is configured. Default-deselected so the green suite never depends on a cluster.

Registered in `pyproject.toml [tool.pytest.ini_options].markers` (`--strict-markers`
is on, so it must be declared).

---

## 3. Canonicalization contract `(NEW: extend `tests/ingest_parity/canonical.py`)`

ALL engines MUST canonicalize through the identical `canonical.to_json`. Today
`render_value` pins timestamps to **second** resolution and assumes UTC, which
HIDES sub-second and timezone divergence between engines. The contract is
extended to make that divergence visible while keeping current goldens stable by
default-equivalence on the corpus that has no sub-second data.

Contract (`canonical.to_json` / `render_value` / `canonical_rows`):

1. **Configurable timestamp precision.** `to_json(..., ts_precision: int = 6)`
   threads through to `render_value(value, *, ts_precision=6)`. A
   `datetime`/timestamp renders as `YYYY-MM-DD HH:MM:SS` when `ts_precision == 0`,
   else `YYYY-MM-DD HH:MM:SS.ffffff` truncated (NOT rounded) to `ts_precision`
   fractional digits. **Default is microsecond (6)** so sub-second divergence is
   visible by default; a case may pin `ts_precision=0` only with an explicit,
   documented reason.
2. **Explicit timezone handling.** TZ rendering is explicit, not implicit-UTC.
   A tz-aware `datetime` is first normalized to UTC then rendered with a trailing
   `Z`; a naive `datetime` renders with NO suffix. The two are therefore NEVER
   byte-equal, so a TZ-aware↔naive divergence cannot silently pass. Every engine
   leg pins its session to UTC (`SET TimeZone='UTC'` / Spark `spark.sql.session.timeZone=UTC`)
   so wall-clock values agree before this rendering step.
3. **Identical for all engines.** SparkDirect, DbtDuckDB, DbtSparkSession,
   SQLPlanGeneratorGold (both backends), and the LDP e2e leg import and call the
   SAME `to_json` with the SAME `ts_precision` and the SAME decimal `scales` map.
   Decimals stay fixed at their declared scale; booleans `true`/`false`; NULL ->
   `"NULL"`; rows sorted by all canonical columns. No per-engine canonicalization.
4. **Backward compatibility (explicit, not hand-waved).** Switching the default
   to `ts_precision=6` is NOT byte-identical to the current second-resolution
   goldens: a whole-second `...:SS` becomes `...:SS.000000`. Two compatible paths,
   one MUST be chosen at implementation:
   - **(a) corpus default `ts_precision=0`** — the existing 10 fixtures keep
     pinning second resolution (their goldens are unchanged, byte-for-byte), and
     ONLY the NEW sub-second/tz cases opt into `ts_precision=6`. This preserves
     every committed golden with zero regeneration. **This is the recommended
     default**; the `to_json` signature default is `6`, but the ingest corpus
     parametrization passes `ts_precision=0` explicitly except for `tz`-tagged
     cases.
   - **(b) global `ts_precision=6` + one-time golden migration** — regenerate all
     goldens under `--update-golden` so whole seconds carry `.000000`. This is
     compatibility by MIGRATION (a single reviewed golden churn), not byte
     compatibility of the unchanged files.
   The harness records the chosen precision per case so golden + every engine leg
   compare at one precision.

---

## 4. Fixture corpus, tags, and cases to add

### 4.1 Existing ingest corpus (`tests/fixtures/ingest/`)

`claims_incremental_pk`, `currency_amounts`, `dates_formats`,
`events_incremental_nopk`, `members_snapshot_pk`, `messy_incremental_pk`,
`nopad_formats`, `parity_hardening`, `provider_snapshot`, `types_basic`.
Two-batch fixtures are tracked by `_TWO_BATCH` in `test_spark_baseline.py`.

### 4.2 Tag taxonomy `(NEW: a `tags:` list on each fixture UMF, surfaced as pytest marks/ids)`

- `types` — scalar type coverage (passthrough, numeric, boolean).
- `decimal` — decimal precision / scale / overflow boundaries.
- `datetime` — date/timestamp format parsing.
- `tz` — timezone-aware + sub-second timestamp behavior.
- `incremental` — incremental (merge / append) ingestion.
- `snapshot` — full-snapshot ingestion.
- `pk` / `nopk` — has / lacks a primary key (dedup vs blind-append).
- `multibatch` — 3+ batches / out-of-order `_load_ts` / tie-break / tombstone.
- `gold` — cross-table gold derivation (join/pivot/unpivot/window/etc).

### 4.3 Missing cases to add `(NEW)`

Ingest tier:

1. **`decimal_boundaries`** (`decimal`) — values at `precision`/`scale` limits,
   rounding at scale boundary, and OVERFLOW inputs that must NULL/error
   identically across engines (largest-representable + just-over-precision).
2. **`tz_subsecond_timestamps`** (`datetime,tz`) — tz-aware offsets (`+00:00`,
   `-05:00`, `Z`) AND `.SSS`/`.SSSSSS` fractional seconds; exercises the
   microsecond + explicit-TZ canonicalization so sub-second/TZ divergence is
   visible and must agree.
3. **`multibatch_ooo_tiebreak`** (`incremental,pk,multibatch`) — 3+ batches with
   OUT-OF-ORDER `_load_ts`, an exact-tie `_load_ts` requiring a deterministic
   tie-break, and a **tombstone** (delete-marker) row that removes a prior key.

Gold pattern family (`gold`, executed via `generate_sql_plan` on BOTH backends):

4. **`gold_join`** — multi-table sequential join (member×claims). Generator path:
   `_generate_join_step` (direct/sequential join).
5. **`gold_pivot`** — pivot derivation. Generator path: `_generate_pivot_join`.
6. **`gold_unpivot`** — UNPIVOT base-view derivation. Generator path:
   `_generate_unpivot_base_view`.
7. **`gold_window_aggregation`** — window / pre-aggregation view (`ROW_NUMBER` /
   `RANK` / pre-aggregation). Generator path: `_generate_pre_aggregation_views`.
8. **`gold_survivorship_priority`** — survivorship across `union_sources` via the
   priority-sorted `COALESCE` candidate order (the generator's supported
   survivorship mechanism). Generator path: `_generate_member_universe_view` +
   priority `COALESCE`. (Most-recent / longest-value survivorship is NOT a named
   generator strategy and is out of scope for this case.)
9. **`gold_first_record`** — first-record-per-key selection. Generator path:
   `_generate_first_record_join` (`strategy in ("first", "first_record")`).
10. **`gold_fk_integrity`** — referential-integrity coverage. NOTE: orphan-FK
    validation is NOT emitted by `generate_sql_plan` (FK metadata there only
    drives join planning / join type). FK-integrity is therefore tested at the
    **dbt `relationships` schema-test** tier: `generate_dbt_dag_project` emits the
    `relationships` test and `dbt build`/`dbt test` is asserted to PASS on clean
    data and FAIL on an injected orphan row (the explicit negative). The SparkDirect
    gold join result for the clean data is still the corpus golden; the orphan
    negative is a dbt-test assertion, not a canonical-row comparison.

Each new case ships: `<name>.umf.yaml` (with `tags:`), CSV batch(es), and a
committed corpus golden produced by the SparkDirect oracle under `--update-golden`.

---

## 5. The matrix assertion

For the parametrized product **(case × available-engine)** the harness asserts:

- **A. Golden conformance:** `canonical(engine, case) == read(case.golden)` —
  byte-identical, using the case's pinned `ts_precision` + decimal `scales`. The
  golden is the SparkDirect oracle output (the previous implementation).
- **B. Pairwise agreement:** for any two engines `e1`, `e2` both available for a
  case, `canonical(e1, case) == canonical(e2, case)`. (Transitively implied by A
  when both pass, but asserted explicitly so a shared-golden-but-divergent-render
  bug is localized to the engine pair.)
- **C. Gold Spark↔DuckDB equivalence:** for every `gold` case, the
  `SQLPlanGeneratorGold` output is executed on BOTH DuckDB and the Spark session
  **via the dbt-generated gold project** (so the dialect layer rewrites
  Spark-flavored constructs like `SELECT * EXCEPT (rn)` / `UNPIVOT EXCLUDE NULLS`
  appropriately per backend) and the two canonical forms MUST be equal (and each
  equal to the golden) — explicitly closing the "gold never run on Spark" gap.
- **D. Compile-golden stability:** `DbtDatabricks` `dbt compile` output and LDP
  emitted project text are byte-equal to their committed goldens; LDP cast SQL ==
  Spark cast SQL (cast-parity).
- **E. Skip visibility:** any unavailable (engine, tier) emits a `skip` with an
  explicit reason; the run summary shows skips so a silently-missing engine is
  detectable (never reported as a pass).

Encapsulation (`tests/test_core_encapsulation.py`) and `make check`
(lint + pyright + full suite) MUST stay green; no core→dbt/ldp import is added by
the harness.
