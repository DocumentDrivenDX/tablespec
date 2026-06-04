"""Direct unit tests for the logical-plan IR (tablespec.core.ir).

The IR is framework-agnostic (no dbt, no SQL). These tests pin its primitives:
node merge-on-add, edge enumeration/sorting, fanout counting, and cycle detection
(including the self-loop and the producer-not-in-graph guard).
"""

from __future__ import annotations

import pytest

from tablespec.core.ir import LogicalEdge, LogicalPlan, NodeRole, PlanNode

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_add_new_node_returns_it():
    plan = LogicalPlan()
    node = PlanNode(node_id="a", role=NodeRole.SOURCE)
    assert plan.add(node) is node
    assert plan.nodes["a"] is node


def test_add_existing_merges_names_deps_and_flags():
    plan = LogicalPlan()
    plan.add(
        PlanNode(
            node_id="a",
            role=NodeRole.INGESTED,
            physical_names={"a"},
            depends_on={"raw_a"},
            external=False,
            expensive=False,
        )
    )
    merged = plan.add(
        PlanNode(
            node_id="a",
            role=NodeRole.INGESTED,
            physical_names={"alias_a"},
            depends_on={"raw_a2"},
            external=True,
            expensive=True,
        )
    )
    # The original node is returned, with unions applied and OR'd flags.
    assert merged.physical_names == {"a", "alias_a"}
    assert merged.depends_on == {"raw_a", "raw_a2"}
    assert merged.external is True
    assert merged.expensive is True


def test_edges_are_exact_and_sorted_producer_then_consumer():
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="raw", role=NodeRole.SOURCE))
    plan.add(PlanNode(node_id="b", role=NodeRole.GOLD, depends_on={"raw", "a"}))
    plan.add(PlanNode(node_id="a", role=NodeRole.INGESTED, depends_on={"raw"}))
    edges = plan.edges()
    # EXACT edge set -- no omissions (e.g. the direct raw->b edge) and no extras.
    assert edges == [
        LogicalEdge(producer="a", consumer="b"),
        LogicalEdge(producer="raw", consumer="a"),
        LogicalEdge(producer="raw", consumer="b"),
    ]
    # already sorted by (producer, consumer)
    assert edges == sorted(edges, key=lambda e: (e.producer, e.consumer))


def test_fanout_counts_distinct_consumers():
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="shared", role=NodeRole.INTERMEDIATE))
    plan.add(PlanNode(node_id="c1", role=NodeRole.GOLD, depends_on={"shared"}))
    plan.add(PlanNode(node_id="c2", role=NodeRole.GOLD, depends_on={"shared"}))
    assert plan.fanout("shared") == 2
    assert plan.fanout("c1") == 0


def test_detect_cycle_none_when_acyclic():
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="raw", role=NodeRole.SOURCE))
    plan.add(PlanNode(node_id="a", role=NodeRole.INGESTED, depends_on={"raw"}))
    assert plan.detect_cycle() is None


def test_detect_cycle_finds_two_node_ring():
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="a", role=NodeRole.GOLD, depends_on={"b"}))
    plan.add(PlanNode(node_id="b", role=NodeRole.GOLD, depends_on={"a"}))
    cycle = plan.detect_cycle()
    assert cycle is not None
    assert cycle[0] == cycle[-1]  # ring closes on itself
    assert set(cycle) == {"a", "b"}


def test_detect_cycle_self_loop():
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="a", role=NodeRole.GOLD, depends_on={"a"}))
    cycle = plan.detect_cycle()
    assert cycle == ["a", "a"]


def test_detect_cycle_ignores_producer_not_in_graph():
    """A dependency on an unregistered id is skipped, not treated as a cycle."""
    plan = LogicalPlan()
    plan.add(PlanNode(node_id="a", role=NodeRole.GOLD, depends_on={"ghost"}))
    assert plan.detect_cycle() is None
