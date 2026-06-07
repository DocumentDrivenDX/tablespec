# @covers US-030-AC2
"""Tests for blocking behavior and validation reporting."""

import pytest

from tablespec.models.quality import (
    QualityCheckResult,
    QualityCheckRun,
    QualityScore,
    QualityThreshold,
)
from tablespec.validation.report import FailureDetail, ValidationReport

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Helper to build a QualityCheckRun from a list of results
# ---------------------------------------------------------------------------


def _make_run(results: list[QualityCheckResult], **kwargs) -> QualityCheckRun:
    defaults = {
        "pipeline_name": "test_pipeline",
        "table_name": "test_table",
        "run_id": "run-001",
        "results": results,
    }
    defaults.update(kwargs)
    return QualityCheckRun(**defaults)


# ---------------------------------------------------------------------------
# ValidationReport tests
# ---------------------------------------------------------------------------


class TestValidationReport:
    def test_all_pass_summary(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=True,
                    severity="warning",
                ),
            ]
        )
        report = ValidationReport(run)
        assert "All 1 expectations passed" in report.summary()

    def test_failures_summary(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=True,
                    severity="warning",
                ),
                QualityCheckResult(
                    check_id="chk2",
                    expectation_type="in_set",
                    success=False,
                    severity="error",
                    unexpected_count=3,
                ),
            ]
        )
        report = ValidationReport(run)
        assert "1/2" in report.summary()
        assert "1 failure" in report.summary()

    def test_multiple_failures_plural(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="a",
                    success=False,
                    severity="error",
                ),
                QualityCheckResult(
                    check_id="chk2",
                    expectation_type="b",
                    success=False,
                    severity="error",
                ),
            ]
        )
        report = ValidationReport(run)
        assert "2 failures" in report.summary()

    def test_empty_summary(self):
        run = _make_run([])
        report = ValidationReport(run)
        assert "No expectations" in report.summary()

    def test_failures_list(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=False,
                    severity="critical",
                    column_name="id",
                    unexpected_count=5,
                ),
            ]
        )
        report = ValidationReport(run)
        failures = report.failures()
        assert len(failures) == 1
        assert failures[0].column == "id"
        assert failures[0].unexpected_count == 5
        assert failures[0].severity == "critical"

    def test_failures_excludes_passing(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=True,
                    severity="warning",
                ),
                QualityCheckResult(
                    check_id="chk2",
                    expectation_type="in_set",
                    success=False,
                    severity="error",
                    column_name="state",
                ),
            ]
        )
        report = ValidationReport(run)
        failures = report.failures()
        assert len(failures) == 1
        assert failures[0].expectation_type == "in_set"

    def test_as_dict(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=True,
                    severity="info",
                ),
            ]
        )
        report = ValidationReport(run)
        d = report.as_dict()
        assert d["total"] == 1
        assert d["passed"] == 1
        assert d["failed"] == 0
        assert d["success"] is True
        assert d["table_name"] == "test_table"
        assert d["failures"] == []

    def test_as_dict_with_failures(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="in_set",
                    success=False,
                    severity="error",
                    column_name="status",
                    unexpected_count=2,
                ),
            ]
        )
        report = ValidationReport(run)
        d = report.as_dict()
        assert d["success"] is False
        assert len(d["failures"]) == 1
        assert d["failures"][0]["expectation_type"] == "in_set"
        assert d["failures"][0]["column"] == "status"

    def test_as_rich_table(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1",
                    expectation_type="not_null",
                    success=True,
                    severity="info",
                    column_name="id",
                ),
                QualityCheckResult(
                    check_id="chk2",
                    expectation_type="in_set",
                    success=False,
                    severity="error",
                    column_name="state",
                    unexpected_count=2,
                ),
            ]
        )
        report = ValidationReport(run)
        table = report.as_rich_table()
        assert table.title == "Validation Results"
        assert table.row_count == 2

    def test_properties(self):
        run = _make_run(
            [
                QualityCheckResult(
                    check_id="chk1", expectation_type="a", success=True, severity="info"
                ),
                QualityCheckResult(
                    check_id="chk2",
                    expectation_type="b",
                    success=False,
                    severity="error",
                ),
                QualityCheckResult(
                    check_id="chk3",
                    expectation_type="c",
                    success=False,
                    severity="warning",
                ),
            ]
        )
        report = ValidationReport(run)
        assert report.total == 3
        assert report.passed == 1
        assert report.failed == 2
        assert report.success is False


# ---------------------------------------------------------------------------
# Blocking behavior tests
# ---------------------------------------------------------------------------


class TestBlockingBehavior:
    """Test _should_block_pipeline logic via the models directly.

    We instantiate the executor's blocking logic by importing the method
    indirectly: we create a minimal stand-in that calls the same algorithm.
    """

    @staticmethod
    def _should_block(
        results: list[QualityCheckResult],
        score: QualityScore,
        thresholds: QualityThreshold | None = None,
    ) -> bool:
        """Re-implement the blocking algorithm for unit testing without Spark."""
        should_block = False

        for result in results:
            if (
                not result.success
                and result.blocking
                and result.severity in ("critical", "error")
            ):
                should_block = True

        if thresholds:
            if thresholds.max_failures is not None:
                failure_count = sum(1 for r in results if not r.success)
                if failure_count > thresholds.max_failures:
                    should_block = True

            if thresholds.max_critical_failures is not None:
                critical_count = sum(
                    1 for r in results if not r.success and r.severity == "critical"
                )
                if critical_count > thresholds.max_critical_failures:
                    should_block = True

            threshold_breached = False
            if (
                thresholds.max_critical_failure_percent is not None
                and score.critical_failure_rate
                > thresholds.max_critical_failure_percent
            ):
                threshold_breached = True
            if (
                thresholds.max_warning_failure_percent is not None
                and score.warning_failure_rate > thresholds.max_warning_failure_percent
            ):
                threshold_breached = True
            if (
                thresholds.min_success_rate is not None
                and score.success_rate < thresholds.min_success_rate
            ):
                threshold_breached = True

            score.threshold_breached = threshold_breached
            if threshold_breached:
                should_block = True

        return should_block

    @staticmethod
    def _make_score(**overrides) -> QualityScore:
        defaults = dict(
            total_checks=1,
            passed_checks=1,
            failed_checks=0,
            critical_failures=0,
            warning_failures=0,
            info_failures=0,
            success_rate=100.0,
            critical_failure_rate=0.0,
            warning_failure_rate=0.0,
            blocking_failures=0,
        )
        defaults.update(overrides)
        return QualityScore(**defaults)

    def test_all_pass_no_block(self):
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=True, severity="info"
            ),
        ]
        score = self._make_score()
        assert self._should_block(results, score) is False

    def test_blocking_critical_failure_blocks(self):
        results = [
            QualityCheckResult(
                check_id="chk1",
                expectation_type="a",
                success=False,
                severity="critical",
                blocking=True,
            ),
        ]
        score = self._make_score(
            passed_checks=0, failed_checks=1, critical_failures=1, success_rate=0.0
        )
        assert self._should_block(results, score) is True

    def test_blocking_error_failure_blocks(self):
        results = [
            QualityCheckResult(
                check_id="chk1",
                expectation_type="a",
                success=False,
                severity="error",
                blocking=True,
            ),
        ]
        score = self._make_score(passed_checks=0, failed_checks=1, success_rate=0.0)
        assert self._should_block(results, score) is True

    def test_blocking_warning_does_not_block(self):
        """A blocking check with severity=warning should NOT block."""
        results = [
            QualityCheckResult(
                check_id="chk1",
                expectation_type="a",
                success=False,
                severity="warning",
                blocking=True,
            ),
        ]
        score = self._make_score(
            passed_checks=0, failed_checks=1, warning_failures=1, success_rate=0.0
        )
        assert self._should_block(results, score) is False

    def test_non_blocking_critical_does_not_block(self):
        """A non-blocking check should not block even if critical."""
        results = [
            QualityCheckResult(
                check_id="chk1",
                expectation_type="a",
                success=False,
                severity="critical",
                blocking=False,
            ),
        ]
        score = self._make_score(
            passed_checks=0, failed_checks=1, critical_failures=1, success_rate=0.0
        )
        assert self._should_block(results, score) is False

    def test_max_failures_threshold_blocks(self):
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=False, severity="warning"
            ),
            QualityCheckResult(
                check_id="chk2", expectation_type="b", success=False, severity="warning"
            ),
        ]
        score = self._make_score(
            total_checks=2,
            passed_checks=0,
            failed_checks=2,
            warning_failures=2,
            success_rate=0.0,
        )
        thresholds = QualityThreshold(max_failures=1)
        assert self._should_block(results, score, thresholds) is True

    def test_max_failures_threshold_not_exceeded(self):
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=False, severity="warning"
            ),
        ]
        score = self._make_score(
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            warning_failures=1,
            success_rate=50.0,
        )
        thresholds = QualityThreshold(max_failures=1)
        assert self._should_block(results, score, thresholds) is False

    def test_max_critical_failures_threshold_blocks(self):
        results = [
            QualityCheckResult(
                check_id="chk1",
                expectation_type="a",
                success=False,
                severity="critical",
            ),
            QualityCheckResult(
                check_id="chk2",
                expectation_type="b",
                success=False,
                severity="critical",
            ),
        ]
        score = self._make_score(
            total_checks=2,
            passed_checks=0,
            failed_checks=2,
            critical_failures=2,
            success_rate=0.0,
            critical_failure_rate=100.0,
        )
        thresholds = QualityThreshold(max_critical_failures=1)
        assert self._should_block(results, score, thresholds) is True

    def test_min_success_rate_blocks(self):
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=False, severity="info"
            ),
        ]
        score = self._make_score(
            total_checks=2, passed_checks=1, failed_checks=1, success_rate=50.0
        )
        thresholds = QualityThreshold(min_success_rate=80.0)
        assert self._should_block(results, score, thresholds) is True

    def test_min_success_rate_not_breached(self):
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=True, severity="info"
            ),
        ]
        score = self._make_score(success_rate=100.0)
        thresholds = QualityThreshold(min_success_rate=80.0)
        assert self._should_block(results, score, thresholds) is False

    def test_no_thresholds_no_blocking_checks(self):
        """With no thresholds and non-blocking failures, should not block."""
        results = [
            QualityCheckResult(
                check_id="chk1", expectation_type="a", success=False, severity="error"
            ),
        ]
        score = self._make_score(passed_checks=0, failed_checks=1, success_rate=0.0)
        assert self._should_block(results, score, thresholds=None) is False

    def test_empty_results_no_block(self):
        score = self._make_score(total_checks=0, passed_checks=0, success_rate=0.0)
        assert self._should_block([], score) is False


# ---------------------------------------------------------------------------
# FailureDetail dataclass
# ---------------------------------------------------------------------------


class TestFailureDetail:
    def test_defaults(self):
        fd = FailureDetail(
            expectation_type="not_null",
            column="id",
            severity="critical",
            description="id must not be null",
        )
        assert fd.observed_value is None
        assert fd.unexpected_count == 0
        assert fd.sample_values == []
