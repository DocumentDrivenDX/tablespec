# SQL Plan Generation

`generate_sql_plan` (and the underlying `SQLPlanGenerator`) compiles a
*generated* table's UMF — its derivation candidates, relationships, and
metadata — into an executable SQL plan: a sequence of
`CREATE OR REPLACE TEMPORARY VIEW` statements (`mode="views"`) or a single
`WITH ... SELECT` statement (`mode="cte"`, the form dbt and LDP gold models
consume). The emitted SQL is engine-agnostic and executes verbatim on both
DuckDB and Spark; the conformance corpus pins this on every gold path.

```python
from tablespec import generate_sql_plan

sql = generate_sql_plan(target_umf, related_umfs, mode="cte")
```

See [Happy Path §5](happy-path.md) for the basic derived-table flow. This page
documents the plan-shaping metadata controls.

## Base-view strategies

`metadata.base_table_strategy` selects how the plan's base view
(`disposition_base`) is built:

| Strategy | Base view |
|----------|-----------|
| *(unset)* | `SELECT <required columns> FROM base_table` |
| `unpivot` | UNPIVOT `unpivot_columns` into rows (optionally deduped, see below) |
| `union_sources` | Key-only universe: UNION of each source table's join key |
| `union_branches` | One full SELECT branch per source table, combined with UNION ALL / UNION |

### `union_branches`

The base table plus each table in `union_base_tables` (falling back to
`source_tables`) becomes one UNION branch. Unlike `union_sources` (which only
unions *keys*), every branch projects the **target column set**, each column
mapped through that source table's own derivation candidates:

- a candidate with `union_value` emits `CAST(<literal> AS <type>)` — a
  per-branch constant, typically a source discriminator;
- otherwise the branch table's lowest-priority candidate supplies the
  `expression` or `column`;
- a column with no candidate for the branch emits `CAST(NULL AS <type>)`, so
  the UNION stays column-aligned when sources have different columns.

```yaml
metadata:
  base_table: bronze_inventory_detail
  base_table_strategy: union_branches
  union_base_tables: [bronze_halo_daily_inventory]
  union_type: union_all          # or 'union' to dedupe exact rows
  dedup_strategy: latest         # per-branch window dedup (see below)
```

**Per-branch filtering.** A branch's WHERE clause comes from the single
distinct `row_filter` among that table's candidates — this is how generation
cutovers are expressed (legacy feed `file_date < DATE '2026-07-20'`, daily feed
`>=`). Candidates of one branch carrying *different* `row_filter` values is an
error. `base_table_filter` additionally applies to the base branch (ANDed with
its row_filter).

**Per-branch dedup.** With `dedup_strategy: latest` and a candidate `order_by`,
each branch is deduplicated before the union:

```sql
ROW_NUMBER() OVER (
  PARTITION BY <target primary_key>
  ORDER BY <order_by> DESC NULLS LAST
) ... WHERE __rn = 1
```

Every `primary_key` column must be branch-projected; conflicting `order_by`
lists within a branch raise. `NULLS LAST` is pinned because DuckDB and Spark
default NULL placement differently.

**Overlap handling.** `union_exclude_base: true` anti-joins each union branch
against the base branch's *post-filter, post-dedup* rows on the target primary
key (rows already present in the base are dropped). `union_coalesce_base: true`
instead merges overlapping rows: base-only rows pass through, overlapping rows
take `COALESCE(base.col, union.col)` (base wins; primary-key, meta, and
`union_value` columns always come from the base side), union-only rows pass
through. Coalesce supports exactly one union table — the overlap semantics are
pairwise. Both modes require a primary key and raise without one.

Joins to *other* tables still work after a union base view: join key columns
are projected into every branch (typed NULL where a source lacks them).

## Base and final filters

- `base_table_filter` — WHERE on the base view, before any joins. Bare
  base-table columns only; filters earliest and cheapest.
- `final_filter` — WHERE applied *after* final assembly, so it can reference
  derived output columns. The assembly is wrapped
  (`SELECT ... FROM (<assembly>) _final WHERE ...`) because a same-level WHERE
  cannot reference SELECT aliases.
- `final_dedup: distinct` — emits `SELECT DISTINCT *` over the final assembly,
  collapsing exact-duplicate rows produced by join fan-out.

Both filters run through `{{template_var}}` substitution.

## Join controls

- `base_join_column` — overrides the auto-inferred base join key. Also
  overwrites `source_column` on every relationship declared outgoing from the
  base table: the field exists precisely when the auto-selected key is wrong,
  and declared relationships carry that same wrong key. Set it only when every
  join out of the base should use one key.
- `ForeignKey.join_filter` — extra predicate ANDed into the JOIN ON clause.
  Candidate-level `join_filter` (on `DerivationCandidate`) takes precedence
  when both are present, because candidate filters are keyed by
  `(table, table_instance)` and can disambiguate multi-instance joins;
  FK-level filters fill the gaps.
- `OutgoingRelationship.alternative_joins` — additional join paths tried in
  declared priority order (the relationship's own `source_column/target_column`
  is priority 1). Emitted as a **UNION-of-joins**, not `ON (a = b OR c = d)`:
  Spark plans OR-joins as a BroadcastNestedLoopJoin, which is a known
  performance hazard. Instead each path becomes an inner-join branch over the
  distinct base keys, branches are UNIONed with a `__branch_priority` literal,
  one match per base key survives (`ROW_NUMBER` ordered by branch priority),
  and the result is joined back null-safely — spelled as
  `(a = b OR (a IS NULL AND b IS NULL))` because `<=>` is Spark-only.

```yaml
relationships:
  outgoing:
    - target_table: payer_xref
      source_column: payor_claim_number
      target_column: pcn
      alternative_joins:
        - source_column: nsa_dispute_number
          target_column: dispute_no
```

## Error handling philosophy

Misconfiguration fails at *plan time* with `ValueError` (missing union tables,
conflicting row_filters/order_bys, exclude/coalesce without a primary key,
alternative-join columns that don't exist). Declarative fields that the
selected strategy does not consume (e.g. `union_base_tables` without
`base_table_strategy: union_branches`) log a warning and are ignored, so
fork-authored specs load — the warning names the missing switch.
