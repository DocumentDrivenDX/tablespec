# @covers US-032-AC1
# @covers US-032-AC2
"""Tests for CTE mode in SQL plan generation."""

from __future__ import annotations

import pytest

from tablespec.models.umf import (
    Cardinality,
    DerivationCandidate,
    OutgoingRelationship,
    Relationships,
    RelationshipSummary,
    Survivorship,
    UMF,
    UMFColumn,
    UMFColumnDerivation,
)
from tablespec.schemas.sql_generator import SQLPlanGenerator, generate_sql_plan

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _card(type_: str, notation: str) -> Cardinality:
    parts = notation.split(":")
    return Cardinality(
        type=type_,
        notation=notation,
        source_multiplicity=parts[0] if len(parts) > 0 else "1",
        target_multiplicity=parts[1] if len(parts) > 1 else "*",
    )


def _make_umf(
    table_name: str,
    columns: list[UMFColumn],
    *,
    primary_key: list[str] | None = None,
    relationships: Relationships | None = None,
) -> UMF:
    return UMF(
        version="1.0",
        table_name=table_name,
        columns=columns,
        primary_key=primary_key,
        relationships=relationships,
    )


@pytest.fixture
def source_table_a() -> UMF:
    return _make_umf(
        "source_a",
        [
            UMFColumn(name="claim_id", data_type="VARCHAR"),
            UMFColumn(name="member_name", data_type="VARCHAR"),
            UMFColumn(name="service_date", data_type="DATE"),
        ],
        primary_key=["claim_id"],
        relationships=Relationships(
            outgoing=[
                OutgoingRelationship(
                    target_table="source_b",
                    source_column="claim_id",
                    target_column="claim_id",
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
def source_table_b() -> UMF:
    return _make_umf(
        "source_b",
        [
            UMFColumn(name="claim_id", data_type="VARCHAR"),
            UMFColumn(name="provider_name", data_type="VARCHAR"),
            UMFColumn(name="provider_type", data_type="VARCHAR"),
        ],
        primary_key=["claim_id"],
        relationships=Relationships(
            summary=RelationshipSummary(
                total_relationships=0,
                total_incoming=1,
                total_outgoing=0,
                hub_score=1.0,
            ),
        ),
    )


@pytest.fixture
def related_umfs(source_table_a: UMF, source_table_b: UMF) -> dict[str, UMF]:
    return {
        "source_a": source_table_a,
        "source_b": source_table_b,
    }


@pytest.fixture
def minimal_umf() -> UMF:
    return _make_umf(
        "test_claims",
        [
            UMFColumn(name="claim_id", data_type="VARCHAR"),
            UMFColumn(name="claim_amount", data_type="DECIMAL"),
            UMFColumn(name="provider_id", data_type="VARCHAR"),
        ],
        primary_key=["claim_id"],
    )


@pytest.fixture
def derived_umf() -> UMF:
    return _make_umf(
        "derived_output",
        [
            UMFColumn(
                name="claim_id",
                data_type="VARCHAR",
                derivation=UMFColumnDerivation(strategy="primary_key"),
            ),
            UMFColumn(
                name="member_name",
                data_type="VARCHAR",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="source_a",
                            column="member_name",
                            priority=1,
                        ),
                    ],
                    survivorship=Survivorship(
                        strategy="single_source",
                        explanation="Direct from source_a",
                    ),
                ),
            ),
            UMFColumn(
                name="provider_name",
                data_type="VARCHAR",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="source_b",
                            column="provider_name",
                            priority=1,
                        ),
                    ],
                    survivorship=Survivorship(
                        strategy="single_source",
                        explanation="Direct from source_b",
                    ),
                ),
            ),
        ],
        primary_key=["claim_id"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCTEMode:
    """Test CTE output mode for SQLPlanGenerator."""

    def test_cte_starts_with_WITH(self, derived_umf: UMF, related_umfs: dict[str, UMF]):
        """CTE mode output contains a WITH clause."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        # Strip leading comment block, then check for WITH
        assert "WITH" in sql
        assert "SELECT * FROM" in sql

    def test_cte_has_no_create_view(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode output must not contain CREATE statements."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        assert "CREATE OR REPLACE TEMPORARY VIEW" not in sql
        assert "CREATE" not in sql

    def test_views_mode_still_produces_create(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """Views mode (explicit) still uses CREATE TEMPORARY VIEW."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="views")
        assert "CREATE OR REPLACE TEMPORARY VIEW" in sql

    def test_default_mode_is_views(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """Default mode is views for backward compatibility."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs)
        assert "CREATE OR REPLACE TEMPORARY VIEW" in sql

    def test_cte_ends_with_select_from_final(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode ends with SELECT * FROM the final (target table) CTE."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        assert "SELECT * FROM derived_output;" in sql

    def test_cte_contains_named_cte_entries(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode contains named CTE entries with AS (...)."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        # Should have at least one "name AS (" pattern
        assert " AS (" in sql

    def test_cte_preserves_join_logic(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode preserves the same join SQL (LEFT JOIN, ON clause)."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        assert "LEFT JOIN" in sql
        assert " ON " in sql

    def test_cte_preserves_final_assembly(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode preserves FINAL ASSEMBLY comment."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(derived_umf, related_umfs, mode="cte")
        assert "FINAL ASSEMBLY" in sql

    def test_cte_minimal_table_no_derivations(
        self, minimal_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """CTE mode works for a minimal table with no derivations."""
        gen = SQLPlanGenerator()
        sql = gen.generate_for_table(minimal_umf, related_umfs, mode="cte")
        # Should still produce valid output (WITH + SELECT or just the view)
        assert "CREATE" not in sql
        assert "test_claims" in sql

    def test_convenience_function_cte_mode(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """generate_sql_plan() convenience function accepts mode='cte'."""
        sql = generate_sql_plan(derived_umf, related_umfs, mode="cte")
        assert "WITH" in sql
        assert "CREATE" not in sql

    def test_convenience_function_default_views(
        self, derived_umf: UMF, related_umfs: dict[str, UMF]
    ):
        """generate_sql_plan() defaults to views mode."""
        sql = generate_sql_plan(derived_umf, related_umfs)
        assert "CREATE OR REPLACE TEMPORARY VIEW" in sql


class TestConvertViewsToCte:
    """Unit tests for the _convert_views_to_cte post-processing method."""

    def test_no_views_returns_unchanged(self):
        """Input with no CREATE VIEW statements is returned as-is."""
        gen = SQLPlanGenerator()
        raw = "-- just a comment\nSELECT 1;"
        assert gen._convert_views_to_cte(raw) == raw

    def test_single_view_converted(self):
        """A single CREATE VIEW becomes a single-CTE WITH statement."""
        gen = SQLPlanGenerator()
        raw = (
            "-- header\n"
            "CREATE OR REPLACE TEMPORARY VIEW my_view AS\n"
            "SELECT col1, col2\nFROM source_table;"
        )
        result = gen._convert_views_to_cte(raw)
        assert "WITH" in result
        assert "my_view AS (" in result
        assert "SELECT * FROM my_view;" in result
        assert "CREATE" not in result

    def test_multiple_views_converted(self):
        """Multiple CREATE VIEW statements become chained CTEs."""
        gen = SQLPlanGenerator()
        raw = (
            "-- header\n"
            "CREATE OR REPLACE TEMPORARY VIEW step_1 AS\n"
            "SELECT a FROM t;\n"
            "CREATE OR REPLACE TEMPORARY VIEW step_2 AS\n"
            "SELECT b FROM step_1;\n"
            "CREATE OR REPLACE TEMPORARY VIEW final AS\n"
            "SELECT c FROM step_2;"
        )
        result = gen._convert_views_to_cte(raw)
        assert "WITH" in result
        assert "step_1 AS (" in result
        assert "step_2 AS (" in result
        assert "final AS (" in result
        assert "SELECT * FROM final;" in result
        assert "CREATE" not in result

    def test_semicolons_stripped_from_cte_bodies(self):
        """Trailing semicolons are removed from CTE bodies."""
        gen = SQLPlanGenerator()
        raw = (
            "CREATE OR REPLACE TEMPORARY VIEW v1 AS\n"
            "SELECT 1;\n"
            "CREATE OR REPLACE TEMPORARY VIEW v2 AS\n"
            "SELECT 2;"
        )
        result = gen._convert_views_to_cte(raw)
        # Count semicolons — should only be the final one
        # Each CTE body should not end with ;
        assert "SELECT 1\n)" in result
        assert "SELECT 2\n)" in result
