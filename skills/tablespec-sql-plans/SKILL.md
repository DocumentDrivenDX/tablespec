---
name: tablespec-sql-plans
description: Authoring derived/gold tables and generating SQL plans - table_type generated UMFs with derivation candidates, generate_sql_plan in views or cte mode, base_table_strategy (unpivot, union_sources, union_branches), per-branch filters and dedup, alternative join paths, and DuckDB/Spark byte-identical SQL. Use when defining a derived table from source UMFs or shaping the SQL plan a dbt or LDP gold model consumes.
---

# Tablespec SQL Plans

Use this skill for authoring derived (gold) tables as UMF and shaping the SQL
plans generated from them. It covers behavior and gotchas; the exhaustive
strategy and metadata tables live in `docs/guide/sql-plans.md`.

## What a SQL plan is

`generate_sql_plan(target_umf, related_umfs, mode=...)` compiles a *generated*
table's UMF — derivation candidates, relationships, metadata — into executable
SQL. `mode="views"` (the default) emits a sequence of
`CREATE OR REPLACE TEMPORARY VIEW` statements; `mode="cte"` emits a single
`WITH ... SELECT`, the form dbt and LDP gold models consume.

```python
from tablespec import generate_sql_plan

sql = generate_sql_plan(target_umf, related_umfs, mode="cte")
```

The emitted SQL is engine-agnostic and must stay that way: conformance tests
pin DuckDB↔Spark byte-parity on every gold path. Do not emit engine-specific
syntax — e.g. spell null-safe equality as `(a = b OR (a IS NULL AND b IS
NULL))`, not `<=>` (Spark-only), and avoid `SELECT * EXCEPT/EXCLUDE`
(dialect-divergent). Both filters and expressions run through
`{{template_var}}` substitution via the `template_vars` argument.

## Authoring a generated table

Derived tables are `table_type: "generated"` UMFs whose columns carry a
`derivation` (`UMFColumnDerivation`) with prioritized `candidates`
(`DerivationCandidate`):

```python
UMFColumn(
    name="claim_id",
    data_type="VARCHAR",
    length=50,
    nullable=Nullable(MD=False, MP=False, ME=False),
    derivation=UMFColumnDerivation(
        strategy="primary_key",
        candidates=[
            DerivationCandidate(table="Medical_Claims", column="claim_id", priority=1),
        ],
    ),
)
```

Candidate field semantics (each optional unless noted):

- `table` (required) and `column` or `expression` (one required) — where the
  value comes from; `expression` is a SQL expression instead of a bare column.
- `priority` (required, `>= 1`) — survivorship order; 1 wins.
- `join_filter` — extra predicate ANDed into the JOIN ON clause for this
  table; used when joining the same table multiple times with different filters.
- `table_instance` — unique alias for a table+filter combination; required to
  disambiguate self-joins / multi-instance joins of the same table.
- `row_filter` — WHERE applied to source rows before aggregation or union
  branching.
- `order_by` — window ORDER BY columns (all DESC); switches aggregation to
  `ROW_NUMBER()` picking the full max row, and drives per-branch dedup.
- `union_value` — literal emitted for this column in the UNION branch for this
  table (typically a source discriminator flag).

Do not author an empty `candidates: []` list — omit `derivation` entirely for
columns with no source; they compile to `CAST(NULL AS <type>)`.

## Base table strategies

`metadata.base_table_strategy` selects how the plan's base view is built.

**Unset** — plain base: `SELECT <required columns> FROM base_table`, filtered
by `base_table_filter` if set.

**`unpivot`** — UNPIVOTs the base table's `unpivot_columns` into rows; requires
both `unpivot_columns` and `unpivot_value_column` in metadata. With
`dedup_strategy: latest` and a `primary_key`, the *wide* row is deduped before
the UNPIVOT — deduping after would collapse all unpivoted rows per key to one.

**`union_sources`** — key-only universe: UNION of each source table's join key
across `source_tables`, with per-source pre-aggregation views joined back.
Unlike `union_branches`, it unions keys, not full rows.

**`union_branches`** — one full SELECT branch per source table (base plus
`union_base_tables`, falling back to `source_tables`), combined with
`union_type: union_all` (default) or `union` (dedupes exact rows). Requires a
resolvable `base_table`.

**`aggregate_source`** — the base view is itself a GROUP BY over `base_table`;
requires `metadata.base_table`.

## union_branches specifics

Every branch projects the full target column set, mapped through that source
table's own candidates:

- a candidate with `union_value` emits `CAST(<literal> AS <type>)` — a
  per-branch constant;
- otherwise the branch table's lowest-priority-number candidate supplies the
  `expression` or `column`;
- a column with no candidate for a branch emits `CAST(NULL AS <type>)`, so the
  UNION stays column-aligned when sources have different columns.

A branch's WHERE clause comes from the single distinct `row_filter` among that
table's candidates — this is how generation cutovers are expressed (legacy feed
`< DATE`, daily feed `>=`). Candidates of one branch carrying *different*
`row_filter` values is a plan-time error, as are conflicting `order_by` lists.
`base_table_filter` additionally applies to the base branch (ANDed).

With `dedup_strategy: latest` and a candidate `order_by`, each branch is
deduplicated before the union via `ROW_NUMBER() OVER (PARTITION BY <primary
key> ORDER BY <order_by> DESC NULLS LAST)`; every `primary_key` column must be
branch-projected. `NULLS LAST` is pinned because DuckDB and Spark default NULL
placement differently.

Overlap handling: `union_exclude_base: true` anti-joins union branches against
the base branch's post-filter, post-dedup rows on the primary key;
`union_coalesce_base: true` instead merges overlapping rows with
`COALESCE(base.col, union.col)` (base wins; supports exactly one union table).
Both require a primary key and raise without one. Joins to other tables still
work after a union base view — join keys are projected into every branch.

## Filters and joins

- `base_table_filter` — WHERE on the base view, before any joins; bare
  base-table columns only. `final_filter` — WHERE after final assembly, wrapped
  as a subquery so it can reference derived output columns. Put predicates in
  `base_table_filter` when they can go there; it filters earliest and cheapest.
- `final_dedup: distinct` collapses exact-duplicate output rows;
  `final_dedup: latest` requires `final_dedup_keys` (or `primary_key`) plus
  `final_dedup_order_by`.
- `base_join_column` overrides the auto-inferred base join key *and* every
  relationship declared outgoing from the base table — set it only when every
  join out of the base should use that one key.
- Candidate-level `join_filter` takes precedence over `ForeignKey.join_filter`
  because candidate filters are keyed by `(table, table_instance)` and can
  disambiguate multi-instance joins; FK-level filters fill the gaps.
- `OutgoingRelationship.alternative_joins` — additional join paths tried in
  declared priority order (the relationship's own columns are priority 1).
  Compiled as a **UNION-of-joins**, never `ON (a = b OR c = d)`: Spark plans
  OR-joins as a BroadcastNestedLoopJoin, a known join-explosion hazard. Each
  path becomes an inner-join branch, one match per base key survives by branch
  priority, and the result joins back null-safely. Alternative-join columns
  are validated against the actual tables at plan time.

## Error philosophy

Misconfiguration fails at *plan time* with `ValueError` — missing union
tables, conflicting row_filters or order_bys, exclude/coalesce without a
primary key, alternative-join columns that don't exist — rather than emitting
broken SQL. Declarative fields the selected strategy does not consume (e.g.
`union_base_tables` without `base_table_strategy: union_branches`, or
`base_table_filter` under `unpivot`/`union_sources`) log a warning and are
ignored so foreign-authored specs still load; the warning names the missing
switch.

## Where plans land

`compile_umfs(..., gold_targets=["Claims_Summary"])` writes a single-target
plan artifact per listed table to `gold_plan/<target>.plan.sql` (views mode).
The dbt gold and LDP gold model renderers invoke the same generator in `cte`
mode, so the model body is the plan — do not hand-edit generated gold SQL;
change the UMF and regenerate.

## Related

- `tablespec-pipeline` — compiling UMFs into runtime artifacts and running them.
- `tablespec-umf-authoring` — split-YAML spec layout and UMF authoring.
- Full reference: `docs/guide/sql-plans.md` in the repository, and
  https://documentdrivendx.github.io/tablespec/
