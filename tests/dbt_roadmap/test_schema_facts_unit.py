"""Direct unit tests for the engine-agnostic ``core.schema_facts`` derivation.

These hit the core seam with no dbt involvement: relationships (with the
resolve_target callback, cross-pipeline skip, unresolvable skip), accepted_values
(unified suite + legacy validation_rules path, empty/missing set), and the merged
``column_tests`` ordering.
"""

from __future__ import annotations

import pytest

from tablespec.core.schema_facts import (
    ColumnTest,
    accepted_values_tests,
    column_tests,
    relationship_tests,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _resolve_all(name: str) -> str:
    return f"ingested_{name}"


def test_relationship_resolves_via_callback() -> None:
    data = {
        "relationships": {
            "foreign_keys": [
                {
                    "column": "m_id",
                    "references_table": "member",
                    "references_column": "id",
                }
            ]
        }
    }
    tests = relationship_tests(data, _resolve_all)
    assert tests == [
        ColumnTest.relationship("m_id", to_model="ingested_member", to_field="id")
    ]


def test_relationship_cross_pipeline_skipped() -> None:
    data = {
        "relationships": {
            "foreign_keys": [
                {
                    "column": "x",
                    "references_table": "other",
                    "references_column": "id",
                    "cross_pipeline": True,
                }
            ]
        }
    }
    assert relationship_tests(data, _resolve_all) == []


def test_relationship_unresolvable_skipped() -> None:
    data = {
        "relationships": {
            "foreign_keys": [
                {"column": "x", "references_table": "ghost", "references_column": "id"}
            ]
        }
    }
    # Resolver returns None for the unknown target -> skip.
    assert relationship_tests(data, lambda _name: None) == []


def test_relationship_incomplete_fk_skipped() -> None:
    data = {"relationships": {"foreign_keys": [{"column": "x"}]}}
    assert relationship_tests(data, _resolve_all) == []


def test_relationship_sorted_by_column() -> None:
    data = {
        "relationships": {
            "foreign_keys": [
                {"column": "z", "references_table": "a", "references_column": "id"},
                {"column": "a", "references_table": "b", "references_column": "id"},
            ]
        }
    }
    cols = [t.column for t in relationship_tests(data, _resolve_all)]
    assert cols == ["a", "z"]


def test_accepted_values_from_unified_suite() -> None:
    data = {
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": ["MD", "ME"]},
                }
            ]
        }
    }
    assert accepted_values_tests(data) == [
        ColumnTest.accepted_values("lob", values=["MD", "ME"])
    ]


def test_accepted_values_from_legacy_validation_rules() -> None:
    data = {
        "validation_rules": {
            "expectations": [
                {
                    "expectation_type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "state", "value_set": ["NY", "CA"]},
                }
            ]
        }
    }
    assert accepted_values_tests(data) == [
        ColumnTest.accepted_values("state", values=["NY", "CA"])
    ]


def test_accepted_values_empty_set_skipped() -> None:
    data = {
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": []},
                }
            ]
        }
    }
    assert accepted_values_tests(data) == []


def test_accepted_values_first_set_wins_per_column() -> None:
    data = {
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": ["A"]},
                },
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": ["B"]},
                },
            ]
        }
    }
    out = accepted_values_tests(data)
    assert out == [ColumnTest.accepted_values("lob", values=["A"])]


def test_accepted_values_coerces_to_str() -> None:
    data = {
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "n", "value_set": [1, 2, 3]},
                }
            ]
        }
    }
    assert accepted_values_tests(data)[0].values == ("1", "2", "3")


def test_column_tests_merges_and_sorts() -> None:
    data = {
        "relationships": {
            "foreign_keys": [
                {
                    "column": "lob",
                    "references_table": "dim",
                    "references_column": "code",
                }
            ]
        },
        "expectations": {
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "lob", "value_set": ["A", "B"]},
                }
            ]
        },
    }
    tests = column_tests(data, _resolve_all)
    # Same column carries both; sorted by (column, kind): accepted_values < relationship.
    assert [(t.column, t.kind) for t in tests] == [
        ("lob", "accepted_values"),
        ("lob", "relationship"),
    ]
