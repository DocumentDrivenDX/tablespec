# SPDX-License-Identifier: MIT OR Apache-2.0
"""Pure helpers in ``native_executor``: column-set matching over bare column
names, and GX ``result_format`` -> failing-value sample limit."""

from __future__ import annotations

import pytest

from tablespec.validation.native_executor import (
    columns_match_set,
    is_natively_supported,
    partial_unexpected_limit,
)

pytestmark = pytest.mark.no_spark


def test_match_set_is_natively_supported():
    assert is_natively_supported("expect_table_columns_to_match_set")


def test_match_set_exact_reports_missing_and_unexpected():
    r = columns_match_set(["a", "c", "SYS_X"], ["a", "b", "c"])
    assert r["success"] is False
    assert r["result"]["observed_value"] == ["SYS_X", "a", "c"]
    assert r["result"]["details"]["mismatched"] == {
        "unexpected": ["SYS_X"],
        "missing": ["b"],
    }
    assert r["result"]["unexpected_count"] == 2


def test_match_set_exact_none_defaults_to_exact():
    assert columns_match_set(["a", "b"], ["a"], exact_match=None)["success"] is False


def test_match_set_superset_passes_without_exact_match():
    r = columns_match_set(["a", "b", "extra"], ["b", "a"], exact_match=False)
    assert r["success"] is True
    assert r["result"]["details"]["mismatched"] == {"unexpected": ["extra"]}
    assert r["result"]["unexpected_count"] == 0


def test_match_set_missing_fails_without_exact_match():
    r = columns_match_set(["a"], ["a", "b"], exact_match=False)
    assert r["success"] is False
    assert r["result"]["details"]["mismatched"] == {"missing": ["b"]}


def test_match_set_clean_has_empty_mismatch():
    r = columns_match_set(["b", "a"], ["a", "b"])
    assert r["success"] is True
    assert r["result"]["details"]["mismatched"] == {}


@pytest.mark.parametrize(
    ("result_format", "expected"),
    [
        (None, 10),
        ("BASIC", 10),
        ("SUMMARY", 10),
        ("BOOLEAN_ONLY", 0),
        ("boolean_only", 0),
        ({"result_format": "BOOLEAN_ONLY"}, 0),
        ({"result_format": "SUMMARY", "partial_unexpected_count": 0}, 0),
        ({"result_format": "COMPLETE", "partial_unexpected_count": 3}, 3),
    ],
)
def test_partial_unexpected_limit(result_format, expected):
    assert partial_unexpected_limit(result_format) == expected
