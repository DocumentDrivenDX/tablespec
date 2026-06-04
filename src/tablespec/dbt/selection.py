"""Map an engine-agnostic :class:`ChangeSet` to a dbt ``--select`` expression.

This is the ONLY dbt-aware piece of the ``state:modified``-style CI selection.
The core (``tablespec.core.selection``) computes *which tables changed*; this
module turns the affected logical ``table_name``s into the concrete dbt node
names that will be emitted for them (``ingested_<t>`` for a landing table,
``gold_<t>`` for a pure-gold table) and unions them with a trailing ``+`` so dbt
selects each changed model AND its descendants (the graph fanout).

Why an explicit union rather than the dbt-native ``state:modified+``:
``state:modified+ --state <prior-manifest>`` is an EQUIVALENT alternative for CI
that has a stored manifest, but it depends on manifest state and a deferred
comparison that is awkward to assert deterministically. The explicit graph-fanout
union ``ingested_member+ gold_x+ ...`` resolves through dbt's own graph (a
trailing ``+`` IS the descendant operator) to exactly the changed models plus
their descendants, with no manifest dependency -- so it is the asserted,
deterministic mechanism. :func:`state_modified_expression` documents the native
form for callers who prefer it.

Empty-selection contract: an empty :class:`ChangeSet` MUST NOT fall through to
selecting the whole project. :data:`EMPTY_SELECTION` is a concrete, safe
*unsatisfiable* selector (``fqn:__tablespec_none__``) that dbt accepts (exit 0)
and that matches ZERO nodes -- so ``dbt ls --select <expr>`` prints nothing and
``dbt build --select <expr>`` reports 0 models.

This module imports NO ``dbt`` package -- it is pure text emission over the
:class:`~tablespec.dbt.registry.NodeRegistry` (which is itself dbt-package-free).
"""

from __future__ import annotations

from tablespec.core.selection import ChangeSet
from tablespec.dbt.registry import NodeRegistry

# A deterministic, PROVABLY-unsatisfiable dbt selector for the empty ChangeSet.
#
# It is the INTERSECTION (dbt ``,`` operator) of two ``fqn:`` selectors for two
# DIFFERENT reserved sentinel literals. ``fqn:`` matches a node when the literal
# equals one of its FQN path segments; a node can match only ONE distinct literal
# per segment, so no single node can satisfy BOTH ``__tablespec_none_a__`` AND
# ``__tablespec_none_b__`` at once -- the intersection is empty for ANY project,
# independent of how nodes happen to be named (it does not rely on a single
# sentinel never colliding with a real FQN segment). dbt accepts the expression
# (exit 0) and selects zero nodes.
#
# This is the canonical "select nothing" contract for an empty ChangeSet -- NEVER
# the empty string (which dbt treats as "no filter" => the WHOLE project) and
# NEVER a silent fall-through to building everything.
EMPTY_SELECTION = "fqn:__tablespec_none_a__,fqn:__tablespec_none_b__"


def _model_ids_for_table(table: str, registry: NodeRegistry) -> list[str]:
    """The emitted MODEL node ids for *table* (``ingested_<t>`` / ``gold_<t>``).

    A landing table contributes ``ingested_<table>``; a pure-gold table
    contributes ``gold_<table>``; a table that is BOTH (has a staging landing AND
    cross-table derivations) contributes both. Sources (``raw_<t>``) are excluded
    -- they are not buildable models. A table absent from the rendered set (e.g. a
    changed UMF that produces no model, or a removed table) contributes nothing.
    """
    ids: list[str] = []
    if table in registry.staging_tables:
        ids.append(f"ingested_{table}")
    if table in registry.gold_tables:
        ids.append(f"gold_{table}")
    return ids


def select_expression(change_set: ChangeSet, registry: NodeRegistry) -> str:
    """Render the dbt ``--select`` expression for *change_set* over *registry*.

    For every AFFECTED table (modified or added; removed tables are excluded by
    :attr:`ChangeSet.affected` so a deleted model is never referenced), emit each
    of its model node ids with a trailing ``+`` (descendant fanout), space-joined
    into one selection.

    Returns:
        A space-separated union like ``ingested_member+ gold_x+``. When the
        :class:`ChangeSet` selects no buildable model (empty set, or only removed
        / unrendered tables), returns :data:`EMPTY_SELECTION` -- the unsatisfiable
        selector that matches zero nodes (never the whole project).
    """
    selectors: list[str] = []
    for table in sorted(change_set.affected):
        for node_id in _model_ids_for_table(table, registry):
            selectors.append(f"{node_id}+")
    if not selectors:
        return EMPTY_SELECTION
    return " ".join(selectors)


def state_modified_expression() -> str:
    """The dbt-native EQUIVALENT selector for CI that stores a prior manifest.

    ``state:modified+`` selects every node dbt detects as modified against the
    ``--state <prior-manifest>`` baseline, plus descendants. It is offered as a
    documented alternative to :func:`select_expression`; the explicit-union form
    is the asserted, manifest-independent mechanism.
    """
    return "state:modified+"


__all__ = [
    "EMPTY_SELECTION",
    "select_expression",
    "state_modified_expression",
]
