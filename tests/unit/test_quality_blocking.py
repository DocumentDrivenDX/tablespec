# @covers US-030-AC1
"""Tests for QualityCheckExecutor blocking/threshold logic.

Tests the internal _should_block_pipeline() and _calculate_quality_score()
methods which implement the quality gate decision logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Inline dataclasses mirroring tablespec.models.quality
# These avoid importing the real models (which live in the main worktree)
# and let us test the pure logic without Spark or GX dependencies.
# ---------------------------------------------------------------------------


@dataclass
class QualityCheckResult:
    check_id: str
    expectation_type: str
    success: bool
    severity: str
    blocking: bool = False
    column_name: str | None = None
    description: str | None = None
    unexpected_count: int | None = None
    unexpected_percent: float | None = None
    observed_value: Any = None
    details: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class QualityScore:
    total_checks: int
    passed_checks: int
    failed_checks: int
    critical_failures: int
    warning_failures: int
    info_failures: int
    success_rate: float
    critical_failure_rate: float
    warning_failure_rate: float
    blocking_failures: int
    threshold_breached: bool = False


@dataclass
class QualityThreshold:
    max_critical_failure_percent: float | None = None
    max_warning_failure_percent: float | None = None
    min_success_rate: float | None = None
    max_failures: int | None = None
    max_critical_failures: int | None = None


# ---------------------------------------------------------------------------
# Patch the models into the executor module before importing it
# ---------------------------------------------------------------------------

_quality_models = {
    "tablespec.models.quality": type(
        "module",
        (),
        {
            "QualityCheckResult": QualityCheckResult,
            "QualityCheckRun": None,  # Not needed for these tests
            "QualityScore": QualityScore,
            "QualityThreshold": QualityThreshold,
        },
    )(),
}


def _make_executor() -> Any:
    """Create a QualityCheckExecutor with spark=None and GX disabled."""
    with patch.dict("sys.modules", _quality_models):
        from tablespec.quality.executor import QualityCheckExecutor

    # Instantiation tries to call get_gx_wrapper(); we bypass via __new__
    executor = object.__new__(QualityCheckExecutor)
    executor.spark = None
    executor.baseline = None
    executor.gx_available = False
    executor.gx_wrapper = None

    import logging

    executor.logger = logging.getLogger("QualityCheckExecutor")
    return executor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    success: bool,
    severity: str = "warning",
    blocking: bool = False,
    check_id: str = "test_check",
) -> QualityCheckResult:
    return QualityCheckResult(
        check_id=check_id,
        expectation_type="expect_column_values_to_not_be_null",
        success=success,
        severity=severity,
        blocking=blocking,
    )


# ---------------------------------------------------------------------------
# Tests: _should_block_pipeline
# ---------------------------------------------------------------------------


class TestShouldBlockPipeline:
    """Tests for QualityCheckExecutor._should_block_pipeline()."""

    @pytest.fixture()
    def executor(self) -> Any:
        return _make_executor()

    def test_blocking_critical_failure_blocks_pipeline(self, executor: Any) -> None:
        """A blocking=True + severity=critical failure blocks the pipeline."""
        results = [_result(success=False, severity="critical", blocking=True)]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=1,
        )
        assert executor._should_block_pipeline(results, score, thresholds=None) is True

    def test_nonblocking_failure_does_not_block(self, executor: Any) -> None:
        """A check with blocking=False never triggers blocking."""
        results = [_result(success=False, severity="critical", blocking=False)]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )
        assert executor._should_block_pipeline(results, score, thresholds=None) is False

    def test_threshold_min_success_rate_breached(self, executor: Any) -> None:
        """When success_rate drops below min_success_rate, threshold_breached is set True."""
        results = [
            _result(success=False, severity="warning"),
            _result(success=True, severity="warning", check_id="check2"),
        ]
        score = QualityScore(
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            critical_failures=0,
            warning_failures=1,
            info_failures=0,
            success_rate=50.0,
            critical_failure_rate=0.0,
            warning_failure_rate=50.0,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(min_success_rate=80.0)

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is True
        assert score.threshold_breached is True

    def test_threshold_max_critical_failure_percent_breached(
        self, executor: Any
    ) -> None:
        """When critical_failure_rate exceeds max_critical_failure_percent, threshold is breached."""
        results = [_result(success=False, severity="critical")]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(max_critical_failure_percent=10.0)

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is True
        assert score.threshold_breached is True

    def test_threshold_max_warning_failure_percent_breached(
        self, executor: Any
    ) -> None:
        """When warning_failure_rate exceeds max_warning_failure_percent, threshold is breached."""
        results = [_result(success=False, severity="warning")]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=0,
            warning_failures=1,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=0.0,
            warning_failure_rate=100.0,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(max_warning_failure_percent=25.0)

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is True
        assert score.threshold_breached is True

    def test_threshold_not_breached_when_within_limits(self, executor: Any) -> None:
        """When all metrics are within thresholds, threshold_breached stays False."""
        results = [
            _result(success=True, check_id="c1"),
            _result(success=True, check_id="c2"),
            _result(success=False, severity="warning", check_id="c3"),
        ]
        score = QualityScore(
            total_checks=3,
            passed_checks=2,
            failed_checks=1,
            critical_failures=0,
            warning_failures=1,
            info_failures=0,
            success_rate=66.7,
            critical_failure_rate=0.0,
            warning_failure_rate=33.3,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(
            min_success_rate=50.0,
            max_critical_failure_percent=10.0,
            max_warning_failure_percent=50.0,
        )

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is False
        assert score.threshold_breached is False

    def test_no_thresholds_configured(self, executor: Any) -> None:
        """When thresholds is None, threshold_breached is not modified on the score."""
        results = [_result(success=False, severity="critical")]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )

        result = executor._should_block_pipeline(results, score, thresholds=None)

        assert result is False
        # threshold_breached stays at its default (False) since no thresholds configured
        assert score.threshold_breached is False

    def test_multiple_thresholds_all_breached(self, executor: Any) -> None:
        """When multiple thresholds are breached, threshold_breached is True and blocks."""
        results = [_result(success=False, severity="critical")]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(
            min_success_rate=90.0,
            max_critical_failure_percent=5.0,
        )

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is True
        assert score.threshold_breached is True

    def test_threshold_max_failures_exceeded(self, executor: Any) -> None:
        """When total failure count exceeds max_failures threshold, pipeline blocks."""
        results = [
            _result(success=False, severity="warning", check_id="c1"),
            _result(success=False, severity="warning", check_id="c2"),
            _result(success=True, severity="warning", check_id="c3"),
        ]
        score = QualityScore(
            total_checks=3,
            passed_checks=1,
            failed_checks=2,
            critical_failures=0,
            warning_failures=2,
            info_failures=0,
            success_rate=33.3,
            critical_failure_rate=0.0,
            warning_failure_rate=66.7,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(max_failures=1)

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is True
        assert score.threshold_breached is True

    def test_threshold_max_failures_not_exceeded(self, executor: Any) -> None:
        """When total failure count is within max_failures threshold, no block."""
        results = [
            _result(success=False, severity="warning", check_id="c1"),
            _result(success=True, severity="warning", check_id="c2"),
        ]
        score = QualityScore(
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            critical_failures=0,
            warning_failures=1,
            info_failures=0,
            success_rate=50.0,
            critical_failure_rate=0.0,
            warning_failure_rate=50.0,
            blocking_failures=0,
        )
        thresholds = QualityThreshold(max_failures=1)

        result = executor._should_block_pipeline(results, score, thresholds)

        assert result is False
        assert score.threshold_breached is False

    def test_blocking_false_with_critical_severity_does_not_block(
        self, executor: Any
    ) -> None:
        """A check with severity=critical but blocking=False does not block the pipeline."""
        results = [_result(success=False, severity="critical", blocking=False)]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=1,
            warning_failures=0,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=100.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )
        assert executor._should_block_pipeline(results, score, thresholds=None) is False

    def test_blocking_true_with_warning_severity_does_not_block(
        self, executor: Any
    ) -> None:
        """A check with blocking=True but severity=warning does not trigger individual blocking."""
        results = [_result(success=False, severity="warning", blocking=True)]
        score = QualityScore(
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            critical_failures=0,
            warning_failures=1,
            info_failures=0,
            success_rate=0.0,
            critical_failure_rate=0.0,
            warning_failure_rate=100.0,
            blocking_failures=1,
        )
        # blocking=True only triggers for severity in (critical, error), not warning
        assert executor._should_block_pipeline(results, score, thresholds=None) is False


# ---------------------------------------------------------------------------
# Tests: _calculate_quality_score
# ---------------------------------------------------------------------------


class TestCalculateQualityScore:
    """Tests for QualityCheckExecutor._calculate_quality_score()."""

    @pytest.fixture()
    def executor(self) -> Any:
        return _make_executor()

    def test_all_pass_returns_100_percent(self, executor: Any) -> None:
        """All checks passing yields 100% success rate."""
        results = [
            _result(success=True, check_id="c1"),
            _result(success=True, check_id="c2"),
            _result(success=True, check_id="c3"),
        ]

        score = executor._calculate_quality_score(results)

        assert score.total_checks == 3
        assert score.passed_checks == 3
        assert score.failed_checks == 0
        assert score.success_rate == 100.0
        assert score.critical_failures == 0
        assert score.warning_failures == 0
        assert score.info_failures == 0
        assert score.blocking_failures == 0
        assert score.threshold_breached is False

    def test_mixed_results_correct_percentages(self, executor: Any) -> None:
        """Mixed pass/fail results compute correct metrics."""
        results = [
            _result(success=True, severity="warning", check_id="c1"),
            _result(success=False, severity="critical", blocking=True, check_id="c2"),
            _result(success=False, severity="warning", check_id="c3"),
            _result(success=False, severity="info", check_id="c4"),
        ]

        score = executor._calculate_quality_score(results)

        assert score.total_checks == 4
        assert score.passed_checks == 1
        assert score.failed_checks == 3
        assert score.success_rate == 25.0
        assert score.critical_failures == 1
        assert score.critical_failure_rate == 25.0
        assert score.warning_failures == 1
        assert score.warning_failure_rate == 25.0
        assert score.info_failures == 1
        assert score.blocking_failures == 1

    def test_empty_results(self, executor: Any) -> None:
        """Empty results list returns zero-value score."""
        score = executor._calculate_quality_score([])

        assert score.total_checks == 0
        assert score.passed_checks == 0
        assert score.failed_checks == 0
        assert score.success_rate == 0.0
        assert score.critical_failure_rate == 0.0
        assert score.warning_failure_rate == 0.0
        assert score.blocking_failures == 0
        assert score.threshold_breached is False

    def test_error_severity_counts_as_critical(self, executor: Any) -> None:
        """severity='error' is counted alongside 'critical' in critical_failures."""
        results = [
            _result(success=False, severity="error", check_id="c1"),
        ]

        score = executor._calculate_quality_score(results)

        assert score.critical_failures == 1
        assert score.critical_failure_rate == 100.0

    def test_all_fail_returns_zero_percent_success(self, executor: Any) -> None:
        """All checks failing yields 0% success rate."""
        results = [
            _result(success=False, severity="critical", check_id="c1"),
            _result(success=False, severity="warning", check_id="c2"),
        ]

        score = executor._calculate_quality_score(results)

        assert score.total_checks == 2
        assert score.passed_checks == 0
        assert score.failed_checks == 2
        assert score.success_rate == 0.0
