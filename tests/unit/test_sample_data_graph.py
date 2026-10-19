# SPDX-License-Identifier: MIT OR Apache-2.0
"""Unit tests for sample_data.graph module - RelationshipGraph and TableNode."""

import pytest

from tablespec.sample_data.graph import RelationshipGraph, TableNode

pytestmark = pytest.mark.fast


class TestTableNode:
    """Test the TableNode dataclass."""

    def test_default_values(self):
        node = TableNode(name="test", umf_data={"columns": []})
        assert node.name == "test"
        assert node.umf_data == {"columns": []}
        assert node.dependencies == set()
        assert node.dependents == set()
        assert node.generation_order == -1

    def test_custom_values(self):
        node = TableNode(
            name="claims",
            umf_data={"columns": [{"name": "id"}]},
            dependencies={"members"},
            dependents={"lab_results"},
            generation_order=2,
        )
        assert node.dependencies == {"members"}
        assert node.dependents == {"lab_results"}
        assert node.generation_order == 2


class TestRelationshipGraph:
    """Test the RelationshipGraph class."""

    def test_add_table(self):
        graph = RelationshipGraph()
        graph.add_table("members", {"columns": []})
        assert "members" in graph.nodes
        assert graph.nodes["members"].name == "members"

    def test_add_table_idempotent(self):
        graph = RelationshipGraph()
        graph.add_table("members", {"columns": [{"name": "id"}]})
        graph.add_table("members", {"columns": [{"name": "new_id"}]})
        # Should keep the first one
        assert graph.nodes["members"].umf_data == {"columns": [{"name": "id"}]}

    def test_add_relationship(self):
        graph = RelationshipGraph()
        graph.add_table("members", {})
        graph.add_table("claims", {})
        graph.add_relationship("members", "claims")

        assert "members" in graph.nodes["claims"].dependencies
        assert "claims" in graph.nodes["members"].dependents

    def test_add_relationship_ignores_missing_tables(self):
        graph = RelationshipGraph()
        graph.add_table("members", {})
        # "claims" not added - relationship should be silently ignored
        graph.add_relationship("members", "claims")
        assert graph.nodes["members"].dependents == set()

    def test_generation_order_no_dependencies(self):
        graph = RelationshipGraph()
        graph.add_table("a", {})
        graph.add_table("b", {})
        graph.add_table("c", {})
        order = graph.get_generation_order()
        assert set(order) == {"a", "b", "c"}
        assert len(order) == 3

    def test_generation_order_linear_chain(self):
        graph = RelationshipGraph()
        graph.add_table("members", {})
        graph.add_table("claims", {})
        graph.add_table("lab_results", {})
        graph.add_relationship("members", "claims")
        graph.add_relationship("claims", "lab_results")

        order = graph.get_generation_order()
        assert order.index("members") < order.index("claims")
        assert order.index("claims") < order.index("lab_results")

    def test_generation_order_diamond(self):
        """Test diamond dependency: A -> B, A -> C, B -> D, C -> D."""
        graph = RelationshipGraph()
        graph.add_table("A", {})
        graph.add_table("B", {})
        graph.add_table("C", {})
        graph.add_table("D", {})
        graph.add_relationship("A", "B")
        graph.add_relationship("A", "C")
        graph.add_relationship("B", "D")
        graph.add_relationship("C", "D")

        order = graph.get_generation_order()
        assert order[0] == "A"
        assert order[-1] == "D"
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_generation_order_assigns_order_numbers(self):
        graph = RelationshipGraph()
        graph.add_table("members", {})
        graph.add_table("claims", {})
        graph.add_relationship("members", "claims")

        graph.get_generation_order()
        assert graph.nodes["members"].generation_order == 0
        assert graph.nodes["claims"].generation_order == 1

    def test_cycle_detection_uses_heuristic(self):
        """When a cycle exists, should fall back to heuristic ordering."""
        graph = RelationshipGraph()
        graph.add_table("A", {})
        graph.add_table("B", {})
        graph.add_relationship("A", "B")
        graph.add_relationship("B", "A")

        order = graph.get_generation_order()
        # Should still return all tables (heuristic ordering)
        assert set(order) == {"A", "B"}

    def test_heuristic_order_prefers_fewer_dependencies(self):
        """Heuristic should prefer tables with fewer dependencies."""
        graph = RelationshipGraph()
        graph.add_table("member_table", {})
        graph.add_table("claims_table", {})
        graph.add_table("supplemental_table", {})
        # Create cycle
        graph.add_relationship("member_table", "claims_table")
        graph.add_relationship("claims_table", "supplemental_table")
        graph.add_relationship("supplemental_table", "member_table")

        order = graph.get_generation_order()
        assert set(order) == {"member_table", "claims_table", "supplemental_table"}
        # member_table has domain priority 0 (contains "member") and fewer deps
        assert order[0] == "member_table"

    def test_heuristic_domain_priority(self):
        """Test domain-specific priority ordering in heuristic."""
        graph = RelationshipGraph()
        graph.add_table("lab_results", {})
        graph.add_table("outreach_list", {})
        graph.add_table("medical_claims", {})
        graph.add_table("supplemental_data", {})
        graph.add_table("other_table", {})

        # Create cycle so heuristic is used
        graph.add_relationship("lab_results", "outreach_list")
        graph.add_relationship("outreach_list", "medical_claims")
        graph.add_relationship("medical_claims", "supplemental_data")
        graph.add_relationship("supplemental_data", "other_table")
        graph.add_relationship("other_table", "lab_results")

        order = graph.get_generation_order()
        assert set(order) == {
            "lab_results",
            "outreach_list",
            "medical_claims",
            "supplemental_data",
            "other_table",
        }

    def test_analyze_cycle_returns_details(self):
        """Test _analyze_cycle gives useful information."""
        graph = RelationshipGraph()
        graph.add_table("A", {})
        graph.add_table("B", {})
        graph.add_relationship("A", "B")
        graph.add_relationship("B", "A")

        # Simulate incomplete topological sort
        in_degree = {"A": 1, "B": 1}
        result = graph._analyze_cycle(in_degree, [])
        assert "Cycle participants" in result
        assert "A" in result
        assert "B" in result

    def test_analyze_cycle_empty_participants(self):
        graph = RelationshipGraph()
        graph.add_table("A", {})
        result = graph._analyze_cycle({"A": 0}, ["A"])
        assert "Unable to identify" in result

    def test_empty_graph(self):
        graph = RelationshipGraph()
        order = graph.get_generation_order()
        assert order == []
