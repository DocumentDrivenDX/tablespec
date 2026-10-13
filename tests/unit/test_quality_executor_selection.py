"""Tests for QualityCheckExecutor expectation source selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tablespec.models.umf import Expectation, ExpectationMeta, ExpectationSuite
from tablespec.quality.executor import QualityCheckExecutor

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]


def _make_executor() -> QualityCheckExecutor:
    return object.__new__(QualityCheckExecutor)


class TestConfiguredCheckSelection:
    def test_prefers_expectation_suite_when_populated(self) -> None:
        executor = _make_executor()
        suite = ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_be_between",
                    kwargs={"column": "amount", "min_value": 0},
                    meta=ExpectationMeta(
                        stage="ingested",
                        severity="critical",
                        blocking=True,
                        description="amount must be non-negative",
                        tags=["finance"],
                    ),
                ),
                Expectation(
                    type="expect_column_values_to_match_regex",
                    kwargs={"column": "code", "regex": r"^[A-Z]+$"},
                    meta=ExpectationMeta(stage="raw"),
                ),
            ],
            thresholds={"max_failures": 2},
        )
        umf = SimpleNamespace(
            expectations=suite,
            model_dump=lambda **_: {"quality_checks": {"checks": ["legacy"]}},
        )

        with patch(
            "tablespec.quality.executor.migrate_to_expectation_suite"
        ) as migrate:
            checks, thresholds = executor._get_configured_checks(umf)

        migrate.assert_not_called()
        assert thresholds == {"max_failures": 2}
        assert len(checks) == 1
        assert checks[0].expectation["type"] == "expect_column_values_to_be_between"
        assert checks[0].severity == "critical"
        assert checks[0].blocking is True
        assert checks[0].description == "amount must be non-negative"
        assert checks[0].tags == ["finance"]

    def test_falls_back_to_legacy_checks_when_suite_is_empty(self) -> None:
        executor = _make_executor()
        umf = SimpleNamespace(
            expectations=ExpectationSuite(expectations=[]),
            model_dump=lambda **_: {"quality_checks": {"checks": ["legacy"]}},
        )
        migrated_suite = ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_be_in_set",
                    kwargs={"column": "status", "value_set": ["A", "B"]},
                    meta=ExpectationMeta(stage="ingested", severity="warning"),
                )
            ],
            thresholds={"min_success_rate": 95.0},
        )

        with patch(
            "tablespec.quality.executor.migrate_to_expectation_suite",
            return_value=migrated_suite,
        ) as migrate:
            checks, thresholds = executor._get_configured_checks(umf)

        migrate.assert_called_once_with({"quality_checks": {"checks": ["legacy"]}})
        assert thresholds == {"min_success_rate": 95.0}
        assert len(checks) == 1
        assert checks[0].expectation["type"] == "expect_column_values_to_be_in_set"
        assert checks[0].severity == "warning"

    def test_does_not_fall_back_when_suite_has_only_raw_expectations(self) -> None:
        executor = _make_executor()
        umf = SimpleNamespace(
            expectations=ExpectationSuite(
                expectations=[
                    Expectation(
                        type="expect_column_values_to_match_regex",
                        kwargs={"column": "id", "regex": r"^\d+$"},
                        meta=ExpectationMeta(stage="raw"),
                    )
                ]
            ),
            model_dump=lambda **_: {"quality_checks": {"checks": ["legacy"]}},
        )

        with patch(
            "tablespec.quality.executor.migrate_to_expectation_suite"
        ) as migrate:
            checks, thresholds = executor._get_configured_checks(umf)

        migrate.assert_not_called()
        assert checks == []
        assert thresholds is None
