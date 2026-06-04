# LDP as a Sibling Emitter on the Shared Core (PROTOTYPE / experimental)

> **Status: PROTOTYPE — experimental.** This is exploratory work that runs AFTER
> the dbt-roadmap audit. It exists to PROVE the core is target-agnostic by emitting
> a second backend from the same inputs. It does **not** touch or change
> `tablespec.dbt`, `tablespec.core` semantics, or the direct-SQL path, and it makes
> **no** claim of running on a real warehouse (see "Honest limits").

## What this is

`tablespec.ldp` is a second backend, parallel to `tablespec.dbt`, that emits a
**Lakeflow Declarative Pipelines (LDP)** project — LDP is the rebrand of Delta
Live Tables (DLT). It is fed by exactly the same core seam the dbt emitter uses:

- the logical-plan IR / `NodeRegistry` (`tablespec.core.registry`, promoted here
  from `tablespec.dbt.registry` because it is framework-agnostic IR construction),
- `build_ingest_select` + `cast_column_sql` (the single cast source of truth),
- the `TableRenderer` Protocol (`tablespec.core.relations`) — implemented by a new
  `LdpRefRenderer` that emits LDP dataset references instead of dbt `{{ ref() }}`.

The point is architectural: if a genuinely different target (declarative streaming
on Databricks, no local runner, MERGE replaced by APPLY CHANGES, tests replaced by
inline EXPECTATIONS) drops onto the same core without forking the cast layer or the
ref-rewriting, the core seam is the real product — the emitters are thin.

## The frame: declared datasets, not an ordered script

The dbt/direct paths produce an **ordered** artifact: a SQL script (or a dbt DAG dbt
runs top-to-bottom). LDP inverts this — you **declare** datasets and **Databricks
owns** the DAG, ordering, incrementalisation, and orchestration. The emitter's job
is therefore to declare each dataset with the right *materialization* and let the
platform schedule it.

## The mapping (what LDP absorbs)

| Our model | dbt / direct path | LDP dataset |
|---|---|---|
| raw landing | `source('raw', raw_<t>)` over an external table | `CREATE OR REFRESH STREAMING TABLE raw_<t> AS SELECT * FROM STREAM read_files(<path>, format => ...)` — continuous file ingestion |
| ingested, incremental **+ pk** | dedup-latest window **+ MERGE** (hand-written) | `CREATE OR REFRESH STREAMING TABLE ingested_<t> ( <EXPECTATIONS> );` then `APPLY CHANGES INTO ingested_<t> FROM (SELECT <casts> FROM STREAM raw_<t>) KEYS (<pk>) SEQUENCE BY <order_by>` — **Databricks owns the upsert + latest-per-key** |
| ingested, incremental **no pk** | blind `INSERT INTO` / dbt append | `STREAMING TABLE` that appends the cast SELECT over the raw STREAM (no KEYS) |
| ingested, **snapshot** | full `INSERT OVERWRITE` / dbt `table` | `MATERIALIZED VIEW` (full reload) |
| gold | `SQLPlanGenerator` plan + dbt `{{ ref() }}` | `MATERIALIZED VIEW` with the **same** `SQLPlanGenerator` plan, refs rendered as bare LDP dataset names by `LdpRefRenderer` |
| validation (GX / dbt tests) | post-hoc `schema.yml` generic tests / GX suite | **inline** `CONSTRAINT <name> EXPECT (<predicate>) ON VIOLATION <action>` |

So LDP **absorbs** four things our hand-rolled pipeline carried explicitly:

1. **Ordering + the runner** — gone; declared datasets, platform-scheduled DAG.
2. **The dedup window + MERGE** — replaced by `APPLY CHANGES ... KEYS ... SEQUENCE BY`.
3. **Validation as a separate step** — replaced by inline `EXPECTATIONS`.
4. **Batch file ingestion** — replaced by streaming `read_files` autoloader.

The CASTS in every dataset body are `cast_column_sql` output via
`build_ingest_select` — **identical** to the dbt/direct paths. The cast layer is
shared, not duplicated (proven by a cross-engine duckdb parity test).

## EXPECTATIONS: ON VIOLATION semantics

Derived from UMF nullability / primary_key / `accepted_values` expectations and
their stage/severity/blocking meta (`ExpectationMeta`):

- non-nullable column / primary-key column → `EXPECT (<col> IS NOT NULL)` →
  `ON VIOLATION FAIL UPDATE` (a typed pipeline must not admit nulls in a key).
- `expect_column_values_to_be_in_set` → `EXPECT (<col> IS NULL OR <col> IN (...))`,
  with the action derived from meta: `blocking` is authoritative for *aborting* —
  only `blocking: true` → **FAIL UPDATE**. A non-blocking check never aborts: with
  `severity in {critical, error, warning}` it → **DROP ROW** (quarantine the bad
  row), and `severity: info`/unset → **WARN** (omit `ON VIOLATION`; keep the row,
  record the metric — LDP's default/expect behaviour). This avoids two failure
  modes codex flagged: a non-blocking check silently dropping data, and an explicit
  `blocking: false` being overridden to FAIL by a high severity.

**Honest gap, surfaced not faked:** uniqueness (PK / unique_constraints) and FK
relationships are **not** row-local predicates, so LDP cannot express them as a
single-dataset `CONSTRAINT`. The emitter writes them as **comments** stating the
intent and where enforcement actually comes from (uniqueness ← `APPLY CHANGES KEYS`
for an incremental dataset; for a snapshot dataset the comment says it is *not*
enforced). It never masquerades them as a constraint.

## Example generated SQL

Raw landing (streaming autoloader):

```sql
CREATE OR REFRESH STREAMING TABLE raw_claims
COMMENT 'Raw landing for claims (continuous file ingestion).'
AS SELECT *
FROM STREAM read_files(
  '${landing_path}/claims',
  format => 'csv'
);
```

Ingested, incremental + pk (EXPECTATIONS + APPLY CHANGES; casts are the shared
`cast_column_sql`; the blocking `status` enum is `FAIL UPDATE`):

```sql
-- uniqueness intent: PRIMARY KEY (claim_id) is enforced by APPLY CHANGES ... KEYS (latest-per-key upsert).
-- relationship intent: member_id -> ingested_member.member_id (referential integrity needs the parent dataset; not a row-local EXPECT).
CREATE OR REFRESH STREAMING TABLE ingested_claims
(
  CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT accepted_values_status EXPECT (status IS NULL OR status IN ('PAID', 'DENIED', 'PENDING')) ON VIOLATION FAIL UPDATE
);

APPLY CHANGES INTO ingested_claims
FROM (
  SELECT
        cast(nullif(trim(regexp_replace(claim_id, '^\$', '')), '') as INT)               AS claim_id,
        cast(nullif(trim(regexp_replace(member_id, '^\$', '')), '') as INT)              AS member_id,
        cast(nullif(trim(regexp_replace(claim_amount, '^\$', '')), '') as DECIMAL(18,2)) AS claim_amount,
        status                                                                            AS status
  FROM STREAM raw_claims
)
KEYS (claim_id)
SEQUENCE BY _load_ts;
```

Gold (materialized view; the SQLPlanGenerator plan with bare LDP dataset refs —
`ingested_claims`, `ingested_member` — instead of `{{ ref() }}`):

```sql
CREATE OR REFRESH MATERIALIZED VIEW gold_enriched
(
  CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS
WITH
disposition_base AS (
  SELECT claim_id, member_id FROM ingested_claims
),
...
LEFT JOIN ingested_member target ON base.member_id = target.member_id
...
SELECT * FROM enriched;
```

## Trade-offs

- **Databricks lock-in.** `STREAMING TABLE`, `APPLY CHANGES`, `read_files`,
  `MATERIALIZED VIEW` and `EXPECT ... ON VIOLATION` are Databricks/LDP-specific.
  The dbt path stays portable (duckdb locally, Databricks/Snowflake in prod); LDP
  does not.
- **No local loop.** There is no open-source LDP runner. The dbt path has a full
  local duckdb develop/test loop (and our e2e tests use it). LDP can only be run on
  a Databricks pipeline, so this prototype is text-generation only.
- **Less explicit control.** APPLY CHANGES / declarative ordering means the platform
  owns the merge + DAG; we trade the transparent hand-written MERGE/window for
  platform behaviour we cannot unit-test locally.
- **Uniqueness / FK are weaker.** Expressed as comments, not enforced constraints
  (LDP has no row-local UNIQUE / referential `EXPECT`).

## Honest limits (what is NOT covered)

- **No real-Databricks e2e.** There is no Databricks in this environment, so the
  generated LDP SQL is **not executed**. No claim of a working pipeline is made.
- **Streaming runtime untested.** `read_files` autoloader, `APPLY CHANGES`
  semantics, continuous/incremental updates, and `ON VIOLATION` enforcement are
  **not** exercised — only the generated SQL's structure is.
- **No LDP parser/linter** in this env to even statically validate the SQL.

## What IS tested (JVM-free, real where it can be)

- **Golden** SQL for the representative multi-table fixture (raw + ingested
  incremental+pk + gold join) and the snapshot + no-pk modes.
- **Structural/functional**: APPLY CHANGES `KEYS` = primary_key and `SEQUENCE BY`
  = order_by; materialization matches `ingestion.mode`; EXPECTATIONS carry the
  correct `ON VIOLATION` from UMF blocking/severity; gold refs resolve to the right
  upstream datasets; unknown relation / cycle fail closed (negative paths).
- **Cross-engine cast parity (REAL duckdb)**: the LDP ingested cast SELECT is
  character-identical to the dbt path's `IngestSelect.select_block` AND, run on real
  duckdb over the same raw rows, produces the same canonical result — proving the
  cast layer is shared, not forked.
- **Encapsulation** (`tests/test_core_encapsulation.py`): core never imports
  `tablespec.ldp`; `tablespec.dbt` and `tablespec.ldp` never import each other; LDP
  is fed only by the core seam and imports no Databricks/Spark runtime to generate.
```
