"""Tests for the guidebook table-page renderer — derivation-rule display."""

# @covers US-046-AC3

from __future__ import annotations

from tablespec.guidebook.renderer import render_table_page
from tablespec.guidebook.reverse_lineage import ReverseLineageIndex
from tablespec.models.umf import (
    UMF,
    DerivationCandidate,
    Survivorship,
    UMFColumn,
    UMFColumnDerivation,
)

_EMPTY_INDEX = ReverseLineageIndex()


def _render(umf: UMF) -> str:
    return render_table_page(umf, _EMPTY_INDEX)


def _report_umf() -> UMF:
    """A generated report with the three derivation-candidate shapes."""
    return UMF(
        version="1.0",
        table_name="member_report",
        canonical_name="member_report",
        table_type="generated",
        description="Computed report.",
        columns=[
            # Column-only candidate WITH a join filter, no expression — the
            # regression case: its priority + filter must still render.
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
                            priority=1,
                            reason="Prefer the GP.",
                            join_filter="SPECIALITY = 'GENERAL PRACTICE'",
                        ),
                        DerivationCandidate(
                            table="providers",
                            column="NAME",
                            priority=2,
                            reason="Fallback provider.",
                            join_filter="encounter_rank = 1",
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


def test_derivation_rules_block_present():
    html = _render(_report_umf())
    assert "Derivation rules" in html  # multi-candidate label (pcp_name)
    assert "Derivation rule</summary>" in html  # singular label (latest_bmi)


def test_join_filter_renders_for_column_only_candidate():
    """Regression: a candidate with a join_filter but NO expression still shows
    its filter and priority (previously dropped)."""
    html = _render(_report_umf())
    assert "SPECIALITY = &#x27;GENERAL PRACTICE&#x27;" in html
    assert "encounter_rank = 1" in html
    assert "Priority 1" in html
    assert "Priority 2" in html


def test_candidates_ordered_by_priority():
    html = _render(_report_umf())
    assert html.index("Priority 1") < html.index("Priority 2")


def test_sql_expression_rendered_when_present():
    html = _render(_report_umf())
    # The BMI expression becomes a formatted <pre> block (sqlparse upper-cases
    # the WHERE keyword).
    assert "<pre><code>" in html
    assert "WHERE description" in html


def test_no_empty_sql_block_for_column_only_candidate():
    """A column-only candidate (id-style) must not emit an empty <pre>."""
    umf = UMF(
        version="1.0",
        table_name="t",
        canonical_name="t",
        columns=[
            UMFColumn(
                name="patient_id",
                data_type="VARCHAR",
                length=36,
                derivation=UMFColumnDerivation(
                    candidates=[
                        DerivationCandidate(
                            table="patients",
                            column="Id",
                            priority=1,
                            reason="Keyed by patient.",
                        )
                    ],
                ),
            ),
        ],
    )
    html = _render(umf)
    assert "patients.Id" in html
    assert "<pre><code></code></pre>" not in html


def test_reason_rendered_as_why():
    html = _render(_report_umf())
    assert "<strong>Why:</strong>" in html
    assert "Prefer the GP." in html


def test_survivorship_block_unchanged():
    html = _render(_report_umf())
    assert "Survivorship logic" in html
    assert "<strong>Strategy:</strong>" in html


def test_plain_column_has_no_derivation_block():
    # The 'id' column (no derivation) should not appear inside a candidate-block.
    html = _render(_report_umf())
    # crude but effective: there are exactly as many candidate-blocks as candidates (3).
    assert html.count('<div class="candidate-block">') == 3
