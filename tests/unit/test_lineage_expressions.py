"""Tests for tablespec.lineage.expressions.extract_refs."""

import pytest

from tablespec.lineage.expressions import ExprRef, extract_refs

pytestmark = pytest.mark.no_spark


def test_disposition_id_case_expression():
    expr = (
        "CASE WHEN UPPER(TRIM(base.me_attr4)) IN ('PED', 'PED-ERD') "
        "THEN base.exclusion_iha_ped__disposition_id "
        "ELSE base.exclusion_iha_adult__disposition_id END"
    )
    # Keywords come back as bare candidates; the builder drops those that match no column.
    assert [r for r in extract_refs(expr) if r.kind != "bare"] == [
        ExprRef("base", "me_attr4"),
        ExprRef("prefixed", "disposition_id", alias="exclusion_iha_ped"),
        ExprRef("prefixed", "disposition_id", alias="exclusion_iha_adult"),
    ]


def test_placeholders_with_and_without_field():
    refs = extract_refs(
        "CASE WHEN {{col:a_date}} IS NOT NULL THEN {{ col:a_date.result }} END"
    )
    assert ExprRef("placeholder", "a_date") in refs
    assert ExprRef("placeholder", "a_date", field="result") in refs
    # Placeholder contents are not re-read as bare identifiers.
    assert ExprRef("bare", "result") not in refs


def test_string_literals_and_template_vars_produce_no_refs():
    refs = extract_refs("test_name = 'Glyco HGB A1C' AND YEAR(d) = {{pipeline_year}}")
    names = {r.column for r in refs}
    assert "Glyco" not in names
    assert "pipeline_year" not in names
    assert {"test_name", "d"} <= names


def test_function_calls_and_qualified_names_are_skipped():
    refs = extract_refs("CONCAT_WS(' ', first_name, p.last_name)")
    names = [r.column for r in refs if r.kind == "bare"]
    assert "CONCAT_WS" not in names
    assert "first_name" in names
    assert "last_name" not in names
    assert "p" not in names


def test_refs_are_deduplicated_in_order():
    assert extract_refs("a + a + b") == [ExprRef("bare", "a"), ExprRef("bare", "b")]


def test_unqualified_alias_column_is_a_prefixed_ref():
    refs = extract_refs("COALESCE(datawarehouse_iha__call_status, '') <> 'Inbound'")
    assert refs == [ExprRef("prefixed", "call_status", alias="datawarehouse_iha")]
