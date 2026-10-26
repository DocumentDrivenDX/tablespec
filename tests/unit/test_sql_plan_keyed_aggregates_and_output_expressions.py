# SPDX-License-Identifier: MIT OR Apache-2.0
"""Keyed pre-aggregation (``metadata.base_join_column`` as the join-back key)
and output expressions (``derivation.output_expression``), executed end to end
in DuckDB so the assertions are on rows, not on SQL text."""

from __future__ import annotations

import duckdb
import pytest
import sqlglot
from pydantic import ValidationError

from tablespec.models.umf import (
    UMF,
    DerivationCandidate,
    UMFColumn,
    UMFColumnDerivation,
    UMFMetadata,
)
from tablespec.schemas.sql_generator import generate_sql_plan

pytestmark = pytest.mark.fast


def _umf(name, columns, *, primary_key=None, metadata=None) -> UMF:
    return UMF(
        version="1.0",
        table_name=name,
        columns=columns,
        primary_key=primary_key,
        metadata=metadata,
    )


def _src(name, cols, *, primary_key=None) -> UMF:
    return _umf(
        name,
        [UMFColumn(name=c, data_type=t) for c, t in cols.items()],
        primary_key=primary_key,
    )


def _col(name, data_type="VARCHAR", **cand) -> UMFColumn:
    return UMFColumn(
        name=name,
        data_type=data_type,
        source="derived",
        derivation=UMFColumnDerivation(
            candidates=[DerivationCandidate(priority=1, **cand)]
        ),
    )


def _out(name, expression, data_type="VARCHAR") -> UMFColumn:
    return UMFColumn(
        name=name,
        data_type=data_type,
        source="derived",
        derivation=UMFColumnDerivation(output_expression=expression),
    )


def _run(
    target: UMF, related: dict[str, UMF], ddl: list[str], cols: list[str]
) -> list[tuple]:
    """Execute the plan in DuckDB; rows projected to *cols*, sorted."""
    sql = generate_sql_plan(target, related, mode="cte").strip().rstrip(";")
    duck = sqlglot.transpile(sql, read="spark", write="duckdb")[0]
    with duckdb.connect() as con:
        for stmt in ddl:
            con.execute(stmt)
        cur = con.execute(duck)
        names = [d[0] for d in cur.description]
        rows = [tuple(r[names.index(c)] for c in cols) for r in cur.fetchall()]
    return sorted(rows, key=lambda r: tuple("" if v is None else str(v) for v in r))


# ---------------------------------------------------------------------------
# keyed pre-aggregation
# ---------------------------------------------------------------------------


class TestKeyedPreAggregation:
    """A target with several rows per key (no primary key) pulls a per-key
    aggregate from another table by naming the key in base_join_column."""

    def _corpus(self, history_pk):
        lines = _src("lines", {"sl": "INTEGER", "cpt": "VARCHAR"})
        history = _src(
            "history",
            {"seq": "INTEGER", "sl": "INTEGER", "stage": "VARCHAR"},
            primary_key=history_pk,
        )
        target = _umf(
            "lines_enriched",
            [
                _col("sl", "INTEGER", table="lines", column="sl"),
                _col("cpt", table="lines", column="cpt"),
                _col("last_stage", table="history", expression="MAX_BY(stage, seq)"),
                _col("first_seq", "INTEGER", table="history", expression="MIN(seq)"),
            ],
            metadata=UMFMetadata(base_table="lines", base_join_column="sl"),
        )
        return target, {"lines": lines, "history": history}

    DDL = [
        "CREATE TABLE lines(sl INTEGER, cpt VARCHAR)",
        "INSERT INTO lines VALUES (1,'a'),(1,'b'),(2,'c')",
        "CREATE TABLE history(seq INTEGER, sl INTEGER, stage VARCHAR)",
        "INSERT INTO history VALUES (1,1,'open'),(2,1,'formal'),(1,3,'x')",
    ]

    @pytest.mark.parametrize("history_pk", [["sl", "seq"], ["seq", "sl"]])
    def test_every_row_of_a_key_gets_the_key_aggregate(self, history_pk):
        """The source groups on the named key even when it is not the
        source's first primary-key column (["seq", "sl"])."""
        target, related = self._corpus(history_pk)
        rows = _run(target, related, self.DDL, ["sl", "cpt", "last_stage", "first_seq"])
        assert rows == [
            (1, "a", "formal", 1),
            (1, "b", "formal", 1),
            (2, "c", None, None),
        ]

    def test_missing_join_key_raises(self):
        """No PK and no base_join_column: fail at generation (backlog: the
        skipped view used to leave a dangling LEFT JOIN)."""
        target, related = self._corpus(None)
        target.metadata = UMFMetadata(base_table="lines")
        related["history"].columns = [
            UMFColumn(name=n, data_type="VARCHAR") for n in ("stage", "seq")
        ]
        with pytest.raises(ValueError, match="cannot determine the join column"):
            generate_sql_plan(target, related)

    def test_aggregated_source_is_not_also_joined_row_level(self):
        target, related = self._corpus(["seq", "sl"])
        sql = generate_sql_plan(target, related)
        assert "GROUP BY sl" in sql
        assert "ON base.sl = agg.sl" in sql
        assert "First Record" not in sql and "Direct Join" not in sql

    def test_primary_key_target_unchanged(self):
        """Without base_join_column the join-back key is still the PK."""
        target, related = self._corpus(["sl", "seq"])
        target.metadata = UMFMetadata(base_table="lines")
        target.primary_key = ["sl"]
        assert "ON base.sl = agg.sl" in generate_sql_plan(target, related)


# ---------------------------------------------------------------------------
# output expressions
# ---------------------------------------------------------------------------


class TestOutputExpressions:
    DDL = [
        "CREATE TABLE src(id INTEGER, a VARCHAR, b VARCHAR)",
        "INSERT INTO src VALUES (1,'x',NULL),(2,NULL,'y'),(3,NULL,NULL),(3,'z',NULL)",
    ]

    def _target(self, *extra, metadata=None) -> tuple[UMF, dict[str, UMF]]:
        src = _src("src", {"id": "INTEGER", "a": "VARCHAR", "b": "VARCHAR"})
        cols = [
            # declared out of dependency order on purpose: output keeps this order
            _out("label", "CONCAT(final_value, ':', chain)"),
            _col("id", "INTEGER", table="src", column="id"),
            _col("chain", table="src", expression="COALESCE(a, b)"),
            _out("final_value", "CASE WHEN chain = 'x' THEN 'override' ELSE chain END"),
            *extra,
        ]
        return (
            _umf("t", cols, metadata=metadata or UMFMetadata(base_table="src")),
            {"src": src},
        )

    def test_layered_expressions_over_sibling_outputs(self):
        target, related = self._target()
        rows = _run(target, related, self.DDL, ["id", "chain", "final_value", "label"])
        assert rows == [
            (1, "x", "override", "override:x"),
            (2, "y", "y", "y:y"),
            (3, None, None, None),
            (3, "z", "z", "z:z"),
        ]

    def test_final_filter_and_dedup_see_output_columns(self):
        target, related = self._target(
            metadata=UMFMetadata(
                base_table="src",
                final_filter="final_value IS NOT NULL",
                final_dedup="latest",
                final_dedup_keys=["id"],
                final_dedup_order_by="label DESC",
            )
        )
        rows = _run(target, related, self.DDL, ["id", "final_value"])
        assert rows == [(1, "override"), (2, "y"), (3, "z")]

    def test_string_literal_is_not_a_reference(self):
        """'chain' inside a literal must not create a dependency (or a cycle)."""
        target, related = self._target(_out("note", "CONCAT('label', id)"))
        sql = generate_sql_plan(target, related)
        assert "AS note" in sql

    def test_cycle_is_an_error(self):
        target, related = self._target(_out("p", "q"), _out("q", "p"))
        with pytest.raises(ValueError, match="cycle"):
            generate_sql_plan(target, related)

    def test_self_reference_is_an_error(self):
        target, related = self._target(_out("p", "COALESCE(p, chain)"))
        with pytest.raises(ValueError, match="references itself"):
            generate_sql_plan(target, related)

    def test_mutually_exclusive_with_candidates(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            UMFColumnDerivation(
                output_expression="a",
                candidates=[DerivationCandidate(table="src", column="a", priority=1)],
            )

    def test_empty_expression_rejected(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            UMFColumnDerivation(output_expression="  ")
