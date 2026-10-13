"""Apply LLM-generated validation responses to UMF."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tablespec.models.umf import (
    Expectation,
    INGESTED_QUALITY_CHECK_TYPES,
    RAW_VALIDATION_TYPES,
    UMF,
    classify_validation_type,
)
from tablespec.expectation_migration import migrate_to_expectation_suite


@dataclass
class ApplyResult:
    """Result of applying LLM-generated expectations."""

    added: list[dict[str, Any]] = field(default_factory=list)
    deduplicated: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_umf: UMF | None = None


def apply_validation_response(
    umf: UMF,
    response: list[dict[str, Any]],
) -> ApplyResult:
    """Merge LLM-generated expectations into UMF.

    Steps:
    1. Parse each expectation from the response
    2. Validate: check type is a known GX expectation type
    3. Classify: auto-assign stage (raw/ingested) via classify_validation_type()
    4. Tag: set meta.generated_from = "llm"
    5. Deduplicate: skip if same type+column already exists in UMF
    6. Return structured result
    """
    known_types = RAW_VALIDATION_TYPES | INGESTED_QUALITY_CHECK_TYPES
    result = ApplyResult()
    new_expectations: list[Expectation] = []

    # Get existing expectations for dedup
    existing_signatures: set[str] = set()
    suite = (
        umf.expectations.model_copy(deep=True)
        if umf.expectations is not None
        else migrate_to_expectation_suite(umf.model_dump(exclude_none=True))
    )
    for exp in suite.expectations:
        sig = _expectation_signature(exp)
        existing_signatures.add(sig)

    for exp in suite.pending:
        sig = _expectation_signature(exp)
        existing_signatures.add(sig)

    for exp_dict in response:
        exp_type = exp_dict.get("type", exp_dict.get("expectation_type", ""))

        # Validate type
        if not exp_type:
            result.invalid.append((exp_dict, "Missing expectation type"))
            continue

        if exp_type not in known_types:
            result.invalid.append((exp_dict, f"Unknown expectation type '{exp_type}'"))
            continue

        # Classify stage
        stage = classify_validation_type(exp_type)

        # Tag
        meta = exp_dict.get("meta", {})
        meta["generated_from"] = "llm"
        meta["validation_stage"] = stage
        exp_dict["meta"] = meta

        # Dedup
        sig = _expectation_signature(exp_dict)
        if sig in existing_signatures:
            result.deduplicated.append(exp_dict)
            continue

        result.added.append(exp_dict)
        new_expectations.append(Expectation.from_gx_dict(exp_dict))
        existing_signatures.add(sig)

    if new_expectations:
        result.updated_umf = umf.model_copy(
            update={
                "expectations": suite.model_copy(
                    update={"expectations": [*suite.expectations, *new_expectations]}
                ),
                "validation_rules": None,
                "quality_checks": None,
            }
        )

    return result


def _expectation_signature(exp: dict[str, Any] | Any) -> str:
    """Create a dedup signature from expectation type + column."""
    if isinstance(exp, dict):
        exp_type = exp.get("type", exp.get("expectation_type", ""))
        column = exp.get("kwargs", {}).get("column", "")
    else:
        exp_type = getattr(exp, "type", "")
        column = getattr(exp, "kwargs", {}).get("column", "")
    return f"{exp_type}:{column}"
