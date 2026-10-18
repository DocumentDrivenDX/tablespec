"""Tests for tablespec.lineage.builder.LineageBuilder (in-memory UMFs)."""

# @covers US-046-AC5

from __future__ import annotations

from typing import Any

import pytest

from tablespec.lineage import LineageBuilder, split_table_id, table_id
from tablespec.models.umf import UMF

pytestmark = pytest.mark.no_spark


class InMemoryProvider:
    """``UMFProvider`` over a dict of table id -> UMF."""

    def __init__(self, umfs: dict[str, UMF]) -> None:
        self.umfs = umfs

    def get_umf(self, group: str, table: str) -> UMF | None:
        return self.umfs.get(table_id(group, table))

    def list_tables(self, group: str) -> list[str]:
        return sorted(t for g, t in map(split_table_id, self.umfs) if g == group)


def col(name: str, *, source: str | None = None, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"name": name, "data_type": "VARCHAR", **extra}
    if source:
        data["source"] = source
    return data


def cand(table: str, priority: int = 1, **extra: Any) -> dict[str, Any]:
    return {"table": table, "priority": priority, **extra}


def derived(name: str, *cands: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return col(name, derivation={"candidates": list(cands)}, **extra)


def umf(
    name: str, columns: list[dict[str, Any]], table_type: str = "ingested", **extra: Any
) -> UMF:
    return UMF.model_validate(
        {
            "version": "1.0",
            "table_name": name,
            "table_type": table_type,
            "columns": columns,
            **extra,
        }
    )


def leaf_ids(graph, target: str) -> list[str]:
    return [leaf.column_id for leaf in graph.leaf_summaries[target]]


def test_ids_for_grouped_and_flat_tables():
    assert table_id("crm", "customers") == "crm.customers"
    assert table_id("", "customers") == "customers"
    assert split_table_id("crm.customers") == ("crm", "customers")
    assert split_table_id("customers") == ("", "customers")


def test_chain_through_generated_tables_across_groups():
    provider = InMemoryProvider(
        {
            "ent.raw_mail": umf(
                "raw_mail",
                [col("drop_date")],
                file_format={
                    "source_directory": "mail",
                    "filename_pattern": {
                        "regex": r"^Mail_(\d{8})\.txt$",
                        "captures": {1: "d"},
                    },
                },
            ),
            "ent.mail_gold": umf(
                "mail_gold",
                [derived("drop_date", cand("raw_mail", column="drop_date"))],
                "generated",
            ),
            "rpt.report": umf(
                "report",
                [derived("mail_date", cand("ent.mail_gold", column="drop_date"))],
                "generated",
            ),
        }
    )
    graph = LineageBuilder(provider).trace_column("rpt", "report", "mail_date")

    [leaf] = graph.leaf_summaries["rpt.report.mail_date"]
    assert leaf.column_id == "ent.raw_mail.drop_date"
    assert leaf.source_system == "mail"
    assert leaf.filename_regex == r"^Mail_(\d{8})\.txt$"
    assert leaf.leaf_kind == "source_column"
    assert leaf.hops == 2
    assert set(graph.tables) == {"rpt.report", "ent.mail_gold", "ent.raw_mail"}
    assert graph.warnings == []


def test_flat_root_tables_resolve_bare_names():
    provider = InMemoryProvider(
        {
            "patients": umf("patients", [col("Id")]),
            "summary": umf(
                "summary",
                [derived("patient_id", cand("patients", column="Id"))],
                "generated",
            ),
        }
    )
    graph = LineageBuilder(provider).trace_table("", "summary")
    assert leaf_ids(graph, "summary.patient_id") == ["patients.Id"]
    assert graph.tables["patients"].location.source_system == "patients"


def test_non_delimited_sources_resolve_their_location():
    provider = InMemoryProvider(
        {
            "events": umf(
                "events",
                [col("id")],
                source={"kind": "parquet", "path": "s3://lake/events"},
            ),
            "orders": umf(
                "orders",
                [col("id")],
                source={
                    "kind": "jdbc",
                    "url": "jdbc:postgresql://db/shop",
                    "dbtable": "orders",
                },
            ),
        }
    )
    builder = LineageBuilder(provider)
    events = builder.trace_column("", "events", "id").tables["events"]
    assert events.location.source_system == "s3://lake/events"
    assert events.file.kind == "parquet"
    orders = builder.trace_column("", "orders", "id").tables["orders"]
    assert orders.location.source_system == "jdbc:postgresql://db/shop"
    assert orders.location.path == "jdbc:postgresql://db/shop orders"


def test_table_instances_collapse_to_one_leaf():
    expr = "CASE WHEN base.kind = 'PED' THEN base.excl_ped__disp_id ELSE base.excl_adult__disp_id END"
    provider = InMemoryProvider(
        {
            "base_tbl": umf("base_tbl", [col("kind")]),
            "excl": umf("excl", [col("disp_id")]),
            "report": umf(
                "report",
                [
                    derived(
                        "disp_id",
                        cand(
                            "excl",
                            table_instance="excl_ped",
                            expression=expr,
                            join_filter="c=39",
                        ),
                        cand("excl", 2, table_instance="excl_adult", column="disp_id"),
                    )
                ],
                "generated",
                metadata={"base_table": "base_tbl"},
            ),
        }
    )
    graph = LineageBuilder(provider).trace_column("", "report", "disp_id")
    assert leaf_ids(graph, "report.disp_id") == ["base_tbl.kind", "excl.disp_id"]
    edge = next(e for e in graph.edges if e.source == "excl.disp_id")
    assert (edge.join_filter, edge.priority) == ("c=39", 1)


def test_intermediate_and_placeholder_refs():
    provider = InMemoryProvider(
        {
            "lab": umf("lab", [col("result"), col("result_date")]),
            "member": umf(
                "member",
                [
                    derived(
                        "a1c_date",
                        cand(
                            "lab",
                            column="result_date",
                            expression="MAX(result_date)",
                            select_columns=["result", "result_date"],
                        ),
                    ),
                    derived(
                        "has_a1c",
                        cand("intermediate", expression="{{col:a1c_date}} IS NOT NULL"),
                    ),
                    derived(
                        "a1c_value",
                        cand("intermediate", expression="{{col:a1c_date.result}}"),
                    ),
                ],
                "generated",
            ),
        }
    )
    builder = LineageBuilder(provider)
    has = builder.trace_column("", "member", "has_a1c")
    assert leaf_ids(has, "member.has_a1c") == ["lab.result_date"]
    assert any(e.kind == "sibling" for e in has.edges)
    value = builder.trace_column("", "member", "a1c_value")
    assert leaf_ids(value, "member.a1c_value") == ["lab.result"]


def test_union_sources_primary_key_fans_out():
    rel = {
        "type": "foreign_to_primary",
        "confidence": 1.0,
        "source_column": "member_id",
    }
    provider = InMemoryProvider(
        {
            "hedis": umf("hedis", [col("member_id")]),
            "iris": umf("iris", [col("mrn")]),
            "member": umf(
                "member",
                [col("member_id", derivation={"strategy": "primary_key"})],
                "generated",
                primary_key=["member_id"],
                metadata={
                    "base_table_strategy": "union_sources",
                    "source_tables": ["hedis", "iris"],
                },
                relationships={
                    "outgoing": [
                        {**rel, "target_table": "iris", "target_column": "mrn"}
                    ]
                },
            ),
        }
    )
    graph = LineageBuilder(provider).trace_column("", "member", "member_id")
    assert leaf_ids(graph, "member.member_id") == ["hedis.member_id", "iris.mrn"]
    assert {e.kind for e in graph.edges} == {"primary_key"}


def test_union_branches_follow_each_branch_candidate_and_skip_literals():
    provider = InMemoryProvider(
        {
            "a": umf("a", [col("name")]),
            "b": umf("b", [col("full_name")]),
            "unified": umf(
                "unified",
                [
                    derived(
                        "name",
                        cand("a", column="name"),
                        cand("b", 2, column="full_name"),
                    ),
                    derived(
                        "origin",
                        cand("a", column="origin", union_value="A"),
                        cand("b", 2, column="origin", union_value="B"),
                    ),
                ],
                "generated",
                metadata={
                    "base_table": "a",
                    "base_table_strategy": "union_branches",
                    "union_base_tables": ["b"],
                },
            ),
        }
    )
    graph = LineageBuilder(provider).trace_table("", "unified")
    assert leaf_ids(graph, "unified.name") == ["a.name", "b.full_name"]
    origin = graph.columns["unified.origin"]
    assert (origin.leaf_kind, origin.constant) == ("constant", "A | B")


def test_base_column_reads_the_base_table():
    provider = InMemoryProvider(
        {
            "outreach": umf("outreach", [col("name")]),
            "unified": umf(
                "unified",
                [col("name", derivation={"strategy": "base_column"})],
                "generated",
                metadata={"base_table": "outreach"},
            ),
        }
    )
    graph = LineageBuilder(provider).trace_column("", "unified", "name")
    assert leaf_ids(graph, "unified.name") == ["outreach.name"]
    assert {e.kind for e in graph.edges} == {"base_column"}


def test_unpivot_value_column_fans_out_and_discriminator_is_constant():
    provider = InMemoryProvider(
        {
            "charges": umf("charges", [col("diag1"), col("diag2")]),
            "coding": umf(
                "coding",
                [
                    derived(
                        "diagnosis_code",
                        cand(
                            "charges",
                            column="diag1",
                            expression="REPLACE(diag_value, '.', '')",
                        ),
                    ),
                    derived("which", cand("charges", column="source_column")),
                ],
                "generated",
                metadata={
                    "base_table": "charges",
                    "base_table_strategy": "unpivot",
                    "unpivot_columns": ["diag1", "diag2"],
                    "unpivot_value_column": "diag_value",
                },
            ),
        }
    )
    builder = LineageBuilder(provider)
    code = builder.trace_column("", "coding", "diagnosis_code")
    assert leaf_ids(code, "coding.diagnosis_code") == ["charges.diag1", "charges.diag2"]
    assert {e.kind for e in code.edges} == {"unpivot"}
    which = builder.trace_column("", "coding", "which")
    assert which.columns["coding.which"].leaf_kind == "constant"
    assert which.warnings == []


def test_generated_leaf_kinds():
    provider = InMemoryProvider(
        {
            "report": umf(
                "report",
                [
                    col("flag", default="N"),
                    col("empty"),
                    col("meta_load_dt", source="metadata"),
                    derived(
                        "na", cand("intermediate", expression="CAST(NULL AS DATE)")
                    ),
                ],
                "generated",
            )
        }
    )
    cols = LineageBuilder(provider).trace_table("", "report").columns
    assert (cols["report.flag"].leaf_kind, cols["report.flag"].constant) == (
        "constant",
        "N",
    )
    assert cols["report.empty"].constant == "NULL"
    assert cols["report.meta_load_dt"].leaf_kind == "runtime_metadata"
    assert cols["report.na"].constant == "CAST(NULL AS DATE)"


def test_source_leaf_kinds_and_self_derivation():
    provider = InMemoryProvider(
        {
            "lab": umf(
                "lab",
                [
                    col("test_name"),
                    col("vendor", source="filename"),
                    col("meta_source_name", source="metadata"),
                    derived(
                        "loinc",
                        cand(
                            "lab",
                            expression="CASE WHEN test_name = 'A1C' THEN '4548-4' END",
                        ),
                        source="derived",
                    ),
                    derived("state", cand("lab", column="state"), source="data"),
                ],
                file_format={
                    "filename_pattern": {
                        "regex": r"^(\w+)_Lab\.csv$",
                        "captures": {1: "vendor"},
                    }
                },
            )
        }
    )
    graph = LineageBuilder(provider).trace_table("", "lab")
    cols = graph.columns
    assert leaf_ids(graph, "lab.loinc") == ["lab.test_name"]
    assert (cols["lab.vendor"].leaf_kind, cols["lab.vendor"].capture_group) == (
        "filename_capture",
        1,
    )
    assert cols["lab.meta_source_name"].leaf_kind == "source_metadata"
    # A self-referencing candidate is not an edge; the column is read from the source.
    assert cols["lab.state"].leaf_kind == "source_column"


def test_cycle_terminates_with_warning():
    provider = InMemoryProvider(
        {
            "a": umf("a", [derived("x", cand("b", column="x"))], "generated"),
            "b": umf("b", [derived("x", cand("a", column="x"))], "generated"),
        }
    )
    graph = LineageBuilder(provider).trace_column("", "a", "x")
    assert any("Cycle detected" in w for w in graph.warnings)


def test_missing_table_is_unresolved():
    provider = InMemoryProvider(
        {"report": umf("report", [derived("x", cand("gone", column="x"))], "generated")}
    )
    graph = LineageBuilder(provider).trace_column("", "report", "x")
    [leaf] = graph.leaf_summaries["report.x"]
    assert (leaf.column_id, leaf.leaf_kind) == ("gone.x", "unresolved")
    assert graph.tables["gone"].table_type is None
    assert graph.warnings == ["Unresolved reference: gone.x"]


def test_leaf_summary_ordered_by_path_priority():
    provider = InMemoryProvider(
        {
            "primary": umf("primary", [col("name")]),
            "backup": umf("backup", [col("name")]),
            "report": umf(
                "report",
                [
                    derived(
                        "name",
                        cand("backup", 2, column="name"),
                        cand("primary", 1, column="name"),
                    )
                ],
                "generated",
            ),
        }
    )
    leaves = (
        LineageBuilder(provider)
        .trace_column("", "report", "name")
        .leaf_summaries["report.name"]
    )
    assert [(leaf.column_id, leaf.path_priority) for leaf in leaves] == [
        ("primary.name", [1]),
        ("backup.name", [2]),
    ]


def _summary(hub_score: float) -> dict[str, Any]:
    return {
        "total_relationships": 1,
        "total_incoming": 0,
        "total_outgoing": 1,
        "hub_score": hub_score,
    }


def test_base_table_inferred_from_hub_score():
    provider = InMemoryProvider(
        {
            "hub": umf(
                "hub", [col("me_attr4")], relationships={"summary": _summary(7.5)}
            ),
            "spoke": umf("spoke", [col("v")], relationships={"summary": _summary(1.0)}),
            "report": umf(
                "report",
                [
                    derived("a", cand("hub", column="me_attr4")),
                    derived(
                        "b", cand("spoke", expression="COALESCE(v, base.me_attr4)")
                    ),
                ],
                "generated",
            ),
        }
    )
    graph = LineageBuilder(provider).trace_column("", "report", "b")
    table = graph.tables["report"]
    assert (table.base_table, table.base_inferred) == ("hub", True)
    assert leaf_ids(graph, "report.b") == ["hub.me_attr4", "spoke.v"]


def test_base_table_falls_back_to_first_contributing_table():
    provider = InMemoryProvider(
        {
            "zeta": umf("zeta", [col("z")]),
            "alpha": umf("alpha", [col("a")]),
            "report": umf(
                "report",
                [
                    derived("z", cand("zeta", column="z")),
                    derived("a", cand("alpha", column="a")),
                ],
                "generated",
            ),
        }
    )
    assert (
        LineageBuilder(provider).trace_table("", "report").tables["report"].base_table
        == "alpha"
    )


def test_trace_table_excludes_internal_columns_and_rejects_missing_tables():
    provider = InMemoryProvider(
        {"t": umf("t", [col("a"), col("helper", internal=True)], "generated")}
    )
    builder = LineageBuilder(provider)
    assert builder.trace_table("", "t").targets == ["t.a"]
    assert builder.trace_table("", "t", include_internal=True).targets == [
        "t.a",
        "t.helper",
    ]
    with pytest.raises(ValueError, match="Table not found"):
        builder.trace_table("", "nope")
