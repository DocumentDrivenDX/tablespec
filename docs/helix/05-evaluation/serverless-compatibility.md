# Serverless / Spark-Connect Compatibility Evaluation

Date: 2026-06-06
Branch: `feat/helix-align`
Run prefix (all python/pytest/dbt commands):
`UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 SPARK_LOCAL_IP=127.0.0.1 uv run <cmd>`

**Traceability**: PRD FR-5.1/5.2 (native profiler), FR-7.7/7.8 (Connect-safe
validation), FR-20.1–20.4 (runtime platform). Vision outcome: *"the same UMF runs
first-class on both classic Spark and Databricks serverless / Spark Connect."*
Decisions under test: ADR-009 (native profiler over PyDeequ), ADR-010 (serverless
runtime model — never assume a JVM `SparkContext`), ADR-011 (Connect-safe GX via
native-executor routing).

## Hypothesis under test

> "tablespec's profiling and validation run first-class on Databricks serverless /
> Spark Connect (env-v3, Python 3.12) — not just 'doesn't crash', but returns the
> *same answers* as classic Spark — with no JVM, no `JAVA_HOME`, and no PyDeequ."

**Verdict: TRUE for the native profiler and the native GX-suite executor /
`TableValidator` path, proven both locally (Sail Spark-Connect, no JVM) and on real
Databricks serverless.** The GX-`add_spark` engine and the GX *custom* expectations
(pandas-backed) are NOT Connect-safe and are deliberately routed away from Connect
(classic-Spark only). The single most important finding: GX `add_spark` does not
error on Connect — it *silently returns wrong answers* — so the fix is
per-expectation routing to a native DataFrame-API executor, not a try/except.

## 1. The runtime model (env-v3 / Python 3.12 / no JVM SparkContext)

Databricks serverless and Spark Connect run an **env-v3 / Python 3.12** client with
**no JVM `SparkContext`** on the client side. Library code that assumes one fails on
Connect:

| Assumption | Where it bites | Failure mode on Connect |
|---|---|---|
| PyDeequ profiling needs the JVM | legacy `DeequToUmfMapper` | hard dependency on a JVM that serverless does not expose |
| GX `add_spark` / `SparkDFExecutionEngine` uses classic `F.lit`/`F.count` | `validation/native_executor.py:1-31` documents it | the classic functions assert `SparkContext._active_spark_context is not None`; on Connect the assertion fails, the error is **swallowed**, and every data-scanning expectation returns `success=False` / `result={}` |
| `pyspark.sql.functions` dispatches by a process-global `is_remote()` | `profiling/native_profiler.py:55-75` `_functions_for` | when classic + Connect sessions coexist (the local Sail lane), the process-global picks the wrong engine for a given DataFrame |

The substrate that makes Connect first-class (ADR-010, FR-20.x):

- **Per-session capability probing** — `session.get_capabilities` probes a tiny
  expression (e.g. `try_to_timestamp` with a format works on classic Spark 4.0 but
  not on some Connect builds), cached by `id(spark)` (`session.py:47-66`).
- **Engine-correct functions dispatch** — both the profiler and the native executor
  select the `functions` module from the **DataFrame in hand**
  (`_functions_for(df)`, `native_profiler.py:55`), never from a process global, so
  expressions stay session-correct when classic and Connect sessions coexist.
- **No JVM / no `JAVA_HOME`** on the Connect path — the local Sail lane uses a
  Rust-based Spark Connect server (pysail), so it runs with zero JVM setup.

## 2. The matrix — what is proven where

Five execution substrates exercise the compatibility surface. "Proven" = an executed
test asserts *correctness* (clean → pass, dirty → fail with the exact
`unexpected_count` / observed value), not merely non-crashing.

| Engine / lane | JVM? | `JAVA_HOME`? | Native profiler | Native GX executor / `TableValidator` | GX `add_spark` | GX custom expectations | Evidence |
|---|---|---|---|---|---|---|---|
| **DuckDB** (fast inner loop) | no | no | n/a (SQL engine, not Spark) | n/a (df-API path is Spark) | n/a | n/a | conformance ingest/gold parity; ADR-006 |
| **Classic Spark 4.0** (local, JDK 17) | yes | **required** (JDK 17; default JDK 26 crashes in `getSubject`) | proven | proven via `add_spark` (classic path) | proven (classic only) | proven (classic only, pandas paths OK on a JVM session) | full `make test`; conformance row tier |
| **Sail Spark-Connect** (local, pysail, no JVM) | **no** | **no** | **proven** | **proven** (routed to native executor) | not used (routed away) | not run (pandas paths not Connect-compatible) | `tests/unit/test_profiler_connect_sail.py`, `tests/unit/test_validation_connect_sail.py` |
| **Databricks serverless / Spark Connect** (env-v3, Py 3.12) | no | no | **proven** (real serverless) | **proven** (same native operations) | not used | not used | the same native operations run on real serverless (test docstrings; ADR-010/011 "proven on real serverless") |
| **Real-Databricks e2e** (opt-in) | n/a | n/a | — | dbt-databricks + LDP deploy/execute | — | — | gated by `DATABRICKS_HOST` (`e2e/gating.py:48`); `tests/conformance/test_*_databricks_*` |

Notes on the matrix:

- **The native paths are the Connect-safe ones.** The native profiler
  (`NativeSparkProfiler`) and the native GX executor (`GXSuiteExecutor` →
  `_execute_native` → `native_executor`) are proven Connect-safe on Sail *and* on
  real serverless. The Sail lane runs with **no JVM and no `JAVA_HOME`** — it is the
  cheap local proxy for serverless.
- **GX `add_spark` is classic-Spark only — by routing, not by accident.**
  `GXSuiteExecutor._is_connect_dataframe` (`gx_executor.py:212`) detects Connect
  DataFrames by module (`pyspark.sql.connect.*`) and routes them to the native path
  (`gx_executor.py:237`); classic DataFrames keep the unchanged `add_spark` engine.
- **GX *custom* expectations are not yet Connect-safe.** They exercise pandas code
  paths (e.g. `validate_domain_type`'s `df[col].dropna()`) that are not
  Spark-Connect-compatible, so the default GX unit harness deliberately stays on
  **classic Spark** (`tests/conftest.py:417-447`). On the Connect path these are
  re-evaluated through the native custom-validators (`_evaluate_custom_native`,
  `gx_executor.py:298`), failing closed if a type is unsupported. GX-on-Connect for
  the full custom-expectation surface is acknowledged future work.

## 3. What the Sail lane locks in (correctness, not just liveness)

The local Sail lane asserts the native paths are *correct*, and it pinned two
prod-neutral profiler fixes that DataFusion (Sail's engine) surfaced and that real
serverless would otherwise hit silently:

1. **Scalar `percentile_approx` per probe** — DataFusion only accepts a scalar
   percentile (`test_profiler_connect_sail.py` docstring).
2. **Type-aware exact `count_distinct` for float/double** — DataFusion does not
   implement `approx_distinct` for `Float64`, so the profiler uses an exact distinct
   count for floating columns.

For validation, `test_validation_connect_sail.py` runs **every supported expectation
type** against a clean dataset (expect `success=True`) and a dirty dataset (expect
`success=False` with the exact `unexpected_count`) on a genuine Spark Connect
session — proving the native executor is the *correct* answer the swallowed
`add_spark` path would have hidden.

## 4. Dependency model (no JVM, no Deequ, test-only dbt/pysail)

| Concern | Decision | Evidence |
|---|---|---|
| Profiling | Native Spark-SQL aggregations; **PyDeequ removed** as the default (legacy mapper only) | ADR-009; FR-5.1/5.5; `native_profiler.py` |
| Local Connect lane | **pysail** (Rust Spark Connect server, no JVM) in the **dev (test-only) group** | `pyproject.toml` dev group; `tests/conftest.py:315` |
| dbt | **test-only** (executes generated projects in conformance); never a user-facing extra; `src` never imports dbt | `pyproject.toml:51` NOTE + dev group; `test_src_never_imports_dbt` |
| `[spark]` extra | still the boundary for the pure-Python core; extended by ADR-010 to also forbid assuming a `SparkContext` | ADR-003 (Evolution), ADR-010 |

## 5. Residual risks / honest gaps

1. **GX custom expectations on Connect (open).** The pandas-backed custom GX
   expectations are not Connect-safe; the default GX harness stays on classic Spark
   and the Connect path re-routes through native custom-validators that fail closed
   on unsupported types. Full custom-expectation parity on Connect is future work.
2. **`add_spark` silent-false-negative is a *routing* guarantee.** Correctness on
   Connect depends on `_is_connect_dataframe` correctly classifying the DataFrame.
   A DataFrame from a Connect build that did **not** surface under
   `pyspark.sql.connect.*` would be mis-routed to `add_spark` and silently fail. The
   classifier is module-prefix based; it is the single point that must stay correct.
3. **Real-serverless leg is opt-in.** The `DATABRICKS_HOST`-gated e2e tier
   (`e2e/gating.py:48`) is skipped with an explicit reason when unset, so local CI is
   green without a workspace — but that means the *real-serverless* assertions are
   only exercised when a workspace is configured. The Sail lane is the always-on
   local proxy; it is a proxy, not the workspace.
4. **Capability probing is per-session, cached by `id(spark)`.** If a session object
   is reused after a capability-relevant reconfiguration, the cached probe could go
   stale. Acceptable today (sessions are not reconfigured mid-run), noted for
   awareness.

## Verdict and recommendation

The hypothesis holds for the paths that matter: **native profiling and native GX
validation are first-class and *correct* on Spark Connect / Databricks serverless**,
with no JVM, no `JAVA_HOME`, and no PyDeequ — proven locally on Sail and on real
serverless. Keep the routing discipline (Connect → native, classic → `add_spark`)
as the load-bearing invariant, treat `_is_connect_dataframe` as a correctness-critical
seam, and track GX custom-expectation Connect parity as the one remaining gap.
Maintain the always-on Sail lane as the local serverless proxy and the
`DATABRICKS_HOST` e2e leg as the periodic real-workspace truth-gate.
