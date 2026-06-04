"""Unit tests for the dbt DAG planner: fail-closed, cycles, materialization.

These are pure-Python (no dbt/duckdb invocation) and assert the corrected-design
invariants directly on the IR / renderer / policy.
"""

from __future__ import annotations

import pytest

from tablespec.core.ir import NodeRole
from tablespec.dbt import (
    DbtProjectError,
    DbtRefRenderer,
    MaterializationPolicy,
    NodeRegistry,
    RoutingPolicy,
    UnknownRelationError,
    generate_dbt_dag_project,
)
from tablespec.models.umf import UMF

_NN = {"default": False}
_NL = {"default": True}


def _member() -> UMF:
    return UMF(
        version="1.0",
        table_name="member",
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "member_name", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )


def _claims() -> UMF:
    return UMF(
        version="1.0",
        table_name="claims",
        primary_key=["claim_id"],
        ingestion={"mode": "incremental", "order_by": ["_load_ts"]},
        columns=[
            {"name": "claim_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NL},
        ],
    )


def _gold_referencing(target: str) -> UMF:
    """A gold table whose one derived column references *target*."""
    return UMF(
        version="1.0",
        table_name="g",
        primary_key=["claim_id"],
        metadata={"base_table": "claims"},
        columns=[
            {
                "name": "claim_id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "member_name",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": target, "column": "member_name", "priority": 1}
                    ],
                },
            },
        ],
    )


def test_renderer_fails_closed_on_unknown_relation() -> None:
    reg = NodeRegistry([_member(), _claims()])
    renderer = DbtRefRenderer(reg)
    # Known relations render as refs/sources.
    assert renderer.render("member") == "{{ ref('ingested_member') }}"
    assert renderer.render("raw_member") == "{{ source('raw', 'raw_member') }}"
    # Unknown relation must RAISE, never fall back to source('external').
    with pytest.raises(UnknownRelationError):
        renderer.render("nonexistent_table")


def test_generate_fails_closed_on_dangling_reference() -> None:
    """A gold model referencing a table NOT in the UMF set fails loudly."""
    # 'g' references 'ghost' which is not provided.
    with pytest.raises((UnknownRelationError, DbtProjectError)):
        generate_dbt_dag_project([_claims(), _gold_referencing("ghost")])


def test_qualified_name_does_not_collide_with_local_table() -> None:
    """A qualified cross-pipeline ref must NOT bind to a local bare table.

    ``other.member`` is a different relation from local ``member``; resolving it
    to the local node would silently re-route a cross-pipeline edge inward.
    """
    reg = NodeRegistry([_member(), _claims()])
    renderer = DbtRefRenderer(reg)
    assert renderer.render("member") == "{{ ref('ingested_member') }}"
    with pytest.raises(UnknownRelationError):
        renderer.render("other.member")


def test_external_qualified_reference_routes_to_external_source() -> None:
    """A qualified reference is treated as external -> source('external', ...)."""
    reg = NodeRegistry([_claims(), _gold_referencing("otherpipe.refdata")])
    # Not dangling -- it is explicitly external (qualified).
    assert reg.dangling_refs == set()
    renderer = DbtRefRenderer(reg)
    assert (
        renderer.render("otherpipe.refdata")
        == "{{ source('external', 'otherpipe__refdata') }}"
    )
    # The project generates cleanly (no fail-closed) and declares the source.
    files = generate_dbt_dag_project(
        [_claims(), _gold_referencing("otherpipe.refdata")]
    )
    assert "  - name: external" in files["models/sources.yml"]
    assert "      - name: otherpipe__refdata" in files["models/sources.yml"]


def test_cycle_detection_raises() -> None:
    """A dependency cycle in the IR is reported as a DbtProjectError."""
    # Two gold tables that reference each other -> cycle in the model graph.
    a = UMF(
        version="1.0",
        table_name="a",
        primary_key=["id"],
        metadata={"base_table": "b"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "bx",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "b", "column": "x", "priority": 1}],
                },
            },
        ],
    )
    b = UMF(
        version="1.0",
        table_name="b",
        primary_key=["id"],
        metadata={"base_table": "a"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "ax",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "a", "column": "x", "priority": 1}],
                },
            },
        ],
    )
    with pytest.raises(DbtProjectError, match="cycle"):
        generate_dbt_dag_project([a, b])


def test_materialization_policy_on_graph() -> None:
    """Staging mode -> incremental/table; gold final -> table by default."""
    policy = MaterializationPolicy()
    # incremental + pk -> merge with unique_key
    m = policy.for_ingested(mode="incremental", primary_key=["claim_id"])
    assert m.strategy == "incremental"
    assert m.incremental_strategy == "merge"
    assert m.unique_key == ("claim_id",)
    # incremental, no pk -> append
    m2 = policy.for_ingested(mode="incremental", primary_key=[])
    assert m2.strategy == "incremental"
    assert m2.incremental_strategy == "append"
    # snapshot -> full table (NOT a dbt snapshot)
    m3 = policy.for_ingested(mode="snapshot", primary_key=["member_id"])
    assert m3.strategy == "table"
    assert m3.incremental_strategy is None

    # gold final -> table by default
    reg = NodeRegistry([_member(), _claims(), _gold_referencing("member")])
    gold_node = reg.plan.nodes["gold_g"]
    assert gold_node.role is NodeRole.GOLD
    mg = policy.for_node(gold_node, reg.plan, table_name="g")
    assert mg.strategy == "table"


def test_routing_literals() -> None:
    r = RoutingPolicy()
    assert r.source_literal("raw_x") == "{{ source('raw', 'raw_x') }}"
    assert r.ref_literal("ingested_x") == "{{ ref('ingested_x') }}"
