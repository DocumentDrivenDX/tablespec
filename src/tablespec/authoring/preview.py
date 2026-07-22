"""Preview validation expectations for a UMF table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tablespec.expectation_migration import ensure_expectation_suite_data
from tablespec.models.umf import classify_validation_type, REDUNDANT_VALIDATION_TYPES


@dataclass
class ExpectationPreview:
    """A single expectation with classification info."""

    type: str
    column: str | None
    stage: str  # "raw", "ingested", "redundant", "unknown"
    severity: str
    generated_from: str | None
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreviewResult:
    """Classified expectation suite for display."""

    raw: list[ExpectationPreview] = field(default_factory=list)
    ingested: list[ExpectationPreview] = field(default_factory=list)
    redundant: list[ExpectationPreview] = field(default_factory=list)
    unknown: list[ExpectationPreview] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.raw) + len(self.ingested) + len(self.redundant) + len(self.unknown)
        )


def generate_preview(umf_data: dict[str, Any]) -> PreviewResult:
    """Classify all expectations in a UMF by stage.

    Prefers the unified expectations suite and falls back to legacy fields.
    """
    result = PreviewResult()
    suite_data = ensure_expectation_suite_data(umf_data)

    for exp in suite_data.get("expectations", []):
        preview = _classify_expectation(exp)
        _route(result, preview)

    for exp in suite_data.get("pending", []):
        preview = _classify_expectation(exp)
        _route(result, preview)

    return result


def _classify_expectation(exp: dict[str, Any]) -> ExpectationPreview:
    exp_type = exp.get("type", exp.get("expectation_type", ""))
    meta = exp.get("meta", {})

    if exp_type in REDUNDANT_VALIDATION_TYPES:
        stage = "redundant"
    else:
        stage = classify_validation_type(exp_type)
        if stage == "unknown":
            stage = meta.get("validation_stage", "unknown")

    return ExpectationPreview(
        type=exp_type,
        column=exp.get("kwargs", {}).get("column"),
        stage=stage,
        severity=meta.get("severity", "warning"),
        generated_from=meta.get("generated_from"),
        kwargs=exp.get("kwargs", {}),
    )


def _route(result: PreviewResult, preview: ExpectationPreview) -> None:
    if preview.stage == "raw":
        result.raw.append(preview)
    elif preview.stage == "ingested":
        result.ingested.append(preview)
    elif preview.stage == "redundant":
        result.redundant.append(preview)
    else:
        result.unknown.append(preview)
