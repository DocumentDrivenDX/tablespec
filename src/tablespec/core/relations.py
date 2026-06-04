"""The single dialect/backend seam for rendering relation references.

Every place the SQL generators inline a *relation* (a base table, a join target,
a pre-aggregation view, a member-universe view, the final assembly source) they
route the physical name through a :class:`TableRenderer`. The renderer decides
the literal text that lands in the SQL:

  * :class:`LiteralRenderer` -> the (optionally resolved) bare/qualified name,
    reproducing the historical direct-artifact behaviour byte-for-byte.
  * ``tablespec.dbt.DbtRefRenderer`` -> a ``{{ ref(...) }}`` / ``{{ source(...) }}``
    Jinja literal, so dbt's parser sees a static edge.

This is deliberately a *semantic* contract: the generator asks the renderer for
"the relation named X", it never string-substitutes SQL aliases. A renderer is
free to FAIL CLOSED on an unknown relation (dbt does); the literal renderer is
permissive because the direct artifact runs against a live catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class RelationRef:
    """A semantic reference to a relation, handed to a :class:`TableRenderer`.

    ``physical_name`` is the relation name as the generator computed it (possibly
    namespace-qualified, e.g. ``other_ns.member``). ``kind`` is a coarse hint a
    renderer may use for routing decisions but is NOT required to honour; the
    physical name is the identity.
    """

    physical_name: str
    kind: str = "table"  # "table" | "view" | "source" -- advisory only


@runtime_checkable
class TableRenderer(Protocol):
    """Render a physical relation name to the literal SQL text for one backend.

    Implementations MUST be pure (no I/O) and deterministic: the same name maps
    to the same text within a generation run.
    """

    def render(self, physical_name: str) -> str:
        """Return the literal SQL text for the relation named *physical_name*.

        Raises:
            KeyError / LookupError: a fail-closed renderer may raise when the
                relation is unknown. (The default :class:`LiteralRenderer` never
                raises.)
        """
        ...


class LiteralRenderer:
    """Default renderer: emit the (optionally resolved) name verbatim.

    This is the historical behaviour of ``SQLPlanGenerator._resolve_table_name``:
    if a ``resolver`` callable is supplied (e.g. catalog-qualification), apply it;
    otherwise pass the name through unchanged. It NEVER raises -- the direct
    artifact is executed against a live catalog where unresolved names are valid.
    """

    def __init__(self, resolver: Callable[[str], str] | None = None) -> None:
        self._resolver = resolver

    def render(self, physical_name: str) -> str:
        if self._resolver is not None:
            return self._resolver(physical_name)
        return physical_name


__all__ = ["LiteralRenderer", "RelationRef", "TableRenderer"]
