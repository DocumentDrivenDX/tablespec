# @covers US-029-AC1
# @covers US-029-AC2
"""Tests for the GXTestHarness (FEAT-016).

These tests verify the harness API works end-to-end with a Sail backend.
They require pysail to be installed (tablespec[lite]).
"""

from __future__ import annotations

import pytest


class TestGXTestHarness:
    """Test the GXTestHarness fixture API."""

    def test_column_exists_passes(self, gx_harness):
        """Harness detects existing columns."""
        result = gx_harness.run(
            expectations=[
                {"type": "expect_column_to_exist", "kwargs": {"column": "id"}},
                {"type": "expect_column_to_exist", "kwargs": {"column": "name"}},
            ],
            data=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        )
        assert result.all_passed

    def test_column_exists_fails_for_missing(self, gx_harness):
        """Harness detects missing columns."""
        result = gx_harness.run(
            expectations=[
                {"type": "expect_column_to_exist", "kwargs": {"column": "missing_col"}},
            ],
            data=[{"id": 1}],
        )
        assert not result.all_passed
        assert result.failed == 1
        assert not result["expect_column_to_exist"]["missing_col"].success

    def test_values_not_null(self, gx_harness):
        """Harness validates not-null constraints."""
        result = gx_harness.run(
            expectations=[
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                },
            ],
            data=[{"id": 1}, {"id": 2}, {"id": 3}],
        )
        assert result.all_passed

    def test_values_in_set(self, gx_harness):
        """Harness validates value set constraints."""
        result = gx_harness.run(
            expectations=[
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["active", "inactive"]},
                },
            ],
            data=[
                {"status": "active"},
                {"status": "inactive"},
                {"status": "active"},
            ],
        )
        assert result.all_passed

    def test_values_in_set_fails(self, gx_harness):
        """Harness catches values outside the allowed set."""
        result = gx_harness.run(
            expectations=[
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["active", "inactive"]},
                },
            ],
            data=[
                {"status": "active"},
                {"status": "unknown"},
            ],
        )
        assert not result.all_passed
        assert len(result.failures) == 1

    def test_result_index_keyerror(self, gx_harness):
        """Accessing a non-existent expectation type raises KeyError."""
        result = gx_harness.run(
            expectations=[
                {"type": "expect_column_to_exist", "kwargs": {"column": "id"}},
            ],
            data=[{"id": 1}],
        )
        with pytest.raises(KeyError, match="No results for"):
            result["expect_nonexistent_type"]

    def test_result_column_attribute_error(self, gx_harness):
        """Accessing a non-existent column raises AttributeError."""
        result = gx_harness.run(
            expectations=[
                {"type": "expect_column_to_exist", "kwargs": {"column": "id"}},
            ],
            data=[{"id": 1}],
        )
        with pytest.raises(AttributeError, match="No result for column"):
            result["expect_column_to_exist"].nonexistent_column

    def test_multiple_expectation_types(self, gx_harness):
        """Harness handles mixed expectation types."""
        result = gx_harness.run(
            expectations=[
                {"type": "expect_column_to_exist", "kwargs": {"column": "id"}},
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                },
                {
                    "type": "expect_column_values_to_be_unique",
                    "kwargs": {"column": "id"},
                },
            ],
            data=[{"id": 1}, {"id": 2}, {"id": 3}],
        )
        assert result.all_passed
        assert result.total >= 1  # GX may bundle expectations into fewer metrics

    def test_empty_expectations(self, gx_harness):
        """Harness handles empty expectation list."""
        result = gx_harness.run(
            expectations=[],
            data=[{"id": 1}],
        )
        assert result.all_passed
        assert result.total == 0
