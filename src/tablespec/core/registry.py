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

This module is part of ``tablespec.core``: it is framework-agnostic IR
construction shared by every backend (the dbt emitter, the LDP emitter). It
imports only ``tablespec.core.ir``, the UMF model, and -- lazily, for inferred
base-table enumeration -- ``tablespec.schemas.relationship_resolver``; it never
imports ``tablespec.dbt`` or ``tablespec.ldp``. ``tablespec.dbt.registry``
re-exports these names for backward compatibility.
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


class NodeRegistryError(ValueError):
    """Raised when the UMF set cannot be indexed unambiguously (name collision)."""


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

        This is the SAME relation enumeration the ``SQLPlanGenerator`` /
        ``RelationshipResolver`` use to decide what the rendered plan inlines, so
        the IR edge set is a superset-faithful model of the rendered refs. It
        unions every relation literal the generator can emit:

          * derivation-candidate source tables (``col.derivation.candidates[].table``),
          * an explicit ``metadata.base_table`` (the plan's hub view),
          * ``metadata.source_tables`` for the ``union_sources`` base strategy
            (each contributes a join into ``member_universe``), and
          * ``join_via.lookup_table`` pre-aggregation lookups (an INNER JOIN
            relation the plan inlines, distinct from the candidate's own table).

        Qualification is PRESERVED: a same-pipeline reference stays bare (e.g.
        ``member``) and a cross-pipeline reference stays qualified (e.g.
        ``other.member``). Pass 3 first tries to bind any ref (bare OR qualified)
        to a known local table; only a genuinely-absent ref that is explicitly
        external routes to a ``source('external', ...)`` leaf.

        Faithfulness notes (matched against the generator's actual render sites):

          * An *inferred* base table (no explicit ``metadata.base_table``; the
            ``RelationshipResolver`` picks a hub by ``hub_score`` / relationship
            count) need NOT be a derivation candidate -- the resolver can select a
            table that has outgoing relationships to the contributors but supplies
            no columns. That hub is still rendered as the base ``FROM`` relation,
            so it is enumerated separately in ``_build`` (Pass 1b) by reusing the
            resolver itself; see :meth:`_inferred_base_table`.
          * A *qualified* aggregate candidate is the one render site that strips
            qualification: the pre-aggregation path uses the BARE name. That
            combination (a qualified ``pipeline.table`` candidate carrying an
            aggregate expression) is not produced by any current UMF; were it
            introduced, the bare form would need binding here. It is intentionally
            NOT auto-bound, because doing so could silently re-route a genuine
            cross-pipeline qualified reference into the local pipeline (the exact
            anti-pattern the qualification-preserving routing guards against).
        """
        refs: set[str] = set()
        # A "self name" is any literal that addresses THIS table: its table_name,
        # its (possibly-qualified) canonical_name, and its declared aliases. We
        # compare both the FULL normalized literal and -- for an unqualified self
        # name only -- its bare form, so a ref equal to a QUALIFIED canonical_name
        # (e.g. ``mart.member`` for the table whose canonical_name is that) is
        # recognized as a self-reference and never becomes a self-dependency.
        self_full = {_norm(umf.table_name)}
        self_bare = {_bare(umf.table_name).lower()}
        if umf.canonical_name:
            self_full.add(_norm(umf.canonical_name))
            if _namespace(umf.canonical_name) is None:
                self_bare.add(umf.canonical_name.lower())
        for alias in umf.aliases or []:
            self_full.add(_norm(alias))
            if _namespace(alias) is None:
                self_bare.add(alias.lower())

        def _add(name: str | None) -> None:
            if not name:
                return
            bare = _bare(name)
            # "intermediate" / "member_universe" are in-model pseudo-tables (the
            # generator's own base/step views), never an inter-table edge.
            if bare.lower() in {"intermediate", "member_universe"}:
                return
            # A self-reference is not an inter-table edge. Match the full literal
            # (covers a qualified canonical_name self-ref) OR, for an unqualified
            # ref, its bare form against the bare self names.
            if _norm(name) in self_full:
                return
            if _namespace(name) is None and bare.lower() in self_bare:
                return
            refs.add(name)

        # 1. Derivation-candidate source tables + their join_via lookup tables.
        for col in umf.columns:
            if not col.derivation or not col.derivation.candidates:
                continue
            for cand in col.derivation.candidates:
                _add(cand.table)
                if cand.join_via:
                    _add(cand.join_via.lookup_table)

        # 2. Base-table / union-source relations from metadata.
        if umf.metadata:
            _add(getattr(umf.metadata, "base_table", None))
            if umf.metadata.base_table_strategy == "union_sources":
                for src in umf.metadata.source_tables or []:
                    _add(src)

        return refs

    def _inferred_base_table(self, umf: UMF) -> str | None:
        """The base table the ``RelationshipResolver`` would render for *umf*.

        Reuses the resolver (the authoritative enumeration) so the IR does not
        duplicate hub-inference logic. Returns the resolved ``base_table`` or
        ``None`` when the resolver cannot place one (e.g. no relationships).
        """
        from tablespec.schemas.relationship_resolver import RelationshipResolver

        resolver = RelationshipResolver(dict(self._umfs))
        try:
            plan = resolver.resolve_plan(umf)
        except Exception:  # noqa: BLE001 - inference is best-effort; never block build
            return None
        return plan.base_table

    def _index(self, node: PlanNode, names: set[str]) -> None:
        for raw in names:
            key = _norm(raw)
            existing = self._by_name.get(key)
            # FAIL CLOSED on a genuine collision: the SAME physical name already
            # resolves to a DIFFERENT node. Silently overwriting would let one
            # table's canonical_name/alias hijack another's relation reference
            # (last-write-wins), routing edges to the wrong model. Re-indexing the
            # SAME node under a name it already owns is fine (idempotent merge).
            if existing is not None and existing.node_id != node.node_id:
                msg = (
                    f"Physical relation name {raw!r} is claimed by two different "
                    f"nodes ({existing.node_id!r} and {node.node_id!r}). A "
                    f"table_name / canonical_name / alias must be unique across the "
                    f"UMF set so every reference resolves unambiguously."
                )
                raise NodeRegistryError(msg)
            self._by_name[key] = ResolvedNode(
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
        # external_by_table is SCOPED per referencing table: a bare ref is external
        # only when THIS table's own cross_pipeline FK marks it. A different
        # table's cross_pipeline FK must NOT make an unrelated table's bare unknown
        # ref fail-open -- that would mask a genuine dangling reference.
        external_by_table: dict[str, set[str]] = {}
        staging_tables: set[str] = set()
        for umf in umfs:
            # FAIL CLOSED on a duplicate table_name BEFORE registering it. Two
            # UMFs with the same table_name produce identical node ids
            # (``ingested_<t>`` / ``gold_<t>``), so the ``_index`` collision guard
            # -- which only fires when the SAME physical name maps to DIFFERENT
            # node ids -- never trips: the second silently overwrites the first in
            # ``self._umfs`` (last-write-wins), dropping a whole table's spec.
            table_key = _norm(umf.table_name)
            if table_key in {_norm(t) for t in self._umfs}:
                msg = (
                    f"Duplicate table_name {umf.table_name!r} in the UMF set. "
                    f"Every table_name must be unique so its ingested_/gold_ node "
                    f"is unambiguous; a repeat silently clobbers the prior table."
                )
                raise NodeRegistryError(msg)
            self._umfs[umf.table_name] = umf
            external_by_table[umf.table_name] = self._external_ref_names(umf)
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

        # Pass 1b: augment each gold table's ref set with its INFERRED base table.
        # When a gold table has no explicit ``metadata.base_table`` / union sources,
        # the RelationshipResolver picks a hub (by ``hub_score`` / relationship
        # count). That hub is rendered as the base ``FROM`` relation but need not be
        # a derivation candidate (it can be a table with outgoing relationships TO
        # the contributors). Reuse the SAME resolver so the IR edge set stays a
        # faithful superset of the rendered refs -- no duplicated inference logic.
        # This only ADDS an edge to an already-gold table; it never reclassifies.
        for t in sorted(self._gold_tables):
            umf = self._umfs[t]
            has_explicit_base = bool(
                umf.metadata
                and (
                    getattr(umf.metadata, "base_table", None)
                    or umf.metadata.base_table_strategy == "union_sources"
                )
            )
            if has_explicit_base:
                continue
            inferred = self._inferred_base_table(umf)
            if inferred and inferred.lower() != t.lower():
                ref_map[t].add(inferred)

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
        # external_source_refs maps a sanitized dbt source id back to the ORIGINAL
        # ref that first claimed it, so two DISTINCT external relations that
        # sanitize to the same id (e.g. ``a.b__c`` and ``a.b.c`` -> ``a__b__c``)
        # fail closed instead of being silently conflated into one source node.
        external_source_refs: dict[str, str] = {}
        for umf in umfs:
            if umf.table_name not in self._gold_tables:
                continue
            t = umf.table_name
            gold_id = f"gold_{t}"
            deps: set[str] = set()
            for ref in sorted(ref_map[t]):
                # Always attempt to bind the ref -- bare OR qualified -- to a known
                # local table. A qualified name can legitimately resolve when a
                # UMF's table_name / canonical_name / alias is itself qualified
                # (e.g. ``mart.member``); such a name must bind to that table's
                # ingested_/gold_ node, NOT become a phantom external source.
                ref_umf = self._lookup_umf(ref)
                if ref_umf is None:
                    # Genuinely absent from the UMF set. It is external ONLY when
                    # explicitly marked so: a qualified-and-unknown cross-pipeline
                    # reference, or a relation a cross_pipeline FK points at.
                    is_qualified = _namespace(ref) is not None
                    is_external = (
                        is_qualified or _bare(ref).lower() in external_by_table[t]
                    )
                    if is_external:
                        # Explicitly external (qualified cross-pipeline ref or a
                        # cross_pipeline FK): a source('external', ...) leaf, not a
                        # local model. Register it so the renderer routes it.
                        ext_id = self._external_source_id(ref)
                        # FAIL CLOSED on a sanitized-id collision: two DIFFERENT
                        # external refs must not share one dbt source id (which
                        # ``LogicalPlan.add`` would silently merge, conflating two
                        # distinct cross-pipeline relations into one source).
                        prior = external_source_refs.get(ext_id)
                        if prior is not None and _norm(prior) != _norm(ref):
                            msg = (
                                f"External relation references {prior!r} and "
                                f"{ref!r} both sanitize to the same dbt source id "
                                f"{ext_id!r}; external source identifiers must be "
                                f"unique. Rename one reference so the sanitized "
                                f"ids differ."
                            )
                            raise NodeRegistryError(msg)
                        # FAIL CLOSED when the sanitized external id collides with a
                        # LOCAL plan node id (a ``raw_<t>`` / ``ingested_<t>`` /
                        # ``gold_<t>``). e.g. local table ``base`` owns ``raw_base``
                        # while a bare cross-pipeline external ref ``raw_base`` also
                        # sanitizes to ``raw_base``. ``LogicalPlan.add`` would merge
                        # the external node INTO the local one (OR-ing external=True),
                        # silently turning the local landing source external. ``prior
                        # is None`` here means this id was not previously claimed as an
                        # external source, so an existing same-id node must be local.
                        if prior is None and ext_id in self.plan.nodes:
                            existing = self.plan.nodes[ext_id]
                            msg = (
                                f"External relation reference {ref!r} sanitizes to "
                                f"dbt source id {ext_id!r}, which already names a "
                                f"local {existing.role.value} node. External source "
                                f"identifiers must not collide with local model / "
                                f"source ids; rename the external reference."
                            )
                            raise NodeRegistryError(msg)
                        external_source_refs[ext_id] = ref
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
                    target_id = f"ingested_{ref_umf.table_name}"
                    target_role = NodeRole.INGESTED
                else:
                    target_id = f"gold_{ref_umf.table_name}"
                    target_role = NodeRole.GOLD
                deps.add(target_id)
                # Ensure the EXACT literal the generator emits resolves to the
                # bound node. The referenced table's own physical aliases are
                # already indexed (Pass 2 for ingested; below for gold), but a
                # qualified ref literal (e.g. ``mart.member``) that bound via a
                # qualified canonical_name/alias must ALSO resolve under its own
                # spelling so the renderer never falls through to fail-closed.
                self._by_name.setdefault(
                    _norm(ref), ResolvedNode(target_id, target_role, external=False)
                )
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


__all__ = ["NodeRegistry", "NodeRegistryError", "ResolvedNode"]
