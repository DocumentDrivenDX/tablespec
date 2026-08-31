"""Consumer wiring for the PR-18 model fields in SQL plan generation.

Covers: base_table_filter, base_join_column, final_filter, final_dedup,
union_branches (union_base_tables / source_tables fallback, union_type,
union_exclude_base, union_coalesce_base, union_value, per-branch row_filter
and dedup), ForeignKey.join_filter, and OutgoingRelationship.alternative_joins.
"""

from __future__ import annotations

import logging

import pytest
import sqlglot

from tablespec.models.umf import (
    UMF,
    Cardinality,
    DerivationCandidate,
    ForeignKey,
    OutgoingRelationship,
    Relationships,
    RelationshipSummary,
    UMFColumn,
    UMFColumnDerivation,
    UMFMetadata,
)
from tablespec.schemas.relationship_resolver import RelationshipResolver
from tablespec.schemas.sql_generator import SQLPlanGenerator, generate_sql_plan

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _card(type_: str, notation: str) -> Cardinality:
    parts = notation.split(":")
    return Cardinality(
        type=type_,
        notation=notation,
        source_multiplicity=parts[0],
        target_multiplicity=parts[1],
    )


def _source_umf(table: str, columns: dict[str, str]) -> UMF:
    return UMF(
        version="1.0",
        table_name=table,
        columns=[UMFColumn(name=n, data_type=t) for n, t in columns.items()],
    )


def _canon(sql: str) -> str:
    """Canonicalize SQL via sqlglot so formatting/case differences vanish."""
    return sqlglot.parse_one(sql, read="spark").sql(
        dialect="spark", normalize=True, pretty=True, comments=False
    )


# ---------------------------------------------------------------------------
# Fixtures: plain base + joined table
# ---------------------------------------------------------------------------


@pytest.fixture
def disputes_umf() -> UMF:
    return UMF(
        version="1.0",
        table_name="disputes",
        primary_key=["arbit_id"],
        columns=[
            UMFColumn(name="arbit_id", data_type="VARCHAR"),
            UMFColumn(name="payor_claim_number", data_type="VARCHAR"),
            UMFColumn(name="nsa_dispute_number", data_type="VARCHAR"),
            UMFColumn(name="status", data_type="VARCHAR"),
        ],
        relationships=Relationships(
            outgoing=[
                OutgoingRelationship(
                    target_table="payer_xref",
                    source_column="payor_claim_number",
                    target_column="pcn",
                    type="foreign_to_primary",
                    confidence=0.9,
                    cardinality=_card("one_to_one", "1:0..1"),
                ),
            ],
            summary=RelationshipSummary(
                total_relationships=1,
                total_incoming=0,
                total_outgoing=1,
                hub_score=5.0,
            ),
        ),
    )


@pytest.fixture
def payer_xref_umf() -> UMF:
    return _source_umf(
        "payer_xref",
        {"pcn": "VARCHAR", "dispute_no": "VARCHAR", "payer_name": "VARCHAR"},
    )


def _simple_target(
    *,
    metadata: UMFMetadata | None = None,
    relationships: Relationships | None = None,
    extra_columns: list[UMFColumn] | None = None,
) -> UMF:
    columns = [
        UMFColumn(
            name="arbit_id",
            data_type="VARCHAR",
            derivation=UMFColumnDerivation(
                strategy="primary_key",
                candidates=[
                    DerivationCandidate(table="disputes", column="arbit_id", priority=1)
                ],
            ),
        ),
        UMFColumn(
            name="payer_name",
            data_type="VARCHAR",
            derivation=UMFColumnDerivation(
                candidates=[
                    DerivationCandidate(
                        table="payer_xref", column="payer_name", priority=1
                    )
                ],
            ),
        ),
    ]
    return UMF(
        version="1.0",
        table_name="gold_disputes",
        table_type="generated",
        primary_key=["arbit_id"],
        metadata=metadata,
        relationships=relationships,
        columns=columns + (extra_columns or []),
    )


# ---------------------------------------------------------------------------
# base_table_filter / base_join_column
# ---------------------------------------------------------------------------


class TestBaseTableFilter:
    def test_filter_emitted_as_base_view_where(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(base_table_filter="status <> 'VOID'")
        )
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        base_view = sql.split("STEP 1")[0]
        assert "WHERE status <> 'VOID'" in base_view

    def test_no_filter_no_where(self, disputes_umf, payer_xref_umf):
        target = _simple_target()
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        base_view = sql.split("STEP 1")[0]
        assert "WHERE" not in base_view

    def test_template_vars_substituted(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(base_table_filter="client_id = {{client_id}}")
        )
        gen = SQLPlanGenerator(template_vars={"client_id": "42"})
        sql = gen.generate_for_table(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        assert "WHERE client_id = 42" in sql

    def test_warns_when_strategy_does_not_consume(self, caplog):
        source = _source_umf(
            "events",
            {"event_id": "VARCHAR", "value_a": "VARCHAR", "value_b": "VARCHAR"},
        )
        target = UMF(
            version="1.0",
            table_name="unpivoted_events",
            table_type="generated",
            primary_key=["event_id"],
            metadata=UMFMetadata(
                base_table="events",
                base_table_strategy="unpivot",
                unpivot_columns=["value_a", "value_b"],
                unpivot_value_column="value",
                base_table_filter="value_a IS NOT NULL",
            ),
            columns=[
                UMFColumn(
                    name="event_id",
                    data_type="VARCHAR",
                    derivation=UMFColumnDerivation(
                        strategy="primary_key",
                        candidates=[
                            DerivationCandidate(
                                table="events", column="event_id", priority=1
                            )
                        ],
                    ),
                ),
                UMFColumn(
                    name="value",
                    data_type="VARCHAR",
                    derivation=UMFColumnDerivation(
                        candidates=[
                            DerivationCandidate(
                                table="events", column="value", priority=1
                            )
                        ],
                    ),
                ),
            ],
        )
        with caplog.at_level(logging.WARNING):
            generate_sql_plan(target, {"events": source})
        assert any(
            "base_table_filter" in r.message and "does not consume" in r.message
            for r in caplog.records
        )


class TestBaseJoinColumn:
    def test_overrides_join_source_column(self, disputes_umf, payer_xref_umf):
        # Without the override, the declared rel joins on payor_claim_number
        target = _simple_target(
            metadata=UMFMetadata(base_join_column="nsa_dispute_number")
        )
        resolver = RelationshipResolver(
            {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        plan = resolver.resolve_plan(target)
        assert plan.join_sequence[0]["source_column"] == "nsa_dispute_number"

    def test_overrides_synthesized_join_key(self, disputes_umf):
        # lookup_tbl has no declared rel from disputes -> synthesized join;
        # without the override it would join on the disputes pk (arbit_id)
        no_rel_base = disputes_umf.model_copy(update={"relationships": None})
        lookup = UMF(
            version="1.0",
            table_name="lookup_tbl",
            primary_key=["payor_claim_number"],
            columns=[
                UMFColumn(name="payor_claim_number", data_type="VARCHAR"),
                UMFColumn(name="extra", data_type="VARCHAR"),
            ],
        )
        target = _simple_target(
            metadata=UMFMetadata(
                base_table="disputes", base_join_column="payor_claim_number"
            ),
            extra_columns=[
                UMFColumn(
                    name="extra",
                    data_type="VARCHAR",
                    derivation=UMFColumnDerivation(
                        candidates=[
                            DerivationCandidate(
                                table="lookup_tbl", column="extra", priority=1
                            )
                        ],
                    ),
                ),
            ],
        )
        target.columns = [c for c in target.columns if c.name != "payer_name"]
        resolver = RelationshipResolver({"disputes": no_rel_base, "lookup_tbl": lookup})
        plan = resolver.resolve_plan(target)
        assert plan.join_sequence[0]["source_column"] == "payor_claim_number"

    def test_projected_in_base_view(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(base_join_column="nsa_dispute_number")
        )
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        base_view = sql.split("STEP 1")[0]
        assert "nsa_dispute_number" in base_view


# ---------------------------------------------------------------------------
# final_filter / final_dedup
# ---------------------------------------------------------------------------


class TestFinalFilterAndDedup:
    def test_final_filter_wraps_assembly(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(final_filter="payer_name IS NOT NULL")
        )
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        final = sql.split("FINAL ASSEMBLY")[1]
        assert ") _final" in final
        assert "WHERE payer_name IS NOT NULL" in final

    def test_final_dedup_distinct(self, disputes_umf, payer_xref_umf):
        target = _simple_target(metadata=UMFMetadata(final_dedup="distinct"))
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        final = sql.split("FINAL ASSEMBLY")[1]
        assert "SELECT DISTINCT *" in final
        assert ") _final" in final
        assert "WHERE" not in final

    def test_combined(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(
                final_filter="payer_name IS NOT NULL", final_dedup="distinct"
            )
        )
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        final = sql.split("FINAL ASSEMBLY")[1]
        assert "SELECT DISTINCT *" in final
        assert "WHERE payer_name IS NOT NULL" in final

    def test_absent_output_unchanged(self, disputes_umf, payer_xref_umf):
        target = _simple_target()
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        final = sql.split("FINAL ASSEMBLY")[1]
        assert "_final" not in final
        assert "DISTINCT" not in final

    def test_synthetic_path_supported(self):
        target = UMF(
            version="1.0",
            table_name="synthetic_tbl",
            table_type="generated",
            metadata=UMFMetadata(final_dedup="distinct"),
            columns=[UMFColumn(name="flag", data_type="BOOLEAN", default=True)],
        )
        sql = generate_sql_plan(target, {})
        assert "SELECT DISTINCT *" in sql
        assert ") _final" in sql

    def test_cte_mode_single_statement(self, disputes_umf, payer_xref_umf):
        target = _simple_target(
            metadata=UMFMetadata(
                final_filter="payer_name IS NOT NULL", final_dedup="distinct"
            )
        )
        sql = generate_sql_plan(
            target,
            {"disputes": disputes_umf, "payer_xref": payer_xref_umf},
            mode="cte",
        )
        assert sql.count(";") == 1
        assert len(sqlglot.parse(sql, read="spark")) == 1
        assert len(sqlglot.parse(sql, read="duckdb")) == 1


# ---------------------------------------------------------------------------
# ForeignKey.join_filter
# ---------------------------------------------------------------------------


class TestForeignKeyJoinFilter:
    def _fk_relationships(self, join_filter: str) -> Relationships:
        return Relationships(
            foreign_keys=[
                ForeignKey(
                    column="payer_name",
                    references_table="payer_xref",
                    references_column="pcn",
                    join_filter=join_filter,
                )
            ]
        )

    def test_fk_join_filter_emitted_in_on_clause(self, disputes_umf, payer_xref_umf):
        target = _simple_target(relationships=self._fk_relationships("client_id = 2"))
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        step_1 = sql.split("STEP 1")[1].split("FINAL ASSEMBLY")[0]
        assert "AND client_id = 2" in step_1

    def test_candidate_level_filter_wins(self, disputes_umf, payer_xref_umf):
        target = _simple_target(relationships=self._fk_relationships("client_id = 2"))
        for col in target.columns:
            if col.name == "payer_name" and col.derivation:
                col.derivation.candidates[0].join_filter = "region = 'WEST'"
        sql = generate_sql_plan(
            target, {"disputes": disputes_umf, "payer_xref": payer_xref_umf}
        )
        step_1 = sql.split("STEP 1")[1].split("FINAL ASSEMBLY")[0]
        assert "region = 'WEST'" in step_1
        assert "client_id = 2" not in step_1


# ---------------------------------------------------------------------------
# alternative_joins
# ---------------------------------------------------------------------------


def _alt_join_base(alternative_joins: list[dict[str, str]]) -> UMF:
    return UMF(
        version="1.0",
        table_name="disputes",
        primary_key=["arbit_id"],
        columns=[
            UMFColumn(name="arbit_id", data_type="VARCHAR"),
            UMFColumn(name="payor_claim_number", data_type="VARCHAR"),
            UMFColumn(name="nsa_dispute_number", data_type="VARCHAR"),
        ],
        relationships=Relationships(
            outgoing=[
                OutgoingRelationship(
                    target_table="payer_xref",
                    source_column="payor_claim_number",
                    target_column="pcn",
                    type="foreign_to_primary",
                    confidence=0.9,
                    cardinality=_card("one_to_one", "1:0..1"),
                    alternative_joins=alternative_joins,
                ),
            ],
            summary=RelationshipSummary(
                total_relationships=1,
                total_incoming=0,
                total_outgoing=1,
                hub_score=5.0,
            ),
        ),
    )


class TestAlternativeJoins:
    ALT = [{"source_column": "nsa_dispute_number", "target_column": "dispute_no"}]

    def test_resolver_carries_alternative_joins(self, payer_xref_umf):
        base = _alt_join_base(self.ALT)
        resolver = RelationshipResolver(
            {"disputes": base, "payer_xref": payer_xref_umf}
        )
        plan = resolver.resolve_plan(_simple_target())
        assert plan.join_sequence[0]["alternative_joins"] == self.ALT

    def test_resolver_validates_source_column(self, payer_xref_umf):
        base = _alt_join_base(
            [{"source_column": "no_such_col", "target_column": "dispute_no"}]
        )
        resolver = RelationshipResolver(
            {"disputes": base, "payer_xref": payer_xref_umf}
        )
        with pytest.raises(ValueError, match="no_such_col"):
            resolver.resolve_plan(_simple_target())

    def test_resolver_validates_target_column(self, payer_xref_umf):
        base = _alt_join_base(
            [{"source_column": "nsa_dispute_number", "target_column": "nope"}]
        )
        resolver = RelationshipResolver(
            {"disputes": base, "payer_xref": payer_xref_umf}
        )
        with pytest.raises(ValueError, match="nope"):
            resolver.resolve_plan(_simple_target())

    def test_resolver_requires_both_keys(self, payer_xref_umf):
        base = _alt_join_base([{"source_column": "nsa_dispute_number"}])
        resolver = RelationshipResolver(
            {"disputes": base, "payer_xref": payer_xref_umf}
        )
        with pytest.raises(ValueError, match="source_column and target_column"):
            resolver.resolve_plan(_simple_target())

    def _generate(self, payer_xref_umf: UMF, mode: str = "views") -> str:
        base = _alt_join_base(self.ALT)
        return generate_sql_plan(
            _simple_target(),
            {"disputes": base, "payer_xref": payer_xref_umf},
            mode=mode,
        )

    def test_union_of_joins_shape(self, payer_xref_umf):
        sql = self._generate(payer_xref_umf)
        assert "base_keys AS (" in sql
        assert "SELECT DISTINCT" in sql
        assert "1 AS __branch_priority" in sql
        assert "2 AS __branch_priority" in sql
        assert "ON b.payor_claim_number = target.pcn" in sql
        assert "ON b.nsa_dispute_number = target.dispute_no" in sql
        assert "ORDER BY __branch_priority" in sql
        assert "WHERE __rn = 1" in sql

    def test_branches_combined_with_union_not_union_all(self, payer_xref_umf):
        sql = self._generate(payer_xref_umf)
        step_1 = sql.split("STEP 1")[1].split("FINAL ASSEMBLY")[0]
        assert "\n  UNION\n" in step_1
        assert "UNION ALL" not in step_1

    def test_null_safe_join_back_is_portable(self, payer_xref_umf):
        sql = self._generate(payer_xref_umf)
        assert (
            "(base.payor_claim_number = m.__match_key_payor_claim_number "
            "OR (base.payor_claim_number IS NULL "
            "AND m.__match_key_payor_claim_number IS NULL))"
        ) in sql
        assert "<=>" not in sql
        assert "* EXCEPT" not in sql
        assert "/*+" not in sql

    def test_base_keys_scans_disposition_base(self, payer_xref_umf):
        sql = self._generate(payer_xref_umf)
        assert "FROM disposition_base\n)" in sql.replace(
            "  FROM disposition_base", "FROM disposition_base"
        )

    def test_no_alternatives_byte_identical_direct_join(self, payer_xref_umf):
        base_with = _alt_join_base([])
        sql = generate_sql_plan(
            _simple_target(), {"disputes": base_with, "payer_xref": payer_xref_umf}
        )
        assert "base_keys" not in sql
        assert "__branch_priority" not in sql
        assert "LEFT JOIN payer_xref target" in sql

    def test_cte_mode_single_statement_both_dialects(self, payer_xref_umf):
        sql = self._generate(payer_xref_umf, mode="cte")
        assert len(sqlglot.parse(sql, read="spark")) == 1
        assert len(sqlglot.parse(sql, read="duckdb")) == 1

    def test_inner_join_type_honored(self, payer_xref_umf):
        base = _alt_join_base(self.ALT)
        target = _simple_target(
            relationships=Relationships(
                foreign_keys=[
                    ForeignKey(
                        column="payer_name",
                        references_table="payer_xref",
                        references_column="pcn",
                        join_type="inner",
                    )
                ]
            )
        )
        sql = generate_sql_plan(
            target, {"disputes": base, "payer_xref": payer_xref_umf}
        )
        assert "INNER JOIN matches_deduped m" in sql


# ---------------------------------------------------------------------------
# union_branches
# ---------------------------------------------------------------------------

LEGACY = "bronze_inventory_detail"
DAILY = "bronze_halo_daily_inventory"
CUTOVER_LEGACY = "to_date(file_date_mdyyyy, 'M.d.yyyy') < DATE'2026-07-20'"
CUTOVER_DAILY = "to_date(file_date_mdyyyy, 'M.d.yyyy') >= DATE'2026-07-20'"


@pytest.fixture
def legacy_umf() -> UMF:
    return _source_umf(
        LEGACY,
        {
            "arbit_id": "VARCHAR",
            "cpt": "VARCHAR",
            "dos": "DATE",
            "snapshot_date": "DATE",
            "file_date_mdyyyy": "VARCHAR",
            "charges": "DECIMAL",
            "fee_alloc_amount": "DECIMAL",
            "created_on": "DATE",
            "meta_load_dt": "DATETIME",
        },
    )


@pytest.fixture
def daily_umf() -> UMF:
    return _source_umf(
        DAILY,
        {
            "arbit_id": "VARCHAR",
            "cpt": "VARCHAR",
            "dos": "DATE",
            "snapshot_date": "DATE",
            "file_date_mdyyyy": "VARCHAR",
            "charges": "DECIMAL",
            "licn": "VARCHAR",
            "payor_offer_amount": "DECIMAL",
            "meta_load_dt": "DATETIME",
        },
    )


def _both_branch_col(
    name: str,
    dtype: str = "VARCHAR",
    *,
    legacy_only: bool = False,
    daily_only: bool = False,
    row_filters: bool = True,
    order_by: bool = True,
) -> UMFColumn:
    cands = []
    common: dict[str, object] = {}
    if order_by:
        common["order_by"] = ["meta_load_dt"]
    if not daily_only:
        cands.append(
            DerivationCandidate(
                table=LEGACY,
                column=name,
                priority=1,
                row_filter=CUTOVER_LEGACY if row_filters else None,
                **common,
            )
        )
    if not legacy_only:
        cands.append(
            DerivationCandidate(
                table=DAILY,
                column=name,
                priority=2,
                row_filter=CUTOVER_DAILY if row_filters else None,
                **common,
            )
        )
    return UMFColumn(
        name=name, data_type=dtype, derivation=UMFColumnDerivation(candidates=cands)
    )


def _inventory_target(
    *,
    union_type: str | None = "union_all",
    dedup: bool = True,
    row_filters: bool = True,
    union_base_tables: list[str] | None = None,
    source_tables: list[str] | None = None,
    union_exclude_base: bool = False,
    union_coalesce_base: bool = False,
    base_table_filter: str | None = None,
) -> UMF:
    order_by = dedup
    return UMF(
        version="1.0",
        table_name="silver_fact_inventory_line",
        table_type="generated",
        primary_key=["arbit_id", "cpt", "dos", "snapshot_date"],
        metadata=UMFMetadata(
            base_table=LEGACY,
            base_table_strategy="union_branches",
            union_base_tables=union_base_tables,
            source_tables=source_tables,
            union_type=union_type,
            union_exclude_base=union_exclude_base,
            union_coalesce_base=union_coalesce_base,
            base_table_filter=base_table_filter,
            dedup_strategy="latest" if dedup else None,
        ),
        columns=[
            _both_branch_col("arbit_id", row_filters=row_filters, order_by=order_by),
            _both_branch_col("cpt", row_filters=row_filters, order_by=order_by),
            _both_branch_col("dos", "DATE", row_filters=row_filters, order_by=order_by),
            _both_branch_col(
                "snapshot_date", "DATE", row_filters=row_filters, order_by=order_by
            ),
            _both_branch_col(
                "charges", "DECIMAL", row_filters=row_filters, order_by=order_by
            ),
            _both_branch_col(
                "fee_alloc_amount",
                "DECIMAL",
                legacy_only=True,
                row_filters=row_filters,
                order_by=order_by,
            ),
            _both_branch_col(
                "created_on",
                "DATE",
                legacy_only=True,
                row_filters=row_filters,
                order_by=order_by,
            ),
            _both_branch_col(
                "licn", daily_only=True, row_filters=row_filters, order_by=order_by
            ),
            _both_branch_col(
                "payor_offer_amount",
                "DECIMAL",
                daily_only=True,
                row_filters=row_filters,
                order_by=order_by,
            ),
            UMFColumn(
                name="source_generation",
                data_type="VARCHAR",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table=LEGACY,
                            column="source_generation",
                            priority=1,
                            union_value="legacy_snapshot",
                            row_filter=CUTOVER_LEGACY if row_filters else None,
                            order_by=["meta_load_dt"] if order_by else None,
                        ),
                        DerivationCandidate(
                            table=DAILY,
                            column="source_generation",
                            priority=2,
                            union_value="daily",
                            row_filter=CUTOVER_DAILY if row_filters else None,
                            order_by=["meta_load_dt"] if order_by else None,
                        ),
                    ],
                ),
            ),
        ],
    )


class TestUnionBranches:
    def _related(self, legacy_umf: UMF, daily_umf: UMF) -> dict[str, UMF]:
        return {LEGACY: legacy_umf, DAILY: daily_umf}

    def test_branch_per_source_with_union_all(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert f"FROM {LEGACY}\n" in sql
        assert f"FROM {DAILY}\n" in sql
        assert "\nUNION ALL\n" in sql

    def test_source_tables_fallback(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=None, source_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert f"FROM {DAILY}\n" in sql
        assert "\nUNION ALL\n" in sql

    def test_union_type_union(self, legacy_umf, daily_umf):
        target = _inventory_target(union_type="union", union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        base_view = sql.split("FINAL ASSEMBLY")[0]
        assert "\nUNION\n" in base_view
        assert "\nUNION ALL\n" not in base_view

    def test_row_filters_become_branch_where(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert f"WHERE {CUTOVER_LEGACY}" in sql
        assert f"WHERE {CUTOVER_DAILY}" in sql

    def test_conflicting_row_filters_raise(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        target.columns[0].derivation.candidates[0].row_filter = "1 = 1"
        with pytest.raises(ValueError, match="conflicting row_filter"):
            generate_sql_plan(target, self._related(legacy_umf, daily_umf))

    def test_union_value_literal_per_branch(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert "CAST('legacy_snapshot' AS STRING) AS source_generation" in sql
        assert "CAST('daily' AS STRING) AS source_generation" in sql

    def test_one_sided_columns_null_cast(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        legacy_branch = sql.split(f"{LEGACY}__rows AS (")[1].split("\n),")[0]
        daily_branch = sql.split(f"{DAILY}__rows AS (")[1].split("\n),")[0]
        assert "CAST(NULL AS STRING) AS licn" in legacy_branch
        assert "CAST(NULL AS DECIMAL(18,2)) AS payor_offer_amount" in legacy_branch
        assert "CAST(NULL AS DECIMAL(18,2)) AS fee_alloc_amount" in daily_branch
        assert "CAST(NULL AS DATE) AS created_on" in daily_branch

    def test_per_branch_dedup_window(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert sql.count("PARTITION BY arbit_id, cpt, dos, snapshot_date") == 2
        assert sql.count("ORDER BY meta_load_dt DESC NULLS LAST") == 2
        assert sql.count("WHERE __rn = 1") == 2
        assert f"{LEGACY}__dedup" in sql
        assert f"{DAILY}__dedup" in sql

    def test_no_dedup_without_order_by(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY], dedup=False)
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert "ROW_NUMBER" not in sql
        assert "__dedup" not in sql

    def test_conflicting_order_by_raises(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        target.columns[0].derivation.candidates[0].order_by = ["snapshot_date"]
        with pytest.raises(ValueError, match="conflicting order_by"):
            generate_sql_plan(target, self._related(legacy_umf, daily_umf))

    def test_base_table_filter_applies_to_base_branch_only(self, legacy_umf, daily_umf):
        target = _inventory_target(
            union_base_tables=[DAILY], base_table_filter="charges > 0"
        )
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        legacy_rows = sql.split(f"{LEGACY}__rows AS (")[1].split("),")[0]
        daily_rows = sql.split(f"{DAILY}__rows AS (")[1].split("),")[0]
        assert "(charges > 0)" in legacy_rows
        assert f"({CUTOVER_LEGACY})" in legacy_rows
        assert "charges > 0" not in daily_rows

    def test_union_exclude_base_anti_join(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY], union_exclude_base=True)
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert "WHERE NOT EXISTS (" in sql
        assert f"SELECT 1 FROM {LEGACY}__dedup b" in sql
        assert "b.arbit_id = t.arbit_id" in sql
        assert "b.snapshot_date = t.snapshot_date" in sql

    def test_union_coalesce_base_three_parts(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY], union_coalesce_base=True)
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        base_view = sql.split("FINAL ASSEMBLY")[0]
        assert base_view.count("WHERE NOT EXISTS (") == 2
        assert "INNER JOIN" in base_view
        assert "COALESCE(b.charges, u.charges) AS charges" in base_view
        # pk and union_value discriminators keep the base value; a column the
        # union table cannot supply (fee_alloc_amount) also stays base-side.
        # licn is NULL on the BASE side, so COALESCE correctly fills it from
        # the union branch.
        assert "COALESCE(b.arbit_id" not in base_view
        assert "COALESCE(b.source_generation" not in base_view
        assert "b.fee_alloc_amount,\n" in base_view
        assert "COALESCE(b.fee_alloc_amount" not in base_view
        assert "COALESCE(b.licn, u.licn) AS licn" in base_view
        # 2 body occurrences (the third "UNION ALL" is the header label)
        assert base_view.count("\nUNION ALL\n") == 2

    def test_coalesce_with_multiple_union_tables_raises(self, legacy_umf, daily_umf):
        third = _source_umf("bronze_third", {"arbit_id": "VARCHAR"})
        target = _inventory_target(
            union_base_tables=[DAILY, "bronze_third"], union_coalesce_base=True
        )
        with pytest.raises(ValueError, match="exactly one union table"):
            generate_sql_plan(
                target, {**self._related(legacy_umf, daily_umf), "bronze_third": third}
            )

    def test_exclude_without_pk_raises(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY], union_exclude_base=True)
        target.primary_key = None
        with pytest.raises(ValueError, match="primary_key"):
            generate_sql_plan(target, self._related(legacy_umf, daily_umf))

    def test_missing_union_tables_raises(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=None, source_tables=None)
        with pytest.raises(ValueError, match="union_base_tables"):
            generate_sql_plan(target, self._related(legacy_umf, daily_umf))

    def test_duplicate_branch_table_raises(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[LEGACY])
        with pytest.raises(ValueError, match="duplicate"):
            generate_sql_plan(target, self._related(legacy_umf, daily_umf))

    def test_union_base_tables_without_strategy_warns_and_ignores(
        self, legacy_umf, daily_umf, caplog
    ):
        target = _inventory_target(union_base_tables=[DAILY], dedup=False)
        assert target.metadata is not None
        target.metadata.base_table_strategy = None
        target.metadata.dedup_strategy = None
        with caplog.at_level(logging.WARNING):
            sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert any("union_base_tables" in r.message for r in caplog.records)
        base_view = sql.split("STEP")[1]
        assert "UNION" not in base_view.split("FINAL ASSEMBLY")[0]

    def test_final_assembly_references_target_names(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        final = sql.split("FINAL ASSEMBLY")[1]
        assert "base.source_generation AS source_generation" in final
        assert "base.licn AS licn" in final

    def test_join_after_union_base_works(self, legacy_umf, daily_umf):
        xref = _source_umf(
            "payer_xref", {"arbit_id": "VARCHAR", "payer_name": "VARCHAR"}
        )
        target = _inventory_target(union_base_tables=[DAILY])
        target.columns.append(
            UMFColumn(
                name="payer_name",
                data_type="VARCHAR",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="payer_xref", column="payer_name", priority=1
                        )
                    ],
                ),
            )
        )
        sql = generate_sql_plan(
            target, {**self._related(legacy_umf, daily_umf), "payer_xref": xref}
        )
        assert "STEP 1: Join payer_xref" in sql
        assert "ON base.arbit_id = target.arbit_id" in sql

    def test_cte_mode_shape_and_single_statement(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(
            target, self._related(legacy_umf, daily_umf), mode="cte"
        )
        assert "disposition_base AS (\nWITH " in sql
        assert sql.count(";") == 1
        assert len(sqlglot.parse(sql, read="spark")) == 1
        assert len(sqlglot.parse(sql, read="duckdb")) == 1

    def test_union_sources_strategy_unaffected(self, legacy_umf, daily_umf):
        # source_tables set but strategy is union_sources -> existing behavior
        target = _inventory_target(union_base_tables=None, source_tables=[DAILY])
        assert target.metadata is not None
        target.metadata.base_table_strategy = "union_sources"
        target.metadata.base_table = None
        target.metadata.dedup_strategy = None
        sql = generate_sql_plan(target, self._related(legacy_umf, daily_umf))
        assert "union_universe" in sql


# ---------------------------------------------------------------------------
# Acceptance fixture: silver_fact_inventory_line generation cutover
# ---------------------------------------------------------------------------


EXPECTED_ACCEPTANCE_CTE = """
with
disposition_base as (
  with bronze_inventory_detail__rows as (
    select
      arbit_id, charges, cpt, created_on, dos, fee_alloc_amount,
      cast(null as string) as licn,
      cast(null as decimal(18,2)) as payor_offer_amount,
      snapshot_date,
      cast('legacy_snapshot' as string) as source_generation,
      meta_load_dt
    from bronze_inventory_detail
    where to_date(file_date_mdyyyy, 'M.d.yyyy') < date'2026-07-20'
  ),
  bronze_inventory_detail__ranked as (
    select *,
      row_number() over (
        partition by arbit_id, cpt, dos, snapshot_date
        order by meta_load_dt desc nulls last
      ) as __rn
    from bronze_inventory_detail__rows
  ),
  bronze_inventory_detail__dedup as (
    select arbit_id, charges, cpt, created_on, dos, fee_alloc_amount, licn,
      payor_offer_amount, snapshot_date, source_generation, meta_load_dt
    from bronze_inventory_detail__ranked
    where __rn = 1
  ),
  bronze_halo_daily_inventory__rows as (
    select
      arbit_id, charges, cpt,
      cast(null as date) as created_on,
      dos,
      cast(null as decimal(18,2)) as fee_alloc_amount,
      licn, payor_offer_amount, snapshot_date,
      cast('daily' as string) as source_generation,
      meta_load_dt
    from bronze_halo_daily_inventory
    where to_date(file_date_mdyyyy, 'M.d.yyyy') >= date'2026-07-20'
  ),
  bronze_halo_daily_inventory__ranked as (
    select *,
      row_number() over (
        partition by arbit_id, cpt, dos, snapshot_date
        order by meta_load_dt desc nulls last
      ) as __rn
    from bronze_halo_daily_inventory__rows
  ),
  bronze_halo_daily_inventory__dedup as (
    select arbit_id, charges, cpt, created_on, dos, fee_alloc_amount, licn,
      payor_offer_amount, snapshot_date, source_generation, meta_load_dt
    from bronze_halo_daily_inventory__ranked
    where __rn = 1
  )
  select arbit_id, charges, cpt, created_on, dos, fee_alloc_amount, licn,
    payor_offer_amount, snapshot_date, source_generation, meta_load_dt
  from bronze_inventory_detail__dedup
  union all
  select arbit_id, charges, cpt, created_on, dos, fee_alloc_amount, licn,
    payor_offer_amount, snapshot_date, source_generation, meta_load_dt
  from bronze_halo_daily_inventory__dedup
),
silver_fact_inventory_line as (
  select
    base.arbit_id as arbit_id,
    base.charges as charges,
    base.cpt as cpt,
    base.created_on as created_on,
    base.dos as dos,
    base.fee_alloc_amount as fee_alloc_amount,
    base.licn as licn,
    base.payor_offer_amount as payor_offer_amount,
    base.snapshot_date as snapshot_date,
    base.source_generation as source_generation
  from disposition_base base
)
select * from silver_fact_inventory_line;
"""


class TestAcceptanceFixtureSilverFactInventoryLine:
    """The real-world generation-cutover shape this port exists to produce.

    Mirrors the downstream check: regenerate the plan from the spec and diff
    against the expected transform after sqlglot normalization -- exact text
    match is deliberately NOT required.
    """

    def test_cte_plan_matches_expected_normalized(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(
            target, {LEGACY: legacy_umf, DAILY: daily_umf}, mode="cte"
        )
        assert _canon(sql) == _canon(EXPECTED_ACCEPTANCE_CTE)

    def test_pinned_shapes(self, legacy_umf, daily_umf):
        target = _inventory_target(union_base_tables=[DAILY])
        sql = generate_sql_plan(target, {LEGACY: legacy_umf, DAILY: daily_umf})
        assert "CAST('legacy_snapshot' AS STRING) AS source_generation" in sql
        assert "CAST('daily' AS STRING) AS source_generation" in sql
        assert (
            "PARTITION BY arbit_id, cpt, dos, snapshot_date" in sql
            and "ORDER BY meta_load_dt DESC NULLS LAST" in sql
        )
        assert "\nUNION ALL\n" in sql
