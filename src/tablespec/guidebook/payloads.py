"""Build page payloads (JSON-serializable models) from UMFs and lineage graphs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tablespec.guidebook.models import (
    CandidateDoc,
    ColumnDoc,
    ForeignKeyDoc,
    RuleDoc,
    SurvivorshipDoc,
    TableDoc,
    TableSummary,
    UsedByRef,
)
from tablespec.guidebook.prose import format_prose
from tablespec.guidebook.sql_format import format_sql
from tablespec.lineage.builder import column_id, split_table_id, table_id
from tablespec.models.pipeline import TableReference

if TYPE_CHECKING:
    from tablespec.lineage.models import LineageGraph
    from tablespec.models.umf import UMF, UMFColumn

_SAMPLE_LIMIT = 5
_CATALOG_DESC_LIMIT = 120

UsedByIndex = dict[str, list[UsedByRef]]
Via = Literal["derivation", "fk"]


def qualify(group: str, ref: str) -> str:
    """Resolve ``group.table`` or a bare table name within ``group`` (ADR-018)."""
    parsed = TableReference.parse(ref)
    return table_id(parsed.pipeline or group, parsed.table)


def _fk_target(group: str, fk: Any) -> str:
    ref = (
        f"{fk.references_pipeline}.{fk.references_table}"
        if fk.references_pipeline
        else fk.references_table
    )
    return qualify(group, ref)


def build_used_by(graphs: list[LineageGraph], umfs: dict[str, UMF]) -> UsedByIndex:
    """Invert lineage edges (derivation) and foreign keys (fk) into per-column consumers.

    ``umfs`` maps table ids to UMFs. A column referenced both ways is listed
    once, as a derivation.
    """
    refs: dict[str, dict[str, Via]] = {}
    for graph in graphs:
        for edge in graph.edges:
            refs.setdefault(edge.source, {})[edge.target] = "derivation"
    for tid, umf in umfs.items():
        group, _ = split_table_id(tid)
        rels = umf.relationships
        for fk in rels.foreign_keys if rels and rels.foreign_keys else []:
            target = column_id(_fk_target(group, fk), fk.references_column)
            refs.setdefault(target, {}).setdefault(column_id(tid, fk.column), "fk")
    return {
        cid: [
            UsedByRef(column_id=ref, via=via) for ref, via in sorted(consumers.items())
        ]
        for cid, consumers in refs.items()
    }


def _expectation_dicts(umf: UMF) -> list[dict[str, Any]]:
    """All expectations as GX-style dicts (``UMF.expectations``, then legacy rules)."""
    found: list[dict[str, Any]] = []
    if umf.expectations:
        found.extend(e.to_gx_dict() for e in umf.expectations.expectations)
    if umf.validation_rules and umf.validation_rules.expectations:
        found.extend(umf.validation_rules.expectations)
    return found


def _rule_docs(umf: UMF) -> tuple[dict[str, list[RuleDoc]], list[RuleDoc]]:
    """Split expectations into per-column rules and table-level rules."""
    per_column: dict[str, list[RuleDoc]] = {}
    table_rules: list[RuleDoc] = []
    for rule in _expectation_dicts(umf):
        kwargs = dict(rule.get("kwargs") or {})
        meta = rule.get("meta") or {}
        column = kwargs.pop("column", None)
        doc = RuleDoc(
            type=str(rule.get("type", "")),
            severity=str(meta.get("severity", "warning")),
            description=meta.get("description"),
            kwargs=kwargs or None,
        )
        if column:
            per_column.setdefault(str(column), []).append(doc)
        else:
            table_rules.append(doc)
    return per_column, table_rules


def _sample_values(col: UMFColumn, rules: list[RuleDoc]) -> list[str]:
    if col.sample_values:
        return [str(v) for v in col.sample_values[:_SAMPLE_LIMIT]]
    for rule in rules:
        if rule.type == "expect_column_values_to_be_in_set" and rule.kwargs:
            return [
                str(v) for v in (rule.kwargs.get("value_set") or [])[:_SAMPLE_LIMIT]
            ]
    return []


def _column_doc(
    group: str, col: UMFColumn, rules: list[RuleDoc], used_by: list[UsedByRef]
) -> ColumnDoc:
    derivation = col.derivation
    candidates = [
        CandidateDoc(
            priority=cand.priority,
            table=cand.table,
            table_id=None
            if cand.table == "intermediate"
            else qualify(group, cand.table),
            column=cand.column,
            expression=format_sql(cand.expression) if cand.expression else None,
            table_instance=cand.table_instance,
            join_filter=format_sql(cand.join_filter) if cand.join_filter else None,
            row_filter=format_sql(cand.row_filter) if cand.row_filter else None,
            via=cand.join_via.lookup_table if cand.join_via else None,
            reason_html=format_prose(cand.reason) if cand.reason else None,
        )
        for cand in sorted(
            (derivation.candidates if derivation else None) or [],
            key=lambda c: c.priority,
        )
    ]
    surv = derivation.survivorship if derivation else None
    nullable = col.nullable
    return ColumnDoc(
        name=col.name,
        data_type=col.data_type,
        description=col.description,
        canonical_name=col.canonical_name,
        format=col.format,
        length=col.length,
        nullable=(
            {k: v for k, v in nullable.model_dump().items() if v is not None}
            if nullable is not None and not isinstance(nullable, bool)
            else nullable
        ),
        key_type=col.key_type,
        source=col.source,
        internal=col.internal,
        default=None if col.default is None else str(col.default),
        provenance_policy=col.provenance_policy,
        provenance_notes=col.provenance_notes,
        derivation_strategy=derivation.strategy if derivation else None,
        derivation_explanation_html=(
            format_prose(derivation.explanation)
            if derivation and derivation.explanation
            else None
        ),
        candidates=candidates,
        survivorship=(
            SurvivorshipDoc(
                strategy=surv.strategy,
                explanation_html=format_prose(surv.explanation)
                if surv.explanation
                else None,
                default_value=None
                if surv.default_value is None
                else str(surv.default_value),
                default_condition=surv.default_condition,
            )
            if surv
            else None
        ),
        validations=rules,
        sample_values=_sample_values(col, rules),
        used_by=used_by,
    )


def build_table_doc(
    group: str, umf: UMF, graph: LineageGraph, used_by: UsedByIndex
) -> TableDoc:
    """Assemble the payload of one table page."""
    tid = table_id(group, umf.table_name)
    per_column_rules, table_rules = _rule_docs(umf)
    meta = umf.metadata
    lineage_table = graph.tables.get(tid)

    own_columns = {column_id(tid, c.name) for c in umf.columns}
    upstream = sorted(
        {
            e.source.rsplit(".", 1)[0]
            for e in graph.edges
            if e.target in own_columns and e.source.rsplit(".", 1)[0] != tid
        }
    )
    downstream = sorted(
        {
            ref.column_id.rsplit(".", 1)[0]
            for cid in own_columns
            for ref in used_by.get(cid, [])
            if ref.column_id.rsplit(".", 1)[0] != tid
        }
    )
    rels = umf.relationships
    return TableDoc(
        id=tid,
        group=group,
        table=umf.table_name,
        table_type=umf.table_type,
        description=umf.description,
        primary_key=list(umf.primary_key or []),
        source_file=umf.source_file,
        source_sheet_name=umf.source_sheet_name,
        base_table=lineage_table.base_table if lineage_table else None,
        base_table_strategy=meta.base_table_strategy if meta else None,
        final_filter=format_sql(meta.final_filter)
        if meta and meta.final_filter
        else None,
        source_tables=[
            qualify(group, s) for s in (meta.source_tables if meta else None) or []
        ],
        union_base_tables=[
            qualify(group, u) for u in (meta.union_base_tables if meta else None) or []
        ],
        file=lineage_table.file if lineage_table else None,
        location=lineage_table.location if lineage_table else None,
        foreign_keys=[
            ForeignKeyDoc(
                column=fk.column,
                references_table_id=_fk_target(group, fk),
                references_column=fk.references_column,
                join_filter=format_sql(fk.join_filter) if fk.join_filter else None,
            )
            for fk in (rels.foreign_keys if rels and rels.foreign_keys else [])
        ],
        upstream_tables=upstream,
        downstream_tables=downstream,
        table_rules=table_rules,
        columns=[
            _column_doc(
                group,
                col,
                per_column_rules.get(col.name, []),
                used_by.get(column_id(tid, col.name), []),
            )
            for col in umf.columns
        ],
        lineage=graph,
    )


def table_summary(umf: UMF) -> TableSummary:
    """Row for a group page."""
    return TableSummary(
        name=umf.table_name,
        table_type=umf.table_type,
        description=umf.description,
        column_count=len(umf.columns),
    )


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_catalog(title: str, umfs_by_group: dict[str, list[UMF]]) -> dict[str, Any]:
    """Compact index of every group, table, and column for navigation and search."""
    return {
        "title": title,
        "groups": [
            {
                "name": group,
                "tables": [
                    {
                        "name": umf.table_name,
                        "type": umf.table_type,
                        "desc": _truncate(umf.description, _CATALOG_DESC_LIMIT),
                        "cols": [
                            [
                                c.name,
                                c.data_type,
                                _truncate(c.description, _CATALOG_DESC_LIMIT),
                            ]
                            for c in umf.columns
                            if not c.internal
                        ],
                    }
                    for umf in umfs
                ],
            }
            for group, umfs in umfs_by_group.items()
        ],
    }
