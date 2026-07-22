"""Relationship graph for table dependency ordering."""

from collections import deque
from dataclasses import dataclass, field
import logging
from typing import Any


@dataclass
class TableNode:
    """Represents a table in the relationship graph."""

    name: str
    umf_data: dict[str, Any]
    dependencies: set[str] = field(default_factory=set)
    dependents: set[str] = field(default_factory=set)
    generation_order: int = -1


class RelationshipGraph:
    """Manages table dependencies and generation ordering."""

    def __init__(self) -> None:
        self.nodes: dict[str, TableNode] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_table(self, table_name: str, umf_data: dict[str, Any]) -> None:
        """Add a table to the dependency graph."""
        if table_name not in self.nodes:
            self.nodes[table_name] = TableNode(table_name, umf_data)

    def add_relationship(self, source_table: str, target_table: str) -> None:
        """Add a dependency relationship."""
        if source_table in self.nodes and target_table in self.nodes:
            # Target depends on source (source must be generated first)
            self.nodes[target_table].dependencies.add(source_table)
            self.nodes[source_table].dependents.add(target_table)

    def get_generation_order(self) -> list[str]:
        """Get topologically sorted order for table generation."""
        # Kahn's algorithm for topological sorting
        in_degree = {name: len(node.dependencies) for name, node in self.nodes.items()}
        queue = deque([name for name, degree in in_degree.items() if degree == 0])
        result = []

        while queue:
            current = queue.popleft()
            result.append(current)

            # Reduce in-degree for dependent tables
            for dependent in self.nodes[current].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self.nodes):
            # Cycle detected - analyze and log details
            cycle_details = self._analyze_cycle(in_degree, result)
            self.logger.warning(
                f"Cycle detected in relationships\n{cycle_details}\nUsing heuristic ordering"
            )
            return self._get_heuristic_order()

        # Assign generation order
        for i, table_name in enumerate(result):
            self.nodes[table_name].generation_order = i

        self.logger.info(f"Generation order: {' → '.join(result)}")
        return result

    def _analyze_cycle(
        self, in_degree: dict[str, int], completed_sort: list[str]
    ) -> str:
        """Analyze and format details about detected cycles.

        Args:
            in_degree: Current in-degree counts after topological sort attempt
            completed_sort: List of successfully sorted tables (incomplete due to cycle)

        Returns:
            Formatted string describing cycle participants and their dependencies

        """
        # Find tables not included in completed sort (cycle participants)
        completed_set = set(completed_sort)
        cycle_participants = [
            table_name for table_name in self.nodes if table_name not in completed_set
        ]

        if not cycle_participants:
            return "Unable to identify specific cycle participants"

        # Build detailed information about each participant
        details = [f"Cycle participants ({len(cycle_participants)} tables):"]
        for table_name in sorted(cycle_participants):
            node = self.nodes[table_name]
            deps = sorted(node.dependencies)
            if deps:
                details.append(f"  - {table_name} depends on: {deps}")
            else:
                details.append(f"  - {table_name} (no dependencies)")

        return "\n".join(details)

    def _get_heuristic_order(self) -> list[str]:
        """Fallback ordering based on healthcare domain knowledge.

        When a cycle is detected, prioritize tables with fewer dependencies first,
        then order by domain priority patterns (outreach/member tables before claims/supplemental).
        """
        available_tables = set(self.nodes.keys())

        # Group tables by dependency count and domain patterns
        def get_priority_key(table_name: str) -> tuple[int, int, str]:
            """Return (dependency_count, domain_priority, name) for sorting."""
            node = self.nodes[table_name]
            dependency_count = len(node.dependencies)

            # Domain priority (lower = higher priority)
            name_lower = table_name.lower()
            if "outreach" in name_lower or "member" in name_lower:
                domain_priority = 0
            elif (
                "medical" in name_lower
                or "pharmacy" in name_lower
                or "claims" in name_lower
            ):
                domain_priority = 1
            elif "supplemental" in name_lower or "contact" in name_lower:
                domain_priority = 2
            elif "lab" in name_lower or "results" in name_lower:
                domain_priority = 3
            else:
                domain_priority = 4

            return (dependency_count, domain_priority, table_name)

        # Sort tables by priority
        ordered = sorted(available_tables, key=get_priority_key)

        self.logger.info(
            f"Using heuristic ordering based on dependency count and domain patterns: {' → '.join(ordered)}"
        )
        return ordered


__all__ = ["RelationshipGraph", "TableNode"]
