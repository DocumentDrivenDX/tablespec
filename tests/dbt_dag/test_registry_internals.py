"""Branch coverage for NodeRegistry internals not hit by the e2e/DAG tests.

Pure-Python. Targets the registry's name-resolution and classification edges:
alias lookup, the ``intermediate`` / ``member_universe`` pseudo-table skip, the
bare self-name skip, the resolver-exception swallow in inferred-base detection,
and the public ``umf`` / ``all_umfs`` accessors.
"""

from __future__ import annotations

import pytest

from tablespec.core.ir import NodeRole
from tablespec.dbt import (
    DbtProjectError,
    NodeRegistry,
    NodeRegistryError,
    generate_dbt_dag_project,
)
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

_NN = {"default": False}
_NL = {"default": True}


def _staging(table: str) -> UMF:
    return UMF(
        version="1.0",
        table_name=table,
        primary_key=[f"{table}_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": f"{table}_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "v", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )


def test_resolve_via_alias():
    """A relation reference matching a declared alias resolves to that node."""
    member = UMF(
        version="1.0",
        table_name="member",
        aliases=["mbr", "member_dim"],
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "member_id", "data_type": "INTEGER", "nullable": _NN}],
    )
    reg = NodeRegistry([member])
    resolved = reg.resolve("member_dim")
    assert resolved is not None
    assert resolved.node_id == "ingested_member"
    assert resolved.role is NodeRole.INGESTED


def test_intermediate_pseudo_table_is_not_an_edge():
    """A derivation candidate naming 'intermediate'/'member_universe' is no edge."""
    gold = UMF(
        version="1.0",
        table_name="g",
        primary_key=["id"],
        metadata={"base_table": "base"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "x",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "intermediate", "column": "x", "priority": 1},
                        {"table": "member_universe", "column": "y", "priority": 2},
                        {"table": "base", "column": "z", "priority": 3},
                    ],
                },
            },
        ],
    )
    base = _staging("base")
    reg = NodeRegistry([base, gold])
    g = reg.plan.nodes["gold_g"]
    # Only the real 'base' table is an edge; the pseudo-tables are skipped.
    assert g.depends_on == {"ingested_base"}
    assert reg.dangling_refs == set()


def test_bare_self_reference_is_not_a_self_edge():
    """A candidate naming the gold table's own bare name is not a self-dependency."""
    gold = UMF(
        version="1.0",
        table_name="g",
        primary_key=["id"],
        metadata={"base_table": "base"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "x",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    # references its OWN bare name
                    "candidates": [{"table": "g", "column": "x", "priority": 1}],
                },
            },
        ],
    )
    reg = NodeRegistry([_staging("base"), gold])
    g = reg.plan.nodes["gold_g"]
    # the ONLY edge is the base table; no self-edge, no dangling, no external.
    assert g.depends_on == {"ingested_base"}
    assert reg.dangling_refs == set()
    assert not any(n.external for n in reg.plan.nodes.values())
    assert reg.plan.detect_cycle() is None


def test_alias_self_reference_is_not_a_self_edge():
    """A candidate naming the gold table's declared alias is not a self-dependency."""
    gold = UMF(
        version="1.0",
        table_name="g",
        aliases=["g_alias"],
        primary_key=["id"],
        metadata={"base_table": "base"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "x",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "g_alias", "column": "x", "priority": 1}],
                },
            },
        ],
    )
    reg = NodeRegistry([_staging("base"), gold])
    g = reg.plan.nodes["gold_g"]
    assert g.depends_on == {"ingested_base"}
    assert reg.dangling_refs == set()
    assert not any(n.external for n in reg.plan.nodes.values())


def test_public_accessors():
    a, b = _staging("a"), _staging("b")
    reg = NodeRegistry([a, b])
    assert reg.umf("a").table_name == "a"
    assert {u.table_name for u in reg.all_umfs()} == {"a", "b"}
    with pytest.raises(KeyError):
        reg.umf("missing")


def test_resolve_unknown_returns_none():
    reg = NodeRegistry([_staging("a")])
    assert reg.resolve("nope") is None


def test_canonical_name_collision_fails_closed():
    """Two tables sharing a canonical_name is an ambiguous index -> RAISES.

    Last-write-wins indexing would let one table's name hijack the other's
    relation reference; the registry must fail closed instead.
    """
    a = UMF(
        version="1.0",
        table_name="a",
        canonical_name="shared.x",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    b = UMF(
        version="1.0",
        table_name="b",
        canonical_name="shared.x",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    with pytest.raises(NodeRegistryError, match="claimed by two different nodes"):
        NodeRegistry([a, b])


def test_alias_collision_with_other_table_name_fails_closed():
    """An alias that equals ANOTHER table's name is a collision -> RAISES."""
    member = UMF(
        version="1.0",
        table_name="member",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    other = UMF(
        version="1.0",
        table_name="other",
        aliases=["member"],  # collides with the 'member' table name
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    with pytest.raises(NodeRegistryError):
        NodeRegistry([member, other])


def test_collision_surfaces_as_dbt_project_error():
    """generate_dbt_dag_project wraps a collision as the public DbtProjectError."""
    a = UMF(
        version="1.0",
        table_name="a",
        canonical_name="shared.x",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    b = UMF(
        version="1.0",
        table_name="b",
        canonical_name="shared.x",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "id", "data_type": "INTEGER", "nullable": _NN}],
    )
    with pytest.raises(DbtProjectError, match="claimed by two different nodes"):
        generate_dbt_dag_project([a, b])


def test_gold_ref_binds_via_referenced_table_alias():
    """A gold candidate naming another table's ALIAS binds to that table's node.

    Exercises ``_lookup_umf`` matching on a declared alias (not table_name or
    canonical_name) during gold edge wiring.
    """
    member = UMF(
        version="1.0",
        table_name="member",
        aliases=["mbr_alias"],
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "member_name", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    gold = UMF(
        version="1.0",
        table_name="g",
        primary_key=["id"],
        metadata={"base_table": "base"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "name",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    # reference 'member' via its ALIAS
                    "candidates": [
                        {"table": "mbr_alias", "column": "member_name", "priority": 1}
                    ],
                },
            },
        ],
    )
    reg = NodeRegistry([_staging("base"), member, gold])
    g = reg.plan.nodes["gold_g"]
    assert "ingested_member" in g.depends_on
    assert reg.dangling_refs == set()
