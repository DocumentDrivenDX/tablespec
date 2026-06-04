"""Direct unit tests for the dbt ``schema_tests`` YAML renderer.

Covers the standalone render helpers, the ``data_tests:`` header behaviour, the
quote-escaping of accepted_values, and the unknown-kind guard.
"""

from __future__ import annotations

import pytest
import yaml

from tablespec.core.schema_facts import ColumnTest
from tablespec.dbt.schema_tests import (
    render_accepted_values,
    render_column_test,
    render_relationship,
    render_tests_for_column,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _parse(lines: list[str]):
    # Reproduce the real schema.yml layout: the column item's content (``name``,
    # ``data_tests``) sits at 8 spaces (``      - name: c``), so the rendered
    # 8/10/14-space lines nest correctly under it.
    doc = "columns:\n      - name: c\n" + "\n".join(lines) + "\n"
    return yaml.safe_load(doc)["columns"][0]["data_tests"]


def test_render_relationship_lines() -> None:
    rel = ColumnTest.relationship("m_id", to_model="ingested_member", to_field="id")
    lines = render_relationship(rel)
    tests = _parse(["        data_tests:", *lines])
    assert tests == [
        {
            "relationships": {
                "arguments": {"to": "ref('ingested_member')", "field": "id"}
            }
        }
    ]


def test_render_accepted_values_lines() -> None:
    av = ColumnTest.accepted_values("lob", values=["MD", "ME"])
    lines = render_accepted_values(av)
    tests = _parse(["        data_tests:", *lines])
    assert tests == [{"accepted_values": {"arguments": {"values": ["MD", "ME"]}}}]


def test_render_accepted_values_escapes_quotes() -> None:
    av = ColumnTest.accepted_values("c", values=['a"b', "c\\d"])
    tests = _parse(["        data_tests:", *render_accepted_values(av)])
    # The embedded double-quote and backslash round-trip through YAML intact.
    assert tests[0]["accepted_values"]["arguments"]["values"] == ['a"b', "c\\d"]


def test_render_column_test_dispatch() -> None:
    rel = ColumnTest.relationship("c", to_model="m", to_field="f")
    av = ColumnTest.accepted_values("c", values=["x"])
    assert render_column_test(rel) == render_relationship(rel)
    assert render_column_test(av) == render_accepted_values(av)


def test_render_column_test_unknown_kind_raises() -> None:
    bad = ColumnTest(column="c", kind="bogus")
    with pytest.raises(ValueError, match="unknown schema-test kind"):
        render_column_test(bad)


def test_render_tests_for_column_empty() -> None:
    assert render_tests_for_column([]) == []


def test_render_tests_for_column_has_header() -> None:
    rel = ColumnTest.relationship("c", to_model="m", to_field="f")
    out = render_tests_for_column([rel])
    assert out[0] == "        data_tests:"
    assert any("relationships" in line for line in out)
