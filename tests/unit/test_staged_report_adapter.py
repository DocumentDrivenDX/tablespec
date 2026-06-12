"""Tests for staged validation report adaptation."""

from __future__ import annotations

import pytest

from tablespec.validation.gx_executor import (
    ExpectationResult,
    StagedExecutionResult,
    SuiteExecutionResult,
)
from tablespec.validation.staged_report import (
    build_validation_report_from_staged_execution,
)

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]


def test_build_validation_report_from_staged_execution_rehydrates_metadata() -> None:
    staged = StagedExecutionResult(
        raw=SuiteExecutionResult.from_results(
            [
                ExpectationResult(
                    expectation_type="expect_column_values_to_not_be_null",
                    success=True,
                    column="customer_id",
                    unexpected_count=0,
                    observed_value=5,
                    details={"element_count": 10},
                ),
            ]
        ),
        ingested=SuiteExecutionResult.from_results(
            [
                ExpectationResult(
                    expectation_type="expect_column_values_to_be_unique",
                    success=False,
                    column="order_id",
                    unexpected_count=2,
                    observed_value=None,
                    details={"element_count": 10},
                ),
            ]
        ),
        skipped=[],
    )
    expectations = [
        {
            "type": "expect_column_values_to_not_be_null",
            "kwargs": {"column": "customer_id"},
            "meta": {
                "severity": "warning",
                "description": "customer ids must be present",
            },
        },
        {
            "type": "expect_column_values_to_be_unique",
            "kwargs": {"column": "order_id"},
            "meta": {"severity": "error"},
        },
    ]

    report = build_validation_report_from_staged_execution(
        "orders",
        staged,
        expectations,
        pipeline_name="northwind",
        run_id="run-1234",
    )

    assert report.quality_run.pipeline_name == "northwind"
    assert report.quality_run.run_id == "run-1234"
    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    assert report.success is False
    assert report.quality_run.should_block is True

    raw_result, ingested_result = report.results
    assert raw_result.check_id == "raw:expect_column_values_to_not_be_null:customer_id"
    assert raw_result.severity == "warning"
    assert raw_result.description == "customer ids must be present"
    assert raw_result.tags == ["raw"]

    assert (
        ingested_result.check_id
        == "ingested:expect_column_values_to_be_unique:order_id"
    )
    assert ingested_result.severity == "error"
    assert ingested_result.description is None
    assert ingested_result.tags == ["ingested"]

    failures = report.failures()
    assert len(failures) == 1
    assert failures[0].description == (
        "expect_column_values_to_be_unique failed on column order_id"
    )


def test_build_validation_report_from_staged_execution_handles_empty_results() -> None:
    staged = StagedExecutionResult(
        raw=SuiteExecutionResult.from_results([]),
        ingested=SuiteExecutionResult.from_results([]),
        skipped=[],
    )

    report = build_validation_report_from_staged_execution(
        "customers",
        staged,
        [],
        pipeline_name="northwind",
        run_id="run-empty",
    )

    assert report.total == 0
    assert report.passed == 0
    assert report.failed == 0
    assert report.success is True
    assert report.quality_run.should_block is False
    assert report.quality_run.run_id == "run-empty"
    assert report.summary() == "No expectations to validate"
