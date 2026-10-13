"""Tests for naming convention validation."""

from __future__ import annotations

import pytest

from tablespec.models.umf import UMF, UMFColumn
from tablespec.naming_validator import (
    _is_valid_snake_case,
    validate_column_naming,
    validate_naming_conventions,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _make_umf(table_name: str, column_names: list[str]) -> UMF:
    """Helper to create a minimal UMF for testing."""
    columns = [UMFColumn(name=name, data_type="VARCHAR") for name in column_names]
    return UMF(version="1.0", table_name=table_name, columns=columns)


class TestIsValidSnakeCase:
    """Test the _is_valid_snake_case helper."""

    def test_valid_names(self):
        """Valid snake_case names."""
        assert _is_valid_snake_case("member_id") is True
        assert _is_valid_snake_case("first_name") is True
        assert _is_valid_snake_case("a") is True
        assert _is_valid_snake_case("col1") is True
        assert _is_valid_snake_case("member2_data") is True

    def test_uppercase_rejected(self):
        """Uppercase letters are rejected."""
        assert _is_valid_snake_case("MemberId") is False
        assert _is_valid_snake_case("MEMBER_ID") is False
        assert _is_valid_snake_case("memberID") is False

    def test_leading_digit_rejected(self):
        """Names starting with digit are rejected."""
        assert _is_valid_snake_case("1column") is False
        assert _is_valid_snake_case("123") is False

    def test_leading_underscore_rejected(self):
        """Leading underscores are rejected."""
        assert _is_valid_snake_case("_member") is False

    def test_trailing_underscore_rejected(self):
        """Trailing underscores are rejected."""
        assert _is_valid_snake_case("member_") is False

    def test_consecutive_underscores_rejected(self):
        """Consecutive underscores are rejected."""
        assert _is_valid_snake_case("member__id") is False

    def test_empty_string_rejected(self):
        """Empty string is rejected."""
        assert _is_valid_snake_case("") is False

    def test_special_chars_rejected(self):
        """Special characters are rejected."""
        assert _is_valid_snake_case("member-id") is False
        assert _is_valid_snake_case("member.id") is False
        assert _is_valid_snake_case("member id") is False


class TestValidateNamingConventions:
    """Test full naming convention validation."""

    def test_valid_umf_no_errors(self):
        """Valid snake_case names produce no errors."""
        umf = _make_umf("member_data", ["member_id", "first_name", "last_name"])
        errors = validate_naming_conventions(umf)
        assert errors == []

    def test_invalid_table_name(self):
        """Invalid table name produces error."""
        umf = _make_umf("MemberData", ["member_id"])
        errors = validate_naming_conventions(umf)
        assert len(errors) == 1
        assert errors[0][0] == "table_name"
        assert "MemberData" in errors[0][1]

    def test_invalid_column_name(self):
        """Invalid column name produces error."""
        umf = _make_umf("member_data", ["MemberID", "first_name"])
        errors = validate_naming_conventions(umf)
        assert len(errors) == 1
        assert errors[0][0] == "MemberID"

    def test_multiple_errors(self):
        """Multiple invalid names produce multiple errors."""
        umf = _make_umf("BadTable", ["BadCol1", "good_col", "BadCol2"])
        errors = validate_naming_conventions(umf)
        # table_name + 2 bad columns = 3 errors
        assert len(errors) == 3

    def test_all_valid_single_column(self):
        """Single valid column UMF passes."""
        umf = _make_umf("t", ["c"])
        errors = validate_naming_conventions(umf)
        assert errors == []


class TestValidateColumnNaming:
    """Test deprecated validate_column_naming function."""

    def test_valid_columns_no_errors(self):
        """Valid column names produce no errors."""
        umf = _make_umf("member_data", ["member_id", "first_name"])
        errors = validate_column_naming(umf)
        assert errors == []

    def test_invalid_columns(self):
        """Invalid column names produce errors."""
        umf = _make_umf("member_data", ["MemberID", "FirstName"])
        errors = validate_column_naming(umf)
        assert len(errors) == 2

    def test_does_not_check_table_name(self):
        """validate_column_naming does NOT check the table name."""
        umf = _make_umf("BadTable", ["good_col"])
        errors = validate_column_naming(umf)
        assert errors == []

    def test_mixed_valid_invalid(self):
        """Mixed valid and invalid columns."""
        umf = _make_umf("t", ["good_col", "BadCol", "ok"])
        errors = validate_column_naming(umf)
        assert len(errors) == 1
        assert errors[0][0] == "BadCol"
