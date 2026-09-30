"""Tests for guidebook table-page payloads — derivation-rule display."""

# @covers US-046-AC3

from __future__ import annotations

from tablespec.guidebook.payloads import build_table_doc
from tablespec.lineage import LineageGraph
from tablespec.models.umf import (
    UMF,
    DerivationCandidate,
    Expectation,
    ExpectationMeta,
    ExpectationSuite,
    Survivorship,
    UMFColumn,
    UMFColumnDerivation,
)


def _doc(umf: UMF):
    return build_table_doc("", umf, LineageGraph(), {})


def _report_umf() -> UMF:
    """A generated report with the three derivation-candidate shapes."""
    return UMF(
        version="1.0",
        table_name="member_report",
        canonical_name="member_report",
        table_type="generated",
        description="Computed report.",
        columns=[
            # Column-only candidates WITH join filters, no expression — their
            # priority + filter must still be shown.
            UMFColumn(
                name="pcp_name",
                data_type="VARCHAR",
                length=200,
                description="Primary care provider name.",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="providers",
                            column="NAME",
                            priority=2,
                            reason="Fallback provider.",
                            join_filter="encounter_rank = 1",
                        ),
                        DerivationCandidate(
                            table="providers",
                            column="NAME",
                            priority=1,
                            reason="Prefer the GP.",
                            join_filter="SPECIALITY = 'GENERAL PRACTICE'",
                        ),
                    ],
                    survivorship=Survivorship(
                        strategy="highest_priority",
                        explanation="Strategy: take the GP.",
                    ),
                ),
            ),
            # Expression candidate, no source column.
            UMFColumn(
                name="latest_bmi",
                data_type="DECIMAL",
                precision=5,
                scale=2,
                description="Latest BMI.",
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="observations",
                            priority=1,
                            expression="max(value) filter (where description = 'BMI')",
                            reason="Latest BMI.",
                        )
                    ],
                ),
            ),
            # Plain column, no derivation at all.
            UMFColumn(name="id", data_type="VARCHAR", length=36, description="PK"),
        ],
    )


def _col(doc, name: str):
    return next(c for c in doc.columns if c.name == name)


def test_candidates_ordered_by_priority_with_join_filters():
    pcp = _col(_doc(_report_umf()), "pcp_name")
    assert [c.priority for c in pcp.candidates] == [1, 2]
    assert pcp.candidates[0].join_filter == "SPECIALITY = 'GENERAL PRACTICE'"
    assert pcp.candidates[1].join_filter == "encounter_rank = 1"
    # Column-only candidates carry no expression.
    assert all(c.expression is None for c in pcp.candidates)
    assert pcp.candidates[0].table_id == "providers"


def test_sql_expression_is_formatted():
    bmi = _col(_doc(_report_umf()), "latest_bmi")
    [cand] = bmi.candidates
    assert cand.expression is not None
    assert "WHERE description" in cand.expression  # sqlparse upper-cases keywords


def test_reason_and_survivorship_rendered_as_prose():
    pcp = _col(_doc(_report_umf()), "pcp_name")
    assert pcp.candidates[0].reason_html is not None
    assert "Prefer the GP." in pcp.candidates[0].reason_html
    assert pcp.survivorship is not None
    assert pcp.survivorship.strategy == "highest_priority"
    assert pcp.survivorship.explanation_html is not None
    assert "<strong>Strategy:</strong>" in pcp.survivorship.explanation_html


def test_plain_column_has_no_derivation():
    plain = _col(_doc(_report_umf()), "id")
    assert plain.candidates == []
    assert plain.survivorship is None


def test_expectations_split_into_column_and_table_rules_with_samples():
    umf = _report_umf().model_copy(
        update={
            "expectations": ExpectationSuite(
                expectations=[
                    Expectation(
                        type="expect_column_values_to_be_in_set",
                        kwargs={"column": "pcp_name", "value_set": ["A", "B"]},
                        meta=ExpectationMeta(
                            severity="critical", description="Known names"
                        ),
                    ),
                    Expectation(
                        type="expect_table_row_count_to_be_between",
                        kwargs={"min_value": 1},
                    ),
                ]
            )
        }
    )
    doc = _doc(umf)
    pcp = _col(doc, "pcp_name")
    assert [(r.type, r.severity) for r in pcp.validations] == [
        ("expect_column_values_to_be_in_set", "critical")
    ]
    assert pcp.sample_values == ["A", "B"]
    assert [r.type for r in doc.table_rules] == ["expect_table_row_count_to_be_between"]
