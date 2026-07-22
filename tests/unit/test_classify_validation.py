"""Tests for classify_validation_type() and validation type sets."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.fast

from tablespec.models.umf import (
    INGESTED_QUALITY_CHECK_TYPES,
    RAW_VALIDATION_TYPES,
    REDUNDANT_VALIDATION_TYPES,
    classify_validation_type,
)


@pytest.mark.parametrize("expectation_type", sorted(RAW_VALIDATION_TYPES))
def test_raw_validation_types_return_raw(expectation_type: str) -> None:
    assert classify_validation_type(expectation_type) == "raw"


@pytest.mark.parametrize("expectation_type", sorted(INGESTED_QUALITY_CHECK_TYPES))
def test_ingested_quality_check_types_return_ingested(expectation_type: str) -> None:
    assert classify_validation_type(expectation_type) == "ingested"


@pytest.mark.parametrize("expectation_type", sorted(REDUNDANT_VALIDATION_TYPES))
def test_redundant_validation_types_return_unknown(expectation_type: str) -> None:
    """Redundant types are not in raw or ingested sets, so they return 'unknown'."""
    assert classify_validation_type(expectation_type) == "unknown"


def test_unknown_type_returns_unknown() -> None:
    assert classify_validation_type("expect_something_totally_made_up") == "unknown"


def test_empty_string_returns_unknown() -> None:
    assert classify_validation_type("") == "unknown"


def test_no_overlap_between_raw_and_ingested() -> None:
    """Raw and ingested sets must be disjoint."""
    overlap = RAW_VALIDATION_TYPES & INGESTED_QUALITY_CHECK_TYPES
    assert overlap == frozenset(), f"Unexpected overlap: {overlap}"


def test_no_overlap_between_raw_and_redundant() -> None:
    overlap = RAW_VALIDATION_TYPES & REDUNDANT_VALIDATION_TYPES
    assert overlap == frozenset(), f"Unexpected overlap: {overlap}"


def test_no_overlap_between_ingested_and_redundant() -> None:
    overlap = INGESTED_QUALITY_CHECK_TYPES & REDUNDANT_VALIDATION_TYPES
    assert overlap == frozenset(), f"Unexpected overlap: {overlap}"
