---
ddx:
  id: FEAT-019
---

# FEAT-019: SQL Generator CTE Mode

**Status**: Implemented
**Priority**: P1
**Feature ID**: FEAT-019
**Owner**: Platform / Compilation
**Covered PRD Subsystem(s)**: Multi-Target Emission
**Covered PRD Requirements**: FR-19.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Add a `mode` parameter to `SQLPlanGenerator` that produces a single `WITH...SELECT` statement using Common Table Expressions instead of sequential `CREATE OR REPLACE TEMPORARY VIEW` statements.

The current view-based approach in `schemas/sql_generator.py`:

- Requires sequential script execution (statements depend on prior views).
- Cannot be embedded in dbt models or other single-statement contexts.
- Forces duplicate joins for diamond dependencies in the dependency graph.
- Prevents query engine optimization across view boundaries.

CTE mode produces a single statement that query engines can optimize holistically.

## Components

### SQLPlanGenerator CTE Mode (`src/tablespec/schemas/sql_generator.py`)

The existing `generate_sql_plan()` function signature is:

```python
generate_sql_plan(table_umf, related_umfs, *, template_vars=None, table_resolver=None)
```

This feature adds a new `mode` parameter (proposed, not yet implemented):

```python
# Current behavior (default) -- produces CREATE OR REPLACE TEMPORARY VIEW statements
sql = generate_sql_plan(table_umf, related_umfs, mode="views")
# CREATE OR REPLACE TEMPORARY VIEW ...
# CREATE OR REPLACE TEMPORARY VIEW ...
# SELECT ...

# Proposed new mode
sql = generate_sql_plan(table_umf, related_umfs, mode="cte")
# WITH
#   step_1 AS (...),
#   step_2 AS (...)
# SELECT ...
```

Both modes produce semantically equivalent results for any valid UMF input.

### Diamond Deduplication (`src/tablespec/schemas/sql_generator.py`)

In CTE mode, diamond dependencies (where multiple downstream steps reference the same upstream step) are handled by emitting each CTE once in the `WITH` clause, then referencing it by name from multiple downstream CTEs. This avoids the duplicate join problem present in view mode without requiring materialization.

### Materialization Guidance

Not all intermediates are suitable as pure CTEs. Steps that perform 1:N deduplication via `ROW_NUMBER()`, pivots, or aggregations should be materialized (temporary tables or views) because re-executing them from a CTE reference would be expensive and potentially non-deterministic. Simple 1:1 joins and filters can remain as pure CTEs since they are cheap to re-evaluate if the query engine chooses not to factor them out.

### Semantic Equivalence Testing

Semantic equivalence testing: both modes produce identical query results when executed against DuckDB with identical source data. DuckDB is used as a dev/test dependency for this verification.

Golden file tests for representative CTE outputs (~15 cases covering linear chains, diamond dependencies, fan-out/fan-in patterns).
## User Stories

- [US-032 — Generate a Single-Statement SQL Plan](../user-stories/US-032-generate-single-statement-sql-plan.md)

## Source

- `src/tablespec/schemas/sql_generator.py` (SQLPlanGenerator)

## Dependencies

- ADR-006 (DuckDB for semantic equivalence testing)
