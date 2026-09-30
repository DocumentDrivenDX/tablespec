"""Build a design-time column lineage graph from UMF derivations.

The traversal mirrors the final-assembly semantics of
:class:`tablespec.schemas.sql_generator.SQLGenerator`:

- ``derivation.strategy: primary_key`` / ``base_column`` read ``base.<col>``
  (the base table, or every ``source_tables`` entry for ``union_sources``).
- Candidates are read in priority order; an ``expression`` wins over ``column``.
  ``union_branches`` / ``aggregate_source`` tables project each column through
  its own candidates, so following candidates covers them; ``union_value``
  candidates are literals.
- A column without a derivation is a literal (default or NULL) in generated
  tables and a raw source value in every other table.

Join keys and filters are recorded on edges but not followed, so the graph
shows where values come from rather than every table that constrains a join.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

from tablespec.models.umf import DelimitedSource

from tablespec.lineage.expressions import ExprRef, extract_refs
from tablespec.lineage.models import (
    EdgeKind,
    LeafKind,
    LeafSource,
    LineageColumn,
    LineageEdge,
    LineageGraph,
    LineageTable,
    SourceFile,
)
from tablespec.lineage.providers import (
    LocationResolver,
    SourceLocationResolver,
    UMFProvider,
    effective_source_directory,
)
from tablespec.models.pipeline import TableReference

if TYPE_CHECKING:
    from tablespec.models.umf import UMF, DerivationCandidate, UMFColumn

INTERMEDIATE = "intermediate"
# Literal column the unpivot base view adds to name the unpivoted source column.
UNPIVOT_DISCRIMINATOR = "source_column"
_UNSET_PRIORITY = 999
# Aggregation / first-record views are named after their source alias
# (e.g. hedis_agg_4, claims_agg_grouped, members_first).
_VIEW_SUFFIX_RE = re.compile(r"(_agg(_\d+|_grouped)?|_first)$")


def table_id(group: str, table: str) -> str:
    """Return the graph id of a table (``group.table``, or ``table`` at the root)."""
    return f"{group}.{table}" if group else table


def split_table_id(tid: str) -> tuple[str, str]:
    """Inverse of :func:`table_id`."""
    group, _, table = tid.rpartition(".")
    return group, table


def column_id(tid: str, column: str) -> str:
    """Return the graph id of a column."""
    return f"{tid}.{column}"


def _unpivot_map(columns: list[str] | None, value: str | None) -> dict[str, list[str]]:
    """Map the unpivot value column to the source columns it is unpivoted from."""
    return {value: list(columns or [])} if value else {}


def _sanitize_alias(name: str) -> str:
    # Same as SQLGenerator._sanitize_alias.
    return name.replace(".", "_")


@dataclass
class _TableCtx:
    id: str
    group: str
    umf: UMF
    columns: dict[str, UMFColumn]
    base: str | None = None
    base_inferred: bool = False
    aliases: dict[str, str] = field(default_factory=dict)
    union_sources: list[tuple[str, str]] = field(
        default_factory=list
    )  # (table id, raw name)
    unpivot_map: dict[str, list[str]] = field(
        default_factory=dict
    )  # value col -> source cols


class LineageBuilder:
    """Trace columns upstream to their ultimate sources.

    One builder memoizes every table and column it visits, so tracing many
    tables with the same instance reuses work.
    """

    def __init__(
        self, provider: UMFProvider, location_resolver: LocationResolver | None = None
    ) -> None:
        self.provider = provider
        self.location_resolver = location_resolver or SourceLocationResolver()
        self._ctx: dict[str, _TableCtx | None] = {}
        self._tables: dict[str, LineageTable] = {}
        self._columns: dict[str, LineageColumn] = {}
        self._upstream: dict[str, list[LineageEdge]] = {}
        self._warnings: dict[str, list[str]] = {}
        self._visiting: set[str] = set()

    # ------------------------------------------------------------------ public

    def trace_column(self, group: str, table: str, column: str) -> LineageGraph:
        """Trace a single column."""
        return self._trace(table_id(group, table), [column])

    def trace_table(
        self, group: str, table: str, *, include_internal: bool = False
    ) -> LineageGraph:
        """Trace every (non-internal by default) column of a table."""
        tid = table_id(group, table)
        ctx = self._table_ctx(tid)
        if ctx is None:
            msg = f"Table not found: {tid}"
            raise ValueError(msg)
        names = [c.name for c in ctx.umf.columns if include_internal or not c.internal]
        return self._trace(tid, names)

    # --------------------------------------------------------------- traversal

    def _trace(self, tid: str, column_names: list[str]) -> LineageGraph:
        targets = [column_id(tid, name) for name in column_names]
        for target in targets:
            self._visit(target)

        closure: set[str] = set()
        stack = list(targets)
        while stack:
            cid = stack.pop()
            if cid in closure:
                continue
            closure.add(cid)
            stack.extend(e.source for e in self._upstream.get(cid, []))

        columns = {cid: self._columns[cid] for cid in sorted(closure)}
        table_ids = sorted({c.table_id for c in columns.values()})
        return LineageGraph(
            targets=targets,
            tables={t: self._tables[t] for t in table_ids},
            columns=columns,
            edges=[e for cid in sorted(closure) for e in self._upstream.get(cid, [])],
            leaf_summaries={t: self._leaf_summary(t) for t in targets},
            warnings=[
                w for cid in sorted(closure) for w in self._warnings.get(cid, [])
            ],
        )

    def _visit(self, cid: str) -> None:
        if cid in self._upstream or cid in self._visiting:
            return
        tid, name = cid.rsplit(".", 1)
        ctx = self._table_ctx(tid)
        col = ctx.columns.get(name) if ctx else None
        self._columns[cid] = LineageColumn(
            id=cid,
            table_id=tid,
            name=name,
            data_type=col.data_type if col else None,
            source=col.source if col else None,
            description=col.description if col else None,
            internal=col.internal if col else False,
        )
        if ctx is None or col is None:
            self._warn(cid, f"Unresolved reference: {cid}")
            self._columns[cid].leaf_kind = "unresolved"
            self._upstream[cid] = []
            return

        self._visiting.add(cid)
        edges: list[LineageEdge] = []
        for edge in self._upstream_edges(ctx, col):
            if edge.source == cid:
                continue
            if edge.source in self._visiting:
                self._warn(cid, f"Cycle detected: {edge.source} -> {cid}")
                continue
            self._visit(edge.source)
            edges.append(edge)
        self._visiting.discard(cid)

        self._upstream[cid] = edges
        if not edges:
            self._set_leaf(ctx, col, self._columns[cid])

    def _upstream_edges(self, ctx: _TableCtx, col: UMFColumn) -> list[LineageEdge]:
        edges = self._expand_unpivot(ctx, self._derivation_edges(ctx, col))
        # One edge per (source, kind), keeping the best priority.
        unique: dict[tuple[str, str], LineageEdge] = {}
        for edge in edges:
            unique.setdefault((edge.source, edge.kind), edge)
        return list(unique.values())

    def _expand_unpivot(
        self, ctx: _TableCtx, edges: list[LineageEdge]
    ) -> list[LineageEdge]:
        """Replace base-view unpivot outputs with the base table's unpivoted columns.

        The unpivot base view exposes ``unpivot_value_column`` (fanned out from
        ``unpivot_columns``) and a ``source_column`` discriminator literal.
        """
        if not ctx.unpivot_map or not ctx.base:
            return edges
        expanded: list[LineageEdge] = []
        for edge in edges:
            tid, name = edge.source.rsplit(".", 1)
            if tid != ctx.base or self._has_column(tid, name):
                expanded.append(edge)
            elif name in ctx.unpivot_map:
                expanded.extend(
                    edge.model_copy(
                        update={"source": column_id(tid, c), "kind": "unpivot"}
                    )
                    for c in ctx.unpivot_map[name]
                )
            elif name != UNPIVOT_DISCRIMINATOR:
                expanded.append(edge)
        return expanded

    def _derivation_edges(self, ctx: _TableCtx, col: UMFColumn) -> list[LineageEdge]:
        target = column_id(ctx.id, col.name)
        derivation = col.derivation
        strategy = derivation.strategy if derivation else None

        if strategy == "primary_key":
            if ctx.union_sources:
                return [
                    LineageEdge(
                        source=column_id(
                            sid, self._union_join_column(ctx, raw, col.name)
                        ),
                        target=target,
                        kind="primary_key",
                    )
                    for sid, raw in ctx.union_sources
                ]
            return self._base_edges(ctx, col.name, target, "primary_key")
        if strategy == "base_column":
            return self._base_edges(ctx, col.name, target, "base_column")

        candidates = (
            derivation.candidates if derivation and derivation.candidates else []
        )
        edges: list[LineageEdge] = []
        for cand in sorted(candidates, key=lambda c: c.priority):
            if cand.union_value is not None:
                continue
            edges.extend(self._candidate_edges(ctx, col, cand, target))
        return edges

    def _candidate_edges(
        self, ctx: _TableCtx, col: UMFColumn, cand: DerivationCandidate, target: str
    ) -> list[LineageEdge]:
        cand_tid = (
            None if cand.table == INTERMEDIATE else self._qualify(ctx.group, cand.table)
        )

        def edge(source: str, kind: EdgeKind) -> LineageEdge:
            return LineageEdge(
                source=source,
                target=target,
                kind=kind,
                priority=cand.priority,
                table_instance=cand.table_instance,
                join_filter=cand.join_filter,
                row_filter=cand.row_filter,
                via=cand.join_via.lookup_table if cand.join_via else None,
                expression=cand.expression,
            )

        if not cand.expression:
            if cand.column and cand_tid:
                return [edge(column_id(cand_tid, cand.column), "column")]
            return []

        return [
            edge(source, kind)
            for ref in extract_refs(cand.expression)
            for source, kind in self._resolve_ref(ctx, col, cand_tid, ref, target)
        ]

    def _resolve_ref(
        self,
        ctx: _TableCtx,
        col: UMFColumn,
        cand_tid: str | None,
        ref: ExprRef,
        target: str,
    ) -> list[tuple[str, EdgeKind]]:
        name = ref.column
        if ref.kind in ("bare", "base") and name in ctx.unpivot_map and ctx.base:
            return [
                (column_id(ctx.base, name), "expression")
            ]  # expanded by _expand_unpivot

        if ref.kind == "placeholder":
            anchor = ctx.columns.get(name)
            if anchor is None:
                self._warn(target, f"Unknown {{{{col:{name}}}}} in {target}")
                return []
            if ref.field is None:
                return [(column_id(ctx.id, name), "sibling")]
            return self._placeholder_field(ctx, anchor, ref.field, target)

        if ref.kind == "prefixed":
            alias_tid = self._resolve_alias(ctx, ref.alias or "")
            if alias_tid and self._has_column(alias_tid, name):
                return [(column_id(alias_tid, name), "expression")]
            if name in ctx.columns:
                return [(column_id(ctx.id, name), "sibling")]
            self._warn(target, f"Unresolved base.{ref.alias}__{name} in {target}")
            return []

        if ref.kind == "base":
            if ctx.base and self._has_column(ctx.base, name):
                return [(column_id(ctx.base, name), "expression")]
            if name in ctx.columns and name != col.name:
                return [(column_id(ctx.id, name), "sibling")]
            self._warn(target, f"Unresolved base.{name} in {target}")
            return []

        # Bare identifier: candidate table, then base table, then a sibling column.
        for tid in (cand_tid, ctx.base):
            if tid and self._has_column(tid, name):
                return [(column_id(tid, name), "expression")]
        if name in ctx.columns and name != col.name:
            return [(column_id(ctx.id, name), "sibling")]
        return []

    def _placeholder_field(
        self, ctx: _TableCtx, anchor: UMFColumn, field_name: str, target: str
    ) -> list[tuple[str, EdgeKind]]:
        anchor_cands = anchor.derivation.candidates if anchor.derivation else None
        results: list[tuple[str, EdgeKind]] = []
        for cand in anchor_cands or []:
            if cand.select_columns and field_name not in cand.select_columns:
                continue
            tid = self._qualify(ctx.group, cand.table)
            if self._has_column(tid, field_name):
                results.append((column_id(tid, field_name), "expression"))
        if not results:
            self._warn(
                target, f"Unresolved {{{{col:{anchor.name}.{field_name}}}}} in {target}"
            )
        return results

    def _base_edges(
        self, ctx: _TableCtx, name: str, target: str, kind: EdgeKind
    ) -> list[LineageEdge]:
        if not ctx.base:
            return []
        return [LineageEdge(source=column_id(ctx.base, name), target=target, kind=kind)]

    def _union_join_column(self, ctx: _TableCtx, raw_source: str, pk: str) -> str:
        """Join column a ``union_sources`` entry contributes (``_find_source_join_column``)."""
        rels = ctx.umf.relationships
        for rel in rels.outgoing if rels and rels.outgoing else []:
            if rel.target_table == raw_source:
                return rel.target_column
        return pk

    def _set_leaf(self, ctx: _TableCtx, col: UMFColumn, node: LineageColumn) -> None:
        kind: LeafKind
        if ctx.umf.table_type == "generated":
            kind = "runtime_metadata" if col.source == "metadata" else "constant"
        elif col.source == "filename":
            kind = "filename_capture"
            source = ctx.umf.effective_source()
            pattern = (
                source.filename_pattern if isinstance(source, DelimitedSource) else None
            )
            captures = pattern.captures if pattern else {}
            node.capture_group = next(
                (g for g, n in captures.items() if n == col.name), None
            )
        elif col.source == "metadata":
            kind = "source_metadata"
        elif col.source == "derived":
            kind = "constant"
        else:
            kind = "source_column"
        node.leaf_kind = kind
        if kind == "constant":
            candidates = col.derivation.candidates if col.derivation else None
            expressions = [c.expression for c in candidates or [] if c.expression]
            values = [
                str(c.union_value)
                for c in candidates or []
                if c.union_value is not None
            ]
            if col.default is not None:
                node.constant = str(col.default)
            elif expressions or values:
                node.constant = " | ".join(expressions + values)
            else:
                node.constant = "NULL"

    # ----------------------------------------------------------- leaf summary

    def _leaf_summary(self, target: str) -> list[LeafSource]:
        best: dict[str, dict[str, tuple[tuple[int, ...], int]]] = {}

        def walk(
            cid: str, visiting: frozenset[str]
        ) -> dict[str, tuple[tuple[int, ...], int]]:
            if cid in best:
                return best[cid]
            edges = self._upstream.get(cid, [])
            if not edges:
                best[cid] = {cid: ((), 0)}
                return best[cid]
            result: dict[str, tuple[tuple[int, ...], int]] = {}
            for e in edges:
                if e.source in visiting:
                    continue
                prio = e.priority if e.priority is not None else _UNSET_PRIORITY
                for leaf, (path, hops) in walk(e.source, visiting | {cid}).items():
                    candidate = ((prio, *path), hops + 1)
                    if leaf not in result or candidate < result[leaf]:
                        result[leaf] = candidate
            best[cid] = result
            return result

        rows: list[LeafSource] = []
        for leaf_id, (path, hops) in walk(target, frozenset()).items():
            node = self._columns[leaf_id]
            table = self._tables[node.table_id]
            rows.append(
                LeafSource(
                    column_id=leaf_id,
                    table_id=node.table_id,
                    column=node.name,
                    leaf_kind=node.leaf_kind or "unresolved",
                    source_system=table.location.source_system
                    if table.location
                    else None,
                    location=table.location.path if table.location else None,
                    filename_regex=table.file.filename_regex if table.file else None,
                    capture_group=node.capture_group,
                    path_priority=list(path),
                    hops=hops,
                )
            )
        rows.sort(key=lambda r: (r.path_priority, r.hops, r.column_id))
        return rows

    # ------------------------------------------------------------ table ctx

    def _qualify(self, group: str, ref: str) -> str:
        """Resolve ``group.table`` or a bare name within ``group`` (ADR-018)."""
        parsed = TableReference.parse(ref)
        return table_id(parsed.pipeline or group, parsed.table)

    def _has_column(self, tid: str, name: str) -> bool:
        ctx = self._table_ctx(tid)
        return ctx is not None and name in ctx.columns

    def _resolve_alias(self, ctx: _TableCtx, alias: str) -> str | None:
        if alias in ctx.aliases:
            return ctx.aliases[alias]
        stripped = _VIEW_SUFFIX_RE.sub("", alias)
        return ctx.aliases.get(stripped)

    def _warn(self, cid: str, message: str) -> None:
        messages = self._warnings.setdefault(cid, [])
        if message not in messages:
            messages.append(message)

    def _table_ctx(self, tid: str) -> _TableCtx | None:
        if tid in self._ctx:
            return self._ctx[tid]
        group, table = split_table_id(tid)
        umf = self.provider.get_umf(group, table)
        if umf is None:
            self._ctx[tid] = None
            self._tables[tid] = LineageTable(id=tid, group=group, table=table)
            return None

        ctx = _TableCtx(
            id=tid, group=group, umf=umf, columns={c.name: c for c in umf.columns}
        )
        # Register before resolving the base so self-references terminate.
        self._ctx[tid] = ctx
        self._populate_ctx(ctx)

        self._tables[tid] = LineageTable(
            id=tid,
            group=group,
            table=table,
            table_type=umf.table_type,
            description=umf.description,
            base_table=ctx.base,
            base_inferred=ctx.base_inferred,
            file=_source_file(umf),
            location=self.location_resolver.resolve(group, umf),
        )
        return ctx

    def _populate_ctx(self, ctx: _TableCtx) -> None:
        umf, group = ctx.umf, ctx.group
        meta = umf.metadata

        for col in umf.columns:
            for cand in (col.derivation.candidates if col.derivation else None) or []:
                if cand.table == INTERMEDIATE:
                    continue
                qualified = self._qualify(group, cand.table)
                ctx.aliases.setdefault(_sanitize_alias(cand.table), qualified)
                if cand.table_instance:
                    ctx.aliases.setdefault(
                        _sanitize_alias(cand.table_instance), qualified
                    )
        rels = umf.relationships
        for fk in rels.foreign_keys if rels and rels.foreign_keys else []:
            ref = (
                f"{fk.references_pipeline}.{fk.references_table}"
                if fk.references_pipeline
                else fk.references_table
            )
            ctx.aliases.setdefault(_sanitize_alias(ref), self._qualify(group, ref))

        if umf.table_type != "generated":
            return

        if meta and meta.base_table_strategy == "union_sources":
            ctx.union_sources = [
                (self._qualify(group, s), s) for s in meta.source_tables or []
            ]
        elif meta and meta.base_table:
            ctx.base = self._qualify(group, meta.base_table)
        else:
            ctx.base = self._infer_base(ctx)
            ctx.base_inferred = ctx.base is not None

        if meta and meta.base_table_strategy == "unpivot":
            ctx.unpivot_map = _unpivot_map(
                meta.unpivot_columns, meta.unpivot_value_column
            )
        if ctx.base:
            ctx.aliases.setdefault(split_table_id(ctx.base)[1], ctx.base)

    def _infer_base(self, ctx: _TableCtx) -> str | None:
        """Pick the base table like ``RelationshipResolver._infer_base_table``.

        Highest ``hub_score`` wins, then the most outgoing relationships, then
        the first contributing table.
        """
        contributing = {
            cand.table
            for col in ctx.umf.columns
            for cand in ((col.derivation.candidates if col.derivation else None) or [])
            if cand.table and cand.table != INTERMEDIATE
        }
        candidates = {t for t in contributing if "." not in t}
        for name in self.provider.list_tables(ctx.group):
            other = self.provider.get_umf(ctx.group, name)
            rels = other.relationships if other else None
            if (
                rels
                and rels.outgoing
                and any(r.target_table in contributing for r in rels.outgoing)
            ):
                candidates.add(name)

        scores: dict[str, float] = {}
        outgoing: dict[str, int] = {}
        for name in sorted(candidates):
            other = self.provider.get_umf(ctx.group, name)
            rels = other.relationships if other else None
            if rels and rels.summary and rels.summary.hub_score:
                scores[name] = rels.summary.hub_score
            if rels and rels.outgoing:
                outgoing[name] = len(rels.outgoing)
        for ranked in (scores, outgoing):
            if ranked:
                best = max(ranked.items(), key=lambda x: (x[1], x[0]))[0]
                return table_id(ctx.group, best)
        if contributing:
            return self._qualify(ctx.group, sorted(contributing)[0])
        return None


def _source_file(umf: UMF) -> SourceFile | None:
    """Source facts of a non-generated table, from ``umf.effective_source()``."""
    if umf.table_type == "generated":
        return None
    source = umf.effective_source()
    if not isinstance(source, DelimitedSource):
        return SourceFile(kind=source.kind)
    pattern = source.filename_pattern
    return SourceFile(
        filename_regex=pattern.regex if pattern else None,
        captures=pattern.captures if pattern else {},
        delimiter=source.delimiter,
        encoding=source.encoding,
        header=source.header,
        quote_char=source.quote_char,
        source_directory=effective_source_directory(umf),
    )
