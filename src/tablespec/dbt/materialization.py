"""Materialization policy: decided on the IR graph, applied at render time.

Corrected-design rules:

  * **ingested staging** -> from ``ingestion.mode``:
      - incremental + primary_key -> ``incremental`` (merge, unique_key=pk)
      - incremental, no pk        -> ``incremental`` (append)
      - snapshot                  -> ``table`` (full reload; NEVER a dbt snapshot)
  * **gold intermediate** (a promoted step/pre-agg/window/member-universe node):
      - ``ephemeral`` ONLY when cheap AND single-fanout AND private
      - ``table`` when expensive OR shared (fanout >= 2)
  * **gold final** -> ``table`` by default. ``incremental`` is NOT chosen
    automatically for joins/aggs/pivots/windows -- only with an explicit,
    documented strategy passed in.

The policy reads facts off the :class:`~tablespec.core.ir.LogicalPlan` (role,
fanout, expensive); it does not re-derive the graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from tablespec.core.ir import LogicalPlan, NodeRole, PlanNode


@dataclass(frozen=True)
class Materialization:
    """A concrete dbt materialization decision for one node."""

    strategy: str  # "table" | "incremental" | "ephemeral" | "view"
    incremental_strategy: str | None = None  # "merge" | "append"
    unique_key: tuple[str, ...] = ()


class MaterializationPolicy:
    """Map a plan node to its dbt :class:`Materialization`.

    Attributes:
        gold_incremental: opt-in map ``{gold_table_name: (incr_strategy, keys)}``
            documenting an explicit incremental strategy for a gold final model.
            Absent -> the gold model is a full ``table`` (the safe default).
    """

    def __init__(
        self,
        gold_incremental: dict[str, tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self._gold_incremental = gold_incremental or {}

    def for_ingested(self, *, mode: str, primary_key: list[str]) -> Materialization:
        """Materialization for an ``ingested_<t>`` staging model."""
        if mode == "incremental" and primary_key:
            return Materialization(
                strategy="incremental",
                incremental_strategy="merge",
                unique_key=tuple(primary_key),
            )
        if mode == "incremental":
            return Materialization(
                strategy="incremental", incremental_strategy="append"
            )
        # snapshot -> full table rebuild (NOT a dbt snapshot resource).
        return Materialization(strategy="table")

    def for_node(
        self, node: PlanNode, plan: LogicalPlan, *, table_name: str = ""
    ) -> Materialization:
        """Materialization for a gold / intermediate node, decided on the graph."""
        if node.role is NodeRole.GOLD:
            explicit = self._gold_incremental.get(table_name)
            if explicit is not None:
                strat, keys = explicit
                return Materialization(
                    strategy="incremental",
                    incremental_strategy=strat,
                    unique_key=keys,
                )
            return Materialization(strategy="table")

        if node.role is NodeRole.INTERMEDIATE:
            fanout = plan.fanout(node.node_id)
            # ephemeral only when cheap AND private (single consumer).
            if not node.expensive and fanout <= 1:
                return Materialization(strategy="ephemeral")
            return Materialization(strategy="table")

        # Sources are never materialized by us; ingested handled separately.
        return Materialization(strategy="table")


__all__ = ["Materialization", "MaterializationPolicy"]
