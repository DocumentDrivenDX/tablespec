"""Core, framework-agnostic seam shared by every table-rendering backend.

This package defines the contract that both the direct Databricks-artifact path
and the dbt path depend on, WITHOUT either path depending on the other and
WITHOUT any dbt-specific logic living here:

  * :class:`~tablespec.core.relations.TableRenderer` -- the one Protocol every
    backend implements to turn a *physical relation name* (as it would appear
    inlined in generated SQL) into the literal text the backend wants there
    (a bare/qualified name for the direct artifact, a ``{{ ref() }}`` /
    ``{{ source() }}`` for dbt).
  * :class:`~tablespec.core.relations.LiteralRenderer` -- the default renderer
    that reproduces the historical "inline the (optionally resolved) name"
    behaviour, so the existing committed artifacts stay byte-for-byte stable.
  * the logical-plan IR in :mod:`tablespec.core.ir` -- an explicit graph of
    table/intermediate nodes with materialization-relevant facts (fanout, role,
    cost) that a backend decides materialization on *before* rendering.

Import rule (enforced by ``tests/test_core_encapsulation.py``): nothing under
``tablespec.core`` may import ``tablespec.dbt``.
"""

from __future__ import annotations

from tablespec.core.ir import (
    LogicalEdge,
    LogicalPlan,
    NodeRole,
    PlanNode,
)
from tablespec.core.registry import (
    NodeRegistry,
    NodeRegistryError,
    ResolvedNode,
)
from tablespec.core.relations import (
    LiteralRenderer,
    RelationRef,
    TableRenderer,
)

__all__ = [
    "LiteralRenderer",
    "LogicalEdge",
    "LogicalPlan",
    "NodeRegistry",
    "NodeRegistryError",
    "NodeRole",
    "PlanNode",
    "RelationRef",
    "ResolvedNode",
    "TableRenderer",
]
