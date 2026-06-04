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

# Pure-Python planner tests: no Spark, no dbt/duckdb invocation. Marked so the
# fast lane runs them with no JVM.
pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

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
    """A gold model referencing a table NOT in the UMF set fails loudly.

    The failure must surface as the PUBLIC ``DbtProjectError`` (callers handle one
    exception type) AND the message must name the exact offending edge
    ``g -> 'ghost'`` so the operator knows which reference to fix -- a bare "build
    failed" is not actionable. Asserting the precise edge also proves the
    dangling-ref path fired (not some unrelated error coincidentally raised).
    """
    # 'g' references 'ghost' which is not provided.
    with pytest.raises(DbtProjectError) as exc:
        generate_dbt_dag_project([_claims(), _gold_referencing("ghost")])
    assert "g -> 'ghost'" in str(exc.value), (
        f"dangling-ref error must name the offending edge, got: {exc.value}"
    )


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


def test_qualified_ref_binds_to_known_local_table() -> None:
    """A qualified ref that resolves to a known local table binds to its node.

    Must-fix: qualification ALONE must not force-external. ``mart.member`` is a
    qualified name, but a local table whose canonical_name IS ``mart.member``
    owns that physical name -- the ref must bind to ``ingested_member``, never
    become a phantom ``source('external', ...)``.
    """
    member = UMF(
        version="1.0",
        table_name="member",
        canonical_name="mart.member",
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "member_name", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    reg = NodeRegistry([member, _claims(), _gold_referencing("mart.member")])
    # The qualified ref resolved locally -> NOT dangling, NOT external.
    assert reg.dangling_refs == set()
    gold = reg.plan.nodes["gold_g"]
    assert "ingested_member" in gold.depends_on
    # No external source node was invented.
    assert not any(n.external for n in reg.plan.nodes.values())
    # The renderer resolves the qualified literal to the bound ingested model.
    renderer = DbtRefRenderer(reg)
    assert renderer.render("mart.member") == "{{ ref('ingested_member') }}"


def test_qualified_self_reference_is_not_a_self_dependency() -> None:
    """A candidate naming the table's own qualified canonical_name is not an edge.

    Regression: with qualified-ref binding enabled, a derivation candidate equal
    to the table's OWN (qualified) canonical_name must be recognized as a
    self-reference, never bound back to ``gold_<t>`` as a self-dependency (a
    1-cycle) nor routed external.
    """
    g = UMF(
        version="1.0",
        table_name="g",
        canonical_name="mart.g",
        primary_key=["id"],
        metadata={"base_table": "claims"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "self_col",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    # References its OWN qualified canonical_name.
                    "candidates": [{"table": "mart.g", "column": "x", "priority": 1}],
                },
            },
        ],
    )
    reg = NodeRegistry([_claims(), g])
    gold = reg.plan.nodes["gold_g"]
    assert "gold_g" not in gold.depends_on  # no self-dependency
    assert reg.dangling_refs == set()
    assert not any(n.external for n in reg.plan.nodes.values())
    assert reg.plan.detect_cycle() is None


def test_external_routing_is_scoped_per_table() -> None:
    """A bare unknown ref fails closed even when ANOTHER table marks it external.

    Regression: ``external_names`` must be scoped to the referencing table's own
    cross_pipeline FKs. Table ``a`` declares a cross_pipeline FK to ``refdata``;
    unrelated gold table ``b`` derives from a bare ``refdata`` it does NOT mark
    external -- that must be a DANGLING (fail-closed) ref, not a phantom external.
    """
    a = UMF(
        version="1.0",
        table_name="a",
        primary_key=["id"],
        metadata={"base_table": "claims"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "rd",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "refdata", "column": "v", "priority": 1}],
                },
            },
        ],
        relationships={
            "foreign_keys": [
                {
                    "column": "rd",
                    "references_table": "refdata",
                    "references_column": "v",
                    "cross_pipeline": True,
                }
            ]
        },
    )
    b = _gold_referencing("refdata")  # bare 'refdata', NO external marking on b
    reg = NodeRegistry([_claims(), a, b])
    # 'a' resolves refdata as external (its own cross_pipeline FK); 'b' does not.
    assert ("g", "refdata") in reg.dangling_refs
    with pytest.raises(DbtProjectError):
        generate_dbt_dag_project([_claims(), a, b])


def test_base_table_metadata_creates_edge() -> None:
    """metadata.base_table is a rendered relation -> an IR edge (must-fix 2).

    ``_gold_referencing`` sets ``metadata.base_table='claims'``; the gold node
    must depend on ``ingested_claims`` even though no derivation candidate names
    ``claims`` directly (the base view selects from it).
    """
    reg = NodeRegistry([_member(), _claims(), _gold_referencing("member")])
    gold = reg.plan.nodes["gold_g"]
    assert "ingested_claims" in gold.depends_on  # from metadata.base_table
    assert "ingested_member" in gold.depends_on  # from the derivation candidate


def test_inferred_base_table_hub_creates_edge() -> None:
    """An INFERRED (hub_score) base table that is NOT a candidate still gets an edge.

    Regression: with no explicit ``metadata.base_table``, the RelationshipResolver
    can pick a hub by ``hub_score`` that has outgoing relationships to the
    contributors but contributes no columns itself. The generator renders it as the
    base ``FROM`` relation, so the IR must carry that edge -- reusing the resolver
    keeps the edge set a faithful superset without missing the non-candidate hub.
    """
    card = {
        "type": "many_to_one",
        "notation": "1:1",
        "source_multiplicity": "*",
        "target_multiplicity": "1",
    }
    summary = {
        "hub_score": 99.0,
        "total_relationships": 1,
        "total_incoming": 0,
        "total_outgoing": 1,
    }
    hub = UMF(
        version="1.0",
        table_name="hub",
        primary_key=["id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "dim_id", "data_type": "INTEGER", "nullable": _NL},
        ],
        relationships={
            "summary": summary,
            "outgoing": [
                {
                    "target_table": "dim",
                    "source_column": "dim_id",
                    "target_column": "dim_id",
                    "type": "foreign_to_primary",
                    "confidence": 1.0,
                    "cardinality": card,
                }
            ],
        },
    )
    dim = UMF(
        version="1.0",
        table_name="dim",
        primary_key=["dim_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "dim_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "dim_val", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    # Gold derives ONLY from 'dim'; 'hub' is the resolver's inferred base but is
    # NOT a derivation candidate. No explicit metadata.base_table.
    gold = UMF(
        version="1.0",
        table_name="g",
        primary_key=["id"],
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "dv",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "dim", "column": "dim_val", "priority": 1}
                    ],
                },
            },
        ],
    )
    reg = NodeRegistry([hub, dim, gold])
    gnode = reg.plan.nodes["gold_g"]
    assert "ingested_hub" in gnode.depends_on  # inferred base (non-candidate)
    assert "ingested_dim" in gnode.depends_on  # derivation candidate
    assert reg.dangling_refs == set()


def test_join_via_lookup_table_creates_edge() -> None:
    """join_via.lookup_table is an INNER JOIN relation -> an IR edge (must-fix 2)."""
    lookup = UMF(
        version="1.0",
        table_name="datawarehouse",
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "insurance_policy", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    gold = UMF(
        version="1.0",
        table_name="g2",
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
                "name": "policy",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {
                            "table": "member",
                            "column": "insurance_policy",
                            "priority": 1,
                            "join_via": {
                                "lookup_table": "datawarehouse",
                                "source_key": "client_member_id",
                                "lookup_key": "member_id",
                                "target_key": "insurance_policy",
                            },
                        }
                    ],
                },
            },
        ],
    )
    reg = NodeRegistry([_member(), _claims(), lookup, gold])
    g = reg.plan.nodes["gold_g2"]
    # The lookup table is its own inter-table edge, distinct from the candidate.
    assert "ingested_datawarehouse" in g.depends_on
    assert "ingested_member" in g.depends_on
    assert "ingested_claims" in g.depends_on


def test_union_sources_metadata_creates_edges() -> None:
    """metadata.source_tables (union_sources) each become an IR edge (must-fix 2)."""
    src_a = UMF(
        version="1.0",
        table_name="src_a",
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "member_id", "data_type": "INTEGER", "nullable": _NN}],
    )
    src_b = UMF(
        version="1.0",
        table_name="src_b",
        primary_key=["member_id"],
        ingestion={"mode": "snapshot"},
        columns=[{"name": "member_id", "data_type": "INTEGER", "nullable": _NN}],
    )
    universe = UMF(
        version="1.0",
        table_name="universe",
        primary_key=["member_id"],
        metadata={
            "base_table_strategy": "union_sources",
            "source_tables": ["src_a", "src_b"],
        },
        columns=[
            {
                "name": "member_id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
        ],
    )
    reg = NodeRegistry([src_a, src_b, universe])
    g = reg.plan.nodes["gold_universe"]
    assert {"ingested_src_a", "ingested_src_b"} <= g.depends_on


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
