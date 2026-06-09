"""Executable compound uniqueness validation behavior."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning"
)


def _compound_expectation() -> dict[str, Any]:
    return {
        "type": "expect_compound_columns_to_be_unique",
        "kwargs": {"column_list": ["member_id", "effective_date"]},
    }


def _compound_expectations(expectations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        expectation
        for expectation in expectations
        if expectation["type"] == "expect_compound_columns_to_be_unique"
    ]


@pytest.mark.no_spark
def test_compound_uniqueness_executable_registry() -> None:
    from tablespec.models.umf import RAW_VALIDATION_TYPES
    from tablespec.validation import native_executor

    assert "expect_compound_columns_to_be_unique" in RAW_VALIDATION_TYPES
    assert (
        native_executor.is_natively_supported("expect_compound_columns_to_be_unique")
        is True
    )


@pytest.mark.spark_only
def test_native_executor_compound_uniqueness_passes_and_fails(
    spark_session: Any,
) -> None:
    from tablespec.validation import native_executor

    kwargs = _compound_expectation()["kwargs"]
    unique_df = spark_session.createDataFrame(
        [
            (1, "2026-01-01"),
            (1, "2026-01-02"),
            (2, "2026-01-01"),
        ],
        "member_id int, effective_date string",
    )
    duplicate_df = spark_session.createDataFrame(
        [
            (1, "2026-01-01"),
            (1, "2026-01-01"),
            (2, "2026-01-01"),
        ],
        "member_id int, effective_date string",
    )

    clean = native_executor.evaluate_expectation(
        unique_df, "expect_compound_columns_to_be_unique", kwargs
    )
    dirty = native_executor.evaluate_expectation(
        duplicate_df, "expect_compound_columns_to_be_unique", kwargs
    )

    assert clean is not None
    assert clean["success"] is True
    assert dirty is not None
    assert dirty["success"] is False
    assert dirty["result"]["unexpected_count"] == 2
    assert dirty["result"]["partial_unexpected_list"] == [
        {"member_id": 1, "effective_date": "2026-01-01"}
    ]


@pytest.mark.spark_only
def test_no_silent_dropped_compound_expectation(spark_session: Any) -> None:
    from tablespec.validation.gx_executor import GXSuiteExecutor

    df = spark_session.createDataFrame(
        [
            (1, "2026-01-01"),
            (1, "2026-01-01"),
            (2, "2026-01-01"),
        ],
        "member_id int, effective_date string",
    )

    result = GXSuiteExecutor(spark=spark_session).execute_suite(
        df, [_compound_expectation()]
    )

    assert result.total == 1
    assert result.failed == 1
    assert result.success is False
    assert result.results[0].expectation_type == "expect_compound_columns_to_be_unique"
    assert result.results[0].unexpected_count == 2


@pytest.mark.no_spark
def test_native_path_unsupported_expectation_fails_closed() -> None:
    from tablespec.validation.gx_executor import GXSuiteExecutor

    result = GXSuiteExecutor()._execute_native(
        object(),
        [{"type": "expect_unimplemented_runtime_check", "kwargs": {}}],
    )

    assert result.total == 1
    assert result.failed == 1
    assert result.results[0].success is False
    assert result.results[0].details == {
        "error": "unsupported native expectation: expect_unimplemented_runtime_check"
    }


@pytest.mark.no_spark
def test_profile_to_gx_expectation_composite_emission_gated_by_executor_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tablespec.profiling import (
        ColumnProfile,
        DataFrameProfile,
        KeyCandidate,
        KeyCandidateEvidence,
        ProfileToGxMapper,
    )
    from tablespec.validation import native_executor

    profile = DataFrameProfile(
        num_records=3,
        columns={
            "member_id": ColumnProfile(
                column_name="member_id",
                completeness=1.0,
                approximate_num_distinct=2,
                data_type="IntegerType",
                is_data_type_inferred=False,
            ),
            "effective_date": ColumnProfile(
                column_name="effective_date",
                completeness=1.0,
                approximate_num_distinct=2,
                data_type="StringType",
                is_data_type_inferred=False,
            ),
        },
        key_candidates=[
            KeyCandidate(
                columns=["member_id", "effective_date"],
                verified_exact=True,
                exact_unique=True,
                emitted=True,
                evidence=KeyCandidateEvidence(
                    minimal=True,
                    nullable=False,
                    reason="all proper subsets exact-verified non-unique",
                ),
            )
        ],
    )

    expectations = ProfileToGxMapper().build_expectations(profile)
    compound = _compound_expectations(expectations)
    assert compound == [
        {
            "type": "expect_compound_columns_to_be_unique",
            "kwargs": {"column_list": ["member_id", "effective_date"]},
            "meta": {
                "description": (
                    "member_id, effective_date: exact verified composite key candidate"
                ),
                "severity": "warning",
                "generated_from": "profiling_key_candidate",
            },
        }
    ]

    monkeypatch.setattr(native_executor, "is_natively_supported", lambda _: False)

    expectations_without_support = ProfileToGxMapper().build_expectations(profile)
    assert _compound_expectations(expectations_without_support) == []
