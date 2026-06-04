# Phase 4 Evaluation: dbt+DuckDB vs Spark for the ingest parity suite

Date: 2026-06-04
Branch: `feat/dbt-runner`
Machine/env: single host, `UV_PROJECT_ENVIRONMENT=/tmp/tsvenv`, `JAVA_HOME=openjdk@17`.
Stacks: duckdb 1.5.0, dbt-core 1.11.11 + dbt-duckdb 1.10.1, pyspark 4.0.1 + Delta 4.0.0.

## Hypothesis under test

> "Running the ingest tests via dbt+duckdb is much faster and easier to
> install/operate locally than via Spark."

Verdict: **TRUE on install/operate footprint and engine speed; PARTLY true on
wall-clock of the test suite as currently written** (the dbt CLI subprocess
wrapper eats most of the duckdb-path test time, not DuckDB itself). Net: the
hypothesis holds. Recommend dbt+duckdb as the default fast inner loop with a thin
Spark truth-gate, per ADR-006/ADR-007.

## 1. Wall-clock (same machine/env)

Both suites cover the same 10 raw->ingest fixtures (the duckdb suite adds 7
sub-second micro-parity unit tests).

| Suite | Tests | Wall-clock |
|---|---|---|
| Spark baseline (`test_spark_baseline.py`) | 10 | **~52-54 s** |
| dbt+DuckDB parity (`test_dbt_duckdb_parity.py`) | 17 (10 fixtures + 7 micro) | **~49 s** |

At the suite level the two are roughly even — but the cost structure is the
opposite, which is the honest part of this story:

### Startup overhead, isolated

| Operation | Cost |
|---|---|
| Spark session `getOrCreate()` (Delta, local[2]) | **5.85 s** |
| Spark first query after session up (JVM/codegen warmup) | **2.18 s** |
| Spark session+first-query total (one-time per suite) | **~8 s** |
| DuckDB `connect()` + first query | **0.067 s** |
| Bare `dbt --version` (CLI import/startup, no project) | **2.7-3.0 s** |
| DuckDB compute on a fixture-scale dedup window | **~0.02 s** |

Reading: the Spark suite pays its ~8 s JVM/session tax **once** (session-scoped
fixture), then each fixture is a fast in-JVM transform. The duckdb suite pays
~0.07 s for the engine but spawns a **fresh `dbt run` subprocess per batch**, and
bare dbt CLI startup alone is ~2.7-3.0 s. So duckdb's per-fixture 3-7 s is almost
entirely dbt-CLI process startup + project parse, NOT DuckDB: the engine itself is
~150x faster than Spark's session (20 ms vs ~3 s for equivalent work).

Implication: the engine claim ("much faster") is unambiguously true; the *current
test harness* doesn't realize it because it shells out to the dbt CLI per batch.
A persistent dbt invocation (single `dbt run`, or the dbt programmatic API, or
batching all fixtures into one run) would collapse the duckdb suite well below the
Spark suite. That is a harness optimization, not an engine limitation.

## 2. Install / operate footprint

| | dbt + DuckDB | PySpark + Delta + JDK |
|---|---|---|
| Install channel | pure `pip`/`uv` | `pip` for pyspark, **out-of-band JDK** (brew/system) + Ivy jar download |
| Python pkgs | duckdb 0.6 MB + native `_duckdb.so` 52 MB; dbt closure ~15 MB | pyspark 460 MB (incl. 442 MB bundled jars) + py4j 0.7 MB |
| Extra runtime jars | none | Delta via Ivy: **~92 MB** in `~/.ivy2` |
| JVM | **none** | **JDK 17/21 required** (~320 MB Cellar install) |
| Rough total on disk | **~67 MB**, all pip | **~870+ MB** + a separately-managed JDK |
| Extra setup steps | `uv sync` | `uv sync` **+ install a compatible JDK + set JAVA_HOME + first-run Ivy resolve** |

DuckDB+dbt is roughly an order of magnitude smaller (~67 MB vs ~870 MB) and has
**zero out-of-band dependencies** — no JVM, no Ivy, no `JAVA_HOME`. Spark needs a
correct JDK installed and pointed-to before anything runs.

## 3. Reliability / operability

The JDK-version fragility is real and observed first-hand:

- The host default JDK is **OpenJDK 26**. Running Spark under it crashes
  immediately: `java.lang.UnsupportedOperationException: getSubject is not
  supported` (`javax.security.auth.Subject.getSubject`). The whole suite is dead
  until `JAVA_HOME` is repointed at **JDK 17**.
- This is a silent landmine: pyspark installs fine, imports fine, and only blows
  up at session creation — so a fresh contributor sees green `pip install` then a
  hard crash. Every Spark command in this repo must carry an explicit
  `JAVA_HOME=.../openjdk@17` prefix to work at all.
- DuckDB has **no equivalent failure mode**: no JVM, no JDK pinning, connects in
  ~67 ms regardless of host Java. Zero reliability tax observed.

## 4. Residual risks (from the parity reviews; re-verified here)

Both are still open — documented, not fixed:

1. **No-format TIMESTAMP offset/Z divergence (real, unguarded).**
   For a column with no UMF format, `cast_column_sql(..., dialect="duckdb")` emits
   `try_cast(v as timestamp)` while `dialect="spark"` emits
   `try_to_timestamp(v)`. Verified empirically: DuckDB **keeps wall-clock and drops
   the offset** — `'2024-01-15 13:45:30+05:30'` and `'2024-01-15T13:45:30Z'` both
   parse to `2024-01-15 13:45:30` — whereas Spark normalizes an offset-bearing
   value to UTC (`+05:30` -> `08:15:30`). There is **no fixture** with offset/Z
   values on a no-format timestamp column, so this path is silently green.
   Action: add an `iso_ts_noformat` fixture with offset/Z values, and EITHER make
   the duckdb no-format timestamp cast honor offsets like Spark, OR document it as
   a known limitation of the no-format path so it is not silently green.

2. **Dedup tie-break under-determined (documented, not fixed).**
   `dedup_window_sql` partitions by PK and orders only by the configured
   `order_by` (default `_load_ts DESC`). The docstring explicitly states that for
   same-PK + same-`order_by` rows, `row_number()` may pick either and the engines
   can disagree; a stricter secondary tie-break is intentionally NOT added (it
   would change the committed byte-for-byte `ingest_sql` goldens). No fixture
   exercises same-PK same-`_load_ts` different-payload.
   Action: add that fixture and EITHER add a deterministic secondary tie-break to
   `dedup_window_sql` OR keep the order_by-unique contract but assert it
   explicitly so the gap is not silently green.

## Refactor guard

The committed byte-for-byte golden suite (`tests/test_golden.py`,
`tests/golden/ingest_sql/` and `tests/golden/dbt_project/`) still passes: **15
passed**. The single cast/dedup seam refactor did not perturb the artifacts.

## Verdict and recommendation

The hypothesis holds. dbt+DuckDB is dramatically lighter to install/operate
(~67 MB pure-pip, no JVM) and the DuckDB engine is far faster than a Spark session
(20 ms vs ~8 s startup), with none of the JDK-version fragility that makes Spark a
real operability tax.

Adopt **dbt+DuckDB as the default fast inner-loop test backend**, with a thin
**Spark truth-gate** retained as the source-of-truth parity oracle (run in CI /
pre-merge, not on every local iteration), consistent with ADR-006 and ADR-007.
Two harness/correctness follow-ups before calling parity airtight: (a) close the
two residual risks above with fixtures, and (b) optionally batch the dbt CLI into
a single `dbt run` (or use dbt's programmatic API) so the local duckdb suite
realizes the engine's speed advantage instead of paying per-batch CLI startup.
