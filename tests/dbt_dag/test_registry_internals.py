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


def test_duplicate_table_name_fails_closed():
    """Two UMFs sharing a table_name is an ambiguous set -> RAISES.

    Regression for the silent last-write-wins gap: identical table_names produce
    identical node ids (``ingested_dup``), so the ``_index`` collision guard --
    which only fires when ONE physical name maps to TWO different node ids -- never
    trips. The second UMF would silently clobber the first in ``self._umfs``,
    dropping a whole table's spec. The build must fail closed instead.
    """
    first = _staging("dup")
    # A genuinely-different second 'dup' (extra column) -- without the guard the
    # registry would keep ONLY this one and drop ``first`` with no error.
    second = UMF(
        version="1.0",
        table_name="dup",
        primary_key=["dup_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "dup_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "extra", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    with pytest.raises(NodeRegistryError, match=r"Duplicate table_name 'dup'"):
        NodeRegistry([first, second])


def test_duplicate_table_name_surfaces_as_dbt_project_error():
    """generate_dbt_dag_project wraps a duplicate table_name as DbtProjectError."""
    with pytest.raises(DbtProjectError, match=r"Duplicate table_name 'dup'"):
        generate_dbt_dag_project([_staging("dup"), _staging("dup")])


def _gold_external(name: str, ref: str) -> UMF:
    """A gold table whose one derived column references an external *ref*."""
    return UMF(
        version="1.0",
        table_name=name,
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
                    "candidates": [{"table": ref, "column": "v", "priority": 1}],
                },
            },
        ],
    )


def test_external_sanitized_id_collision_fails_closed():
    """Two DISTINCT external refs sanitizing to one dbt source id -> RAISES.

    ``a.b__c`` and ``a.b.c`` are different cross-pipeline relations, yet both
    sanitize (``.replace('.', '__')``) to the SAME source id ``a__b__c``.
    ``LogicalPlan.add`` merges same-id nodes, so without a guard the two distinct
    relations are silently conflated into ONE ``source('external', 'a__b__c')``
    -- a wrong-data edge. The registry must detect the clash and fail closed.
    """
    with pytest.raises(NodeRegistryError, match=r"sanitize.*'a__b__c'"):
        NodeRegistry(
            [
                _staging("base"),
                _gold_external("g1", "a.b__c"),
                _gold_external("g2", "a.b.c"),
            ]
        )


def test_external_sanitized_collision_surfaces_as_dbt_project_error():
    """The sanitized-id clash is wrapped as the public DbtProjectError."""
    with pytest.raises(DbtProjectError, match=r"sanitize.*'a__b__c'"):
        generate_dbt_dag_project(
            [
                _staging("base"),
                _gold_external("g1", "a.b__c"),
                _gold_external("g2", "a.b.c"),
            ]
        )


def test_distinct_external_refs_without_collision_coexist():
    """Two external refs with DIFFERENT sanitized ids both register (no false clash).

    Guards against an over-eager collision check: ``a.b`` -> ``a__b`` and
    ``c.d`` -> ``c__d`` are distinct ids and must BOTH yield external source nodes.
    """
    reg = NodeRegistry(
        [_staging("base"), _gold_external("g1", "a.b"), _gold_external("g2", "c.d")]
    )
    ext_ids = sorted(n.node_id for n in reg.plan.nodes.values() if n.external)
    assert ext_ids == ["a__b", "c__d"]
    assert reg.dangling_refs == set()


def _gold_bare_external(name: str, ref: str) -> UMF:
    """A gold table whose derived col references a BARE *ref* marked cross_pipeline.

    A bare (unqualified) reference only routes external when THIS table's own
    cross_pipeline FK points at it; that is the path that can yield an external
    source id WITHOUT a namespace separator (so it can collide with a local id).
    """
    return UMF(
        version="1.0",
        table_name=name,
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
                    "candidates": [{"table": ref, "column": "v", "priority": 1}],
                },
            },
        ],
        relationships={
            "foreign_keys": [
                {
                    "column": "x",
                    "references_table": ref,
                    "references_column": "v",
                    "cross_pipeline": True,
                }
            ]
        },
    )


def test_external_id_colliding_with_local_node_fails_closed():
    """A bare external ref sanitizing to a LOCAL node id -> RAISES (no conflation).

    Local table ``base`` owns the plan node id ``raw_base``. A bare cross-pipeline
    external ref ``raw_base`` also sanitizes to ``raw_base``; ``LogicalPlan.add``
    merges same-id nodes (OR-ing ``external=True``), which would silently turn the
    LOCAL landing source into an external one and re-route the local pipeline's
    raw read to a phantom cross-pipeline source. The registry must fail closed.
    """
    reg_ok_msg = r"already names a local source node"
    with pytest.raises(NodeRegistryError, match=reg_ok_msg):
        NodeRegistry([_staging("base"), _gold_bare_external("g", "raw_base")])


def test_same_external_ref_in_two_golds_is_idempotent():
    """The SAME external ref used by two gold tables is one shared source, not a clash.

    Re-claiming an external id with the IDENTICAL original ref is a legitimate
    shared cross-pipeline source -- it must merge into one node, never raise.
    """
    reg = NodeRegistry(
        [
            _staging("base"),
            _gold_external("g1", "ext.shared"),
            _gold_external("g2", "ext.shared"),
        ]
    )
    ext = [n for n in reg.plan.nodes.values() if n.external]
    assert len(ext) == 1
    assert ext[0].node_id == "ext__shared"
    # Both gold models depend on the one shared external source.
    assert reg.plan.nodes["gold_g1"].depends_on >= {"ext__shared"}
    assert reg.plan.nodes["gold_g2"].depends_on >= {"ext__shared"}


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
