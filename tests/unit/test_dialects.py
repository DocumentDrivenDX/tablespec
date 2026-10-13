"""Unit tests for the public cast dialect contract."""

from __future__ import annotations

import pytest

from tablespec.dialects import (
    CAST_DIALECTS,
    PROFILE_TARGETS,
    normalize_cast_dialect,
    validate_profile_target,
)


def test_cast_dialects_public_set() -> None:
    assert set(CAST_DIALECTS) == {"spark", "databricks", "duckdb"}


def test_normalize_cast_dialect_spark_family() -> None:
    assert normalize_cast_dialect("spark") == "spark"
    assert normalize_cast_dialect("databricks") == "spark"
    assert normalize_cast_dialect("duckdb") == "duckdb"


def test_normalize_cast_dialect_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported dialect"):
        normalize_cast_dialect("postgres")


def test_validate_profile_target() -> None:
    for t in PROFILE_TARGETS:
        assert validate_profile_target(t) == t
    with pytest.raises(ValueError, match="profile target"):
        validate_profile_target("snowflake")
