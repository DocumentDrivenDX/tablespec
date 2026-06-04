"""Logical-plan IR: an explicit dependency graph built BEFORE rendering.

The IR is the corrected design's foundation (per the adversarial review): decide
materialization on the *graph*, then render -- never compute fanout from rendered
strings. Nodes are UMF tables AND generated intermediates (raw sources, ingested
staging models, gold models, and -- when a backend chooses to promote them --
step / pre-agg / window / member-universe intermediates). Edges are static
producer->consumer dependencies.

This module is framework-agnostic: it knows nothing about dbt, SQL dialects, or
materializations. A backend (e.g. ``tablespec.dbt``) reads ``fanout`` / ``role``
/ ``cost`` off these nodes to decide how to package them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeRole(str, Enum):
    """What a node *is* in the layered pipeline."""

    SOURCE = "source"  # external/raw landing relation (a leaf, never built)
    INGESTED = "ingested"  # raw -> typed staging model (one per UMF table)
    GOLD = "gold"  # joined/aggregated serving model
    INTERMEDIATE = "intermediate"  # a generated step shared/private within gold


@dataclass(frozen=True)
class LogicalEdge:
    """A static producer -> consumer dependency edge.

    ``producer`` is the node depended ON; ``consumer`` is the node that ref's it.
    """

    producer: str  # node id
    consumer: str  # node id


@dataclass
class PlanNode:
    """One node in the logical plan.

    Attributes:
        node_id: stable unique id (also the backend's relation/model name).
        role: :class:`NodeRole`.
        physical_names: every literal name this node appears as in generated SQL
            (canonical_name, table_name, namespace-qualified, declared aliases).
            The backend's renderer maps any of these to this node.
        depends_on: node ids this node consumes (its producers).
        external: True when the UMF explicitly marks the relation external; an
            unknown relation that is NOT external must fail closed, never become
            a phantom source.
        expensive: True when the node aggregates / windows / pivots / joins and so
            should not be inlined everywhere (drives materialization).
    """

    node_id: str
    role: NodeRole
    physical_names: set[str] = field(default_factory=set)
    depends_on: set[str] = field(default_factory=set)
    external: bool = False
    expensive: bool = False


@dataclass
class LogicalPlan:
    """The whole graph: nodes keyed by id, plus derived edge/fanout helpers."""

    nodes: dict[str, PlanNode] = field(default_factory=dict)

    def add(self, node: PlanNode) -> PlanNode:
        """Insert *node*, merging physical names / deps if the id already exists."""
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
            return node
        existing.physical_names |= node.physical_names
        existing.depends_on |= node.depends_on
        existing.external = existing.external or node.external
        existing.expensive = existing.expensive or node.expensive
        return existing

    def edges(self) -> list[LogicalEdge]:
        """All producer->consumer edges, sorted for deterministic output."""
        out: list[LogicalEdge] = []
        for consumer in self.nodes.values():
            for producer in consumer.depends_on:
                out.append(LogicalEdge(producer=producer, consumer=consumer.node_id))
        out.sort(key=lambda e: (e.producer, e.consumer))
        return out

    def fanout(self, node_id: str) -> int:
        """Number of distinct consumers that depend on *node_id*."""
        return sum(1 for n in self.nodes.values() if node_id in n.depends_on)

    def detect_cycle(self) -> list[str] | None:
        """Return a cycle as an ordered node-id list, or ``None`` if acyclic.

        Plain iterative DFS over ``depends_on`` (consumer -> producer). A back
        edge to a node on the current stack is a cycle; the returned list is the
        offending ring for a loud failure at generation time.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self.nodes}
        stack_path: list[str] = []

        def visit(nid: str) -> list[str] | None:
            color[nid] = GREY
            stack_path.append(nid)
            for producer in sorted(self.nodes[nid].depends_on):
                if producer not in self.nodes:
                    continue
                if color[producer] == GREY:
                    # Found a back edge -> slice the ring out of the path.
                    idx = stack_path.index(producer)
                    return [*stack_path[idx:], producer]
                if color[producer] == WHITE:
                    found = visit(producer)
                    if found is not None:
                        return found
            stack_path.pop()
            color[nid] = BLACK
            return None

        for nid in sorted(self.nodes):
            if color[nid] == WHITE:
                found = visit(nid)
                if found is not None:
                    return found
        return None


__all__ = [
    "LogicalEdge",
    "LogicalPlan",
    "NodeRole",
    "PlanNode",
]
