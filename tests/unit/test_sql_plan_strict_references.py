# SPDX-License-Identifier: MIT OR Apache-2.0
"""``strict_references``: a plan that reads a table missing from
``related_umfs`` raises instead of silently emitting an empty or partial plan."""

from __future__ import annotations

import pytest

from tablespec.models.umf import (
    UMF,
    DerivationCandidate,
    UMFColumn,
    UMFColumnDerivation,
    UMFMetadata,
)
from tablespec.schemas.sql_generator import (
    UnresolvedTableError,
    generate_sql_plan,
    unresolved_table_refs,
)

pytestmark = pytest.mark.no_spark


def _src(name: str) -> UMF:
    return UMF(
        version="1.0",
        table_name=name,
        columns=[UMFColumn(name="id", data_type="INTEGER")],
        primary_key=["id"],
    )


def _col(name: str, table: str) -> UMFColumn:
    return UMFColumn(
        name=name,
        data_type="VARCHAR",
        source="derived",
        derivation=UMFColumnDerivation(
            candidates=[DerivationCandidate(priority=1, table=table, column="id")]
        ),
    )


def _target(*cols: UMFColumn, metadata: UMFMetadata | None = None) -> UMF:
    return UMF(
        version="1.0",
        table_name="gold",
        columns=list(cols),
        primary_key=[cols[0].name],
        metadata=metadata,
    )


def test_missing_candidate_table_raises_in_strict_mode():
    target = _target(_col("id", "claims"), _col("pay_id", "payments"))
    related = {"claims": _src("claims")}
    with pytest.raises(UnresolvedTableError, match="payments"):
        generate_sql_plan(target, related, strict_references=True)


def test_default_mode_still_warns_and_renders():
    target = _target(_col("id", "claims"), _col("pay_id", "payments"))
    assert generate_sql_plan(target, {"claims": _src("claims")})


def test_missing_base_table_raises_in_strict_mode():
    target = _target(_col("id", "claims"), metadata=UMFMetadata(base_table="spine"))
    with pytest.raises(UnresolvedTableError, match="spine"):
        generate_sql_plan(target, {"claims": _src("claims")}, strict_references=True)


def test_qualified_markers_and_self_refs_resolve():
    target = _target(
        _col("id", "ns.claims"),  # resolves bare
        _col("a", "intermediate"),  # plan marker
        _col("b", "gold"),  # self-reference
    )
    assert unresolved_table_refs(target, {"claims": _src("claims")}) == []
