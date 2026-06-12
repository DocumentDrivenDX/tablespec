"""Adapters from staged validation execution into validation reports."""

from __future__ import annotations

import uuid
from typing import Any

from tablespec.models.quality import QualityCheckResult, QualityCheckRun

from .gx_executor import StagedExecutionResult
from .report import ValidationReport


def build_validation_report_from_staged_execution(
    table_name: str,
    staged: StagedExecutionResult,
    expectations: list[dict[str, Any]],
    *,
    pipeline_name: str = "staged_validation",
    run_id: str | None = None,
) -> ValidationReport:
    """Convert staged execution results into a ``ValidationReport``.

    The adapter reattaches expectation metadata from the composed expectation
    list so downstream reporting keeps severity and description on the shipped
    ``QualityCheckResult`` model.
    """

    meta_by_key: dict[tuple[str, str | None], dict[str, Any]] = {}
    for exp in expectations:
        key = (exp.get("type", ""), exp.get("kwargs", {}).get("column"))
        meta_by_key.setdefault(key, exp.get("meta", {}))

    results: list[QualityCheckResult] = []
    for stage, suite in (("raw", staged.raw), ("ingested", staged.ingested)):
        for result in suite.results:
            meta = meta_by_key.get((result.expectation_type, result.column), {})
            results.append(
                QualityCheckResult(
                    check_id=f"{stage}:{result.expectation_type}:{result.column or '-'}",
                    expectation_type=result.expectation_type,
                    success=result.success,
                    severity=meta.get("severity", "critical"),
                    column_name=result.column,
                    description=meta.get("description"),
                    unexpected_count=result.unexpected_count,
                    observed_value=result.observed_value,
                    details=result.details,
                    tags=[stage],
                )
            )

    run = QualityCheckRun(
        pipeline_name=pipeline_name,
        table_name=table_name,
        run_id=run_id or uuid.uuid4().hex[:8],
        results=results,
        should_block=any(not result.success for result in results),
    )
    return ValidationReport(run)
