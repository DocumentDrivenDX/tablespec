# SPDX-License-Identifier: MIT OR Apache-2.0
"""Quality check execution models.

Dataclasses for quality check results, scores, thresholds, and run summaries.
Used by QualityCheckExecutor and QualityResultsWriter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class QualityCheckResult:
    """Result of a single quality check execution."""

    check_id: str
    expectation_type: str
    success: bool
    severity: str  # "critical", "error", "warning", "info"
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
    """Aggregate quality metrics from a set of check results."""

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
    """Configurable thresholds for quality gate decisions."""

    max_critical_failure_percent: float | None = None
    max_warning_failure_percent: float | None = None
    min_success_rate: float | None = None
    max_failures: int | None = None
    max_critical_failures: int | None = None


@dataclass
class QualityCheckRun:
    """Complete quality check run with results, scores, and blocking decision."""

    pipeline_name: str
    table_name: str
    run_id: str
    results: list[QualityCheckResult]
    should_block: bool = False
    run_timestamp: datetime = field(default_factory=datetime.now)
    score: QualityScore | None = None
    thresholds: QualityThreshold | None = None
    error_message: str | None = None
    since_timestamp: datetime | None = None
    incremental_mode: bool = False
    total_source_records: int = 0
    validated_records: int = 0
