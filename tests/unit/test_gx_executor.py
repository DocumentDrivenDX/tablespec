"""Tests for GXSuiteExecutor — suite-level GX execution with staged validation.

Unit tests cover pure logic (dataclasses, classification, routing).
Actual GX execution against Spark/Sail is covered in contract tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tablespec.validation.gx_executor import (
    ExpectationResult,
    GXSuiteExecutor,
    StagedExecutionResult,
    SuiteExecutionResult,
)

pytestmark = [
    pytest.mark.fast,
    pytest.mark.no_spark,
]


# ── SuiteExecutionResult dataclass tests ──────────────────────────────


class TestSuiteExecutionResult:
    def test_from_results_all_passing(self):
        results = [
            ExpectationResult(expectation_type="a", success=True),
            ExpectationResult(expectation_type="b", success=True),
        ]
        r = SuiteExecutionResult.from_results(results)
        assert r.success is True
        assert r.total == 2
        assert r.passed == 2
        assert r.failed == 0

    def test_from_results_all_failing(self):
        results = [
            ExpectationResult(expectation_type="a", success=False),
            ExpectationResult(expectation_type="b", success=False),
        ]
        r = SuiteExecutionResult.from_results(results)
        assert r.success is False
        assert r.total == 2
        assert r.passed == 0
        assert r.failed == 2

    def test_from_results_mixed(self):
        results = [
            ExpectationResult(expectation_type="a", success=True),
            ExpectationResult(expectation_type="b", success=False),
        ]
        r = SuiteExecutionResult.from_results(results)
        assert r.success is False
        assert r.total == 2
        assert r.passed == 1
        assert r.failed == 1

    def test_from_results_empty(self):
        r = SuiteExecutionResult.from_results([])
        assert r.success is True
        assert r.total == 0
        assert r.passed == 0
        assert r.failed == 0

    def test_from_results_single_pass(self):
        r = SuiteExecutionResult.from_results(
            [ExpectationResult(expectation_type="a", success=True)]
        )
        assert r.success is True
        assert r.total == 1

    def test_from_results_single_fail(self):
        r = SuiteExecutionResult.from_results(
            [ExpectationResult(expectation_type="a", success=False)]
        )
        assert r.success is False
        assert r.total == 1


# ── ExpectationResult defaults ────────────────────────────────────────


class TestExpectationResult:
    def test_defaults(self):
        r = ExpectationResult(expectation_type="test", success=True)
        assert r.column is None
        assert r.observed_value is None
        assert r.unexpected_count == 0
        assert r.unexpected_values == []
        assert r.details == {}

    def test_with_column(self):
        r = ExpectationResult(expectation_type="test", success=True, column="id")
        assert r.column == "id"


# ── execute_suite: empty short-circuit ────────────────────────────────


class TestExecuteSuiteEmpty:
    def test_empty_expectations_returns_empty_success(self):
        executor = GXSuiteExecutor(spark=None)
        result = executor.execute_suite(MagicMock(), [])
        assert result.success is True
        assert result.total == 0


class TestValidateExpectation:
    def test_validate_expectation_success(self):
        executor = GXSuiteExecutor(spark=None)

        import types

        mock_suite_cls = MagicMock()
        mock_suite = MagicMock()
        mock_suite_cls.return_value = mock_suite
        mock_config_cls = MagicMock()

        core_module = types.ModuleType("great_expectations.core")
        core_module.ExpectationSuite = mock_suite_cls
        config_module = types.ModuleType(
            "great_expectations.expectations.expectation_configuration"
        )
        config_module.ExpectationConfiguration = mock_config_cls

        with patch.dict(
            "sys.modules",
            {
                "great_expectations.core": core_module,
                "great_expectations.expectations.expectation_configuration": config_module,
            },
        ):
            is_valid, error = executor.validate_expectation(
                "expect_column_to_exist",
                {"column": "id"},
                {"severity": "critical"},
            )

        assert is_valid is True
        assert error is None
        mock_suite_cls.assert_called_once_with(name="validation_test")
        mock_config_cls.assert_called_once_with(
            type="expect_column_to_exist",
            kwargs={"column": "id"},
            meta={"severity": "critical"},
        )
        mock_suite.add_expectation_configuration.assert_called_once()

    def test_validate_expectation_failure(self):
        executor = GXSuiteExecutor(spark=None)

        import types

        mock_suite_cls = MagicMock(side_effect=ValueError("bad expectation"))
        core_module = types.ModuleType("great_expectations.core")
        core_module.ExpectationSuite = mock_suite_cls
        config_module = types.ModuleType(
            "great_expectations.expectations.expectation_configuration"
        )
        config_module.ExpectationConfiguration = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "great_expectations.core": core_module,
                "great_expectations.expectation_configuration": config_module,
                "great_expectations.expectations.expectation_configuration": config_module,
            },
        ):
            is_valid, error = executor.validate_expectation(
                "bad_type",
                {"column": "id"},
            )

        assert is_valid is False
        assert "bad expectation" in error


# ── execute_staged: classification and routing ────────────────────────


class TestStagedExecution:
    """Tests for execute_staged classification logic.

    Mocks execute_suite to isolate routing from actual GX execution.
    """

    def _make_executor(self):
        executor = GXSuiteExecutor(spark=None)
        return executor

    def _mock_execute_suite(self, executor):
        """Patch execute_suite to return a result reflecting the expectations passed in."""

        def side_effect(df, expectations):
            results = [
                ExpectationResult(
                    expectation_type=e.get("type", e.get("expectation_type", "")),
                    success=True,
                    column=e.get("kwargs", {}).get("column"),
                )
                for e in expectations
            ]
            return SuiteExecutionResult.from_results(results)

        return patch.object(executor, "execute_suite", side_effect=side_effect)

    def test_routes_raw_and_ingested(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    # regex → raw
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "age", "regex": r"^\d+$"},
                    },
                    # between → ingested
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {"column": "age", "min_value": 1, "max_value": 150},
                    },
                ],
            )
        assert result.raw.total == 1
        assert result.ingested.total == 1

    def test_skips_redundant(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [{"type": "expect_column_to_exist", "kwargs": {"column": "id"}}],
            )
        assert len(result.skipped) == 1
        assert result.skipped[0]["reason"] == "redundant"

    def test_empty_staged(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(MagicMock(), MagicMock(), [])
        assert result.raw.total == 0
        assert result.ingested.total == 0

    def test_honors_explicit_stage_in_meta(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        # normally raw, forced to ingested
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "val"},
                        "meta": {"validation_stage": "ingested"},
                    },
                ],
            )
        assert result.raw.total == 0
        assert result.ingested.total == 1

    def test_only_raw_expectations(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "x", "regex": ".*"},
                    },
                ],
            )
        assert result.raw.total == 1
        assert result.ingested.total == 0

    def test_only_ingested_expectations(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {"column": "x", "min_value": 0, "max_value": 100},
                    },
                ],
            )
        assert result.raw.total == 0
        assert result.ingested.total == 1

    def test_force_raw_type_to_ingested_via_meta(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "x", "regex": ".*"},
                        "meta": {"validation_stage": "ingested"},
                    },
                ],
            )
        assert result.raw.total == 0
        assert result.ingested.total == 1

    def test_force_ingested_type_to_raw_via_meta(self):
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {"column": "x", "min_value": 0, "max_value": 100},
                        "meta": {"validation_stage": "raw"},
                    },
                ],
            )
        assert result.raw.total == 1
        assert result.ingested.total == 0

    def test_expectation_type_alias_key(self):
        """execute_staged handles 'expectation_type' as alias for 'type'."""
        executor = self._make_executor()
        with self._mock_execute_suite(executor):
            result = executor.execute_staged(
                MagicMock(),
                MagicMock(),
                [
                    {
                        "expectation_type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "x", "regex": ".*"},
                    },
                ],
            )
        assert result.raw.total == 1


# ── _cleanup robustness ───────────────────────────────────────────────


class TestCleanupRobustness:
    def test_cleanup_survives_all_deletions_raising(self):
        """_cleanup should not raise even if every delete call fails."""
        context = MagicMock()
        context.validation_definitions.delete.side_effect = RuntimeError("boom")
        context.suites.delete.side_effect = RuntimeError("boom")
        context.data_sources.delete.side_effect = RuntimeError("boom")
        ds = MagicMock()
        ds.delete_asset.side_effect = RuntimeError("boom")

        # Should not raise
        GXSuiteExecutor._cleanup(
            context, MagicMock(name="suite"), ds, "ds", "asset", "vd"
        )

    def test_cleanup_without_vd(self):
        """_cleanup works when vd_name is None."""
        context = MagicMock()
        ds = MagicMock()
        GXSuiteExecutor._cleanup(
            context, MagicMock(name="suite"), ds, "ds", "asset", None
        )
        context.validation_definitions.delete.assert_not_called()

    def test_cleanup_without_ds(self):
        """_cleanup works when ds is None."""
        context = MagicMock()
        GXSuiteExecutor._cleanup(
            context, MagicMock(name="suite"), None, "ds", "asset", "vd"
        )


# ── StagedExecutionResult ─────────────────────────────────────────────


class TestStagedExecutionResult:
    def test_structure(self):
        raw = SuiteExecutionResult.from_results([])
        ingested = SuiteExecutionResult.from_results([])
        staged = StagedExecutionResult(raw=raw, ingested=ingested, skipped=[])
        assert staged.raw.success is True
        assert staged.ingested.success is True
        assert staged.skipped == []
