"""Build the logical-plan IR and the physical-name -> node index from a UMF set.

This is the corrected design's "IR FIRST" step. Given the whole table set we:

  1. classify each UMF table as *staging-only* (no cross-table derivations) or
     *gold* (its columns derive from OTHER tables),
  2. create the nodes: a ``raw_<t>`` SOURCE + an ``ingested_<t>`` INGESTED model
     per table, plus a ``gold_<t>`` GOLD model for every gold table,
  3. wire static dependency edges (ingested -> its raw source; gold -> the
     ingested models of every table it references), and
  4. index every *physical name* a node can appear as (table_name, canonical_name,
     namespace-qualified ``ns.table``, declared aliases) so the renderer resolves
     any literal the SQL generator emits.

Materialization is decided later on this graph (fanout/role/expensive). Nothing
here renders SQL or knows about dbt Jinja; it produces the engine-agnostic
:class:`~tablespec.core.ir.LogicalPlan` plus a name index the renderer consumes.
"""

from __future__ import annotations

from dataclasses import dataclass

from tablespec.core.ir import LogicalPlan, NodeRole, PlanNode
from tablespec.models.umf import UMF


def _bare(name: str) -> str:
    """Strip a leading ``namespace.`` qualifier from a relation name."""
    return name.split(".", 1)[1] if "." in name else name


def _namespace(name: str) -> str | None:
    """Return the ``namespace`` of a qualified ``namespace.table`` name, else None."""
    return name.split(".", 1)[0] if "." in name else None


def _norm(name: str) -> str:
    """Normalize a relation name for index lookup, PRESERVING any namespace.

    Namespace-preserving is load-bearing for fail-closed routing: a qualified
    cross-pipeline reference like ``other.member`` must NOT collide with a local
    bare ``member`` node (which would silently re-route a cross-pipeline edge into
    the local pipeline). Local same-pipeline references are emitted bare and so
    resolve against the bare-indexed local nodes; a qualified reference only
    resolves if a node explicitly registered that exact qualified physical name
    (e.g. an external SOURCE node), otherwise it fails closed.
    """
    return name.strip().lower()


@dataclass(frozen=True)
class ResolvedNode:
    """A registry hit: the node id plus its role (for the renderer's routing)."""

    node_id: str
    role: NodeRole
    external: bool = False  # True for a source('external', ...) leaf


class NodeRegistry:
    """Index physical relation names to logical-plan nodes for a UMF set.

    The registry owns the :class:`LogicalPlan` and the ``physical name -> node``
    map. ``resolve`` is fail-closed: an unknown name returns ``None`` so the
    renderer raises rather than inventing a phantom source (unless the UMF marked
    the relation external, in which case an external SOURCE node exists for it).
    """

    def __init__(self, umfs: list[UMF]) -> None:
        self._umfs: dict[str, UMF] = {}
        self.plan = LogicalPlan()
        self._by_name: dict[str, ResolvedNode] = {}
        self._gold_tables: set[str] = set()
        self._staging_tables: set[str] = set()
        self._dangling_refs: set[tuple[str, str]] = set()
        self._build(umfs)

    # -- construction -------------------------------------------------------

    def _table_referenced_tables(self, umf: UMF) -> set[str]:
        """Names of OTHER tables this table's derivations reference.

        Qualification is PRESERVED: a same-pipeline reference stays bare (e.g.
        ``member``) and a cross-pipeline reference stays qualified (e.g.
        ``other.member``). Pass 3 uses the qualification to route cross-pipeline
        refs to external sources rather than mis-binding them to a local table.
        """
        refs: set[str] = set()
        self_names = {umf.table_name.lower()}
        if umf.canonical_name:
            self_names.add(umf.canonical_name.lower())
        for col in umf.columns:
            if not col.derivation or not col.derivation.candidates:
                continue
            for cand in col.derivation.candidates:
                if not cand.table:
                    continue
                bare = _bare(cand.table)
                # "intermediate" / "member_universe" are in-model pseudo-tables,
                # never an inter-table edge.
                if bare.lower() in {"intermediate", "member_universe"}:
                    continue
                if _namespace(cand.table) is None and bare.lower() in self_names:
                    continue
                refs.add(cand.table)
        return refs

    def _index(self, node: PlanNode, names: set[str]) -> None:
        for raw in names:
            self._by_name[_norm(raw)] = ResolvedNode(
                node.node_id, node.role, external=node.external
            )
            node.physical_names.add(raw)

    def _external_ref_names(self, umf: UMF) -> set[str]:
        """Names a UMF explicitly marks external (cross-pipeline foreign keys).

        Such a reference is intentionally OUTSIDE this pipeline; it routes to a
        ``source('external', ...)`` leaf rather than failing closed. Only FKs
        flagged ``cross_pipeline`` qualify -- everything else must resolve to a
        local node or be reported as dangling.
        """
        out: set[str] = set()
        if umf.relationships and umf.relationships.foreign_keys:
            for fk in umf.relationships.foreign_keys:
                if fk.cross_pipeline:
                    out.add(fk.references_table.lower())
        return out

    def _build(self, umfs: list[UMF]) -> None:
        # Pass 1: register tables + classify gold vs staging.
        ref_map: dict[str, set[str]] = {}
        staging_tables: set[str] = set()
        external_names: set[str] = set()
        for umf in umfs:
            self._umfs[umf.table_name] = umf
            external_names |= self._external_ref_names(umf)
            refs = self._table_referenced_tables(umf)
            ref_map[umf.table_name] = refs
            if refs:
                self._gold_tables.add(umf.table_name)
            else:
                # A table with NO cross-table derivations is a raw landing table:
                # it gets a raw_<t> source + ingested_<t> staging model. A gold
                # table (has cross-table refs) is derived -- no raw landing.
                staging_tables.add(umf.table_name)
        self._staging_tables = staging_tables

        # Pass 2: create source + ingested nodes (only for real landing tables).
        for umf in umfs:
            t = umf.table_name
            if t not in staging_tables:
                # Pure-gold table: its physical names resolve to the GOLD node so
                # any inter-table reference to it lands on gold_<t>, not a phantom
                # ingested_<t> / raw_<t>.
                continue
            raw_id = f"raw_{t}"
            source_node = PlanNode(
                node_id=raw_id,
                role=NodeRole.SOURCE,
                external=False,
            )
            self.plan.add(source_node)
            # Raw source is addressed by its raw_<t> identifier only.
            self._index(source_node, {raw_id})

            ingested_node = PlanNode(
                node_id=f"ingested_{t}",
                role=NodeRole.INGESTED,
                depends_on={raw_id},
            )
            self.plan.add(ingested_node)
            self._index(ingested_node, self._physical_aliases(umf))

        # Pass 3: gold nodes + their inter-table edges (gold -> ingested_<ref>).
        for umf in umfs:
            if umf.table_name not in self._gold_tables:
                continue
            t = umf.table_name
            gold_id = f"gold_{t}"
            deps: set[str] = set()
            for ref in sorted(ref_map[t]):
                is_qualified = _namespace(ref) is not None
                is_external = is_qualified or _bare(ref).lower() in external_names
                ref_umf = None if is_qualified else self._lookup_umf(ref)
                if ref_umf is None:
                    if is_external:
                        # Explicitly external (qualified cross-pipeline ref or a
                        # cross_pipeline FK): a source('external', ...) leaf, not a
                        # local model. Register it so the renderer routes it.
                        ext_id = self._external_source_id(ref)
                        ext_node = PlanNode(
                            node_id=ext_id,
                            role=NodeRole.SOURCE,
                            external=True,
                        )
                        self.plan.add(ext_node)
                        self._index(ext_node, {ref})
                        deps.add(ext_id)
                        continue
                    # A gold table references a relation that is in NO UMF and is
                    # not external. Record it so the project generator can FAIL
                    # CLOSED instead of silently dropping a dependency (which the
                    # RelationshipResolver would otherwise do for an unknown table).
                    self._dangling_refs.add((t, ref))
                    continue
                # A reference to a staging table -> its ingested model; a reference
                # to another (pure-)gold table -> that gold model.
                if ref_umf.table_name in staging_tables:
                    deps.add(f"ingested_{ref_umf.table_name}")
                else:
                    deps.add(f"gold_{ref_umf.table_name}")
            gold_node = PlanNode(
                node_id=gold_id,
                role=NodeRole.GOLD,
                depends_on=deps,
                expensive=True,  # gold = joins/aggs -> never inline
            )
            self.plan.add(gold_node)
            gold_names = {gold_id}
            if t not in staging_tables:
                # Pure-gold table: its own physical names address the gold node
                # (there is no ingested_<t> to point at).
                gold_names |= self._physical_aliases(umf)
            self._index(gold_node, gold_names)

    @staticmethod
    def _external_source_id(ref: str) -> str:
        """Stable dbt identifier for an external relation reference.

        ``other.member`` -> ``other__member``; bare ``foo`` -> ``foo`` (sanitized
        to a valid identifier so it can be a dbt source table name).
        """
        return ref.replace(".", "__")

    def _physical_aliases(self, umf: UMF) -> set[str]:
        """Every literal name the SQL generator may emit for *umf*'s relation."""
        names = {umf.table_name}
        if umf.canonical_name:
            names.add(umf.canonical_name)
        for alias in umf.aliases or []:
            names.add(alias)
        return names

    def _lookup_umf(self, name: str) -> UMF | None:
        target = _norm(name)
        for umf in self._umfs.values():
            if _norm(umf.table_name) == target:
                return umf
            if umf.canonical_name and _norm(umf.canonical_name) == target:
                return umf
            for alias in umf.aliases or []:
                if _norm(alias) == target:
                    return umf
        return None

    # -- queries ------------------------------------------------------------

    def resolve(self, physical_name: str) -> ResolvedNode | None:
        """Resolve a literal relation name to its node, or ``None`` (fail closed)."""
        return self._by_name.get(_norm(physical_name))

    @property
    def gold_tables(self) -> set[str]:
        """Table names classified as gold (have cross-table derivations)."""
        return set(self._gold_tables)

    @property
    def staging_tables(self) -> set[str]:
        """Table names with a real raw landing (an ``ingested_<t>`` model)."""
        return set(self._staging_tables)

    @property
    def dangling_refs(self) -> set[tuple[str, str]]:
        """``(gold_table, referenced_name)`` pairs where the ref is in no UMF.

        Non-empty means a gold table depends on a relation that is neither a known
        table nor external -- the project generator fails closed on these.
        """
        return set(self._dangling_refs)

    def umf(self, table_name: str) -> UMF:
        """Return the UMF for *table_name* (raises KeyError if unknown)."""
        return self._umfs[table_name]

    def all_umfs(self) -> list[UMF]:
        """Every UMF in registration order."""
        return list(self._umfs.values())


__all__ = ["NodeRegistry", "ResolvedNode"]
