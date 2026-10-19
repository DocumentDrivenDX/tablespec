# SPDX-License-Identifier: MIT OR Apache-2.0
"""Migration logic for converting legacy validation_rules + quality_checks to ExpectationSuite."""

import warnings
from typing import Any

from tablespec.models.umf import (
    Expectation,
    ExpectationMeta,
    ExpectationSuite,
    classify_validation_type,
)


def migrate_to_expectation_suite(umf_data: dict[str, Any]) -> ExpectationSuite:
    """Convert legacy validation_rules + quality_checks to unified ExpectationSuite.

    Rules:
    - validation_rules.expectations -> stage auto-classified via classify_validation_type()
    - quality_checks.checks -> stage="ingested" (but corrected if misclassified)
    - Severity from meta dict (validation_rules) or top-level field (quality_checks)
    - Blocking defaults to False for migrated validation_rules
    - Unknown types get stage="unknown" with warning
    - Column-level validations already merged into expectations by loader

    Args:
        umf_data: Raw UMF data dict containing validation_rules and/or quality_checks

    Returns:
        Unified ExpectationSuite with all expectations classified by stage

    """
    expectations: list[Expectation] = []
    pending: list[Expectation] = []

    # Migrate validation_rules
    vr = umf_data.get("validation_rules") or {}
    for exp_dict in vr.get("expectations", []):
        exp = _migrate_expectation(exp_dict, default_stage="raw")
        expectations.append(exp)

    for exp_dict in vr.get("pending_expectations", []):
        exp = _migrate_expectation(exp_dict, default_stage="raw")
        pending.append(exp)

    # Migrate quality_checks
    qc = umf_data.get("quality_checks") or {}
    for check in qc.get("checks", []):
        exp_dict = check.get("expectation", {})
        # Quality checks have top-level severity and blocking
        meta_overrides = {
            "severity": check.get("severity", "warning"),
            "blocking": check.get("blocking", False),
            "description": check.get("description"),
            "tags": check.get("tags", []),
        }
        exp = _migrate_expectation(
            exp_dict, default_stage="ingested", meta_overrides=meta_overrides
        )
        expectations.append(exp)

    return ExpectationSuite(
        expectations=expectations,
        thresholds=qc.get("thresholds"),
        alert_config=qc.get("alert_config"),
        pending=pending,
    )


def ensure_expectation_suite_data(umf_data: dict[str, Any]) -> dict[str, Any]:
    """Return unified expectation-suite data, migrating legacy fields when needed."""
    suite = umf_data.get("expectations")
    if isinstance(suite, dict):
        return suite
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return migrate_to_expectation_suite(umf_data).model_dump(exclude_none=True)


def _migrate_expectation(
    exp_dict: dict[str, Any],
    default_stage: str = "raw",
    meta_overrides: dict[str, Any] | None = None,
) -> Expectation:
    """Migrate a single expectation dict to Expectation model.

    Args:
        exp_dict: Raw expectation dict (type + kwargs + optional meta)
        default_stage: Default stage if type cannot be classified
        meta_overrides: Overrides from quality_checks top-level fields

    Returns:
        Unified Expectation model instance

    """
    exp_type = exp_dict.get("type", exp_dict.get("expectation_type", ""))
    raw_meta = exp_dict.get("meta", {})

    # Auto-classify stage
    classified = classify_validation_type(exp_type)
    if classified == "unknown":
        # Check if meta has a stage hint
        stage = raw_meta.get("validation_stage", default_stage)
        if stage == default_stage and exp_type:
            warnings.warn(
                f"Unknown expectation type '{exp_type}' — defaulting to stage='{default_stage}'. "
                f"Explicitly set validation_stage in meta to suppress this warning.",
                UserWarning,
                stacklevel=3,
            )
    else:
        stage = classified
        # Warn if misclassified (e.g., raw type in quality_checks)
        if default_stage == "ingested" and classified == "raw":
            warnings.warn(
                f"Expectation type '{exp_type}' is a raw-stage type but was in quality_checks. "
                f"Reclassified to stage='raw'.",
                UserWarning,
                stacklevel=3,
            )

    # Build meta
    severity = raw_meta.get("severity", "warning")
    if meta_overrides:
        severity = meta_overrides.get("severity", severity)

    meta = ExpectationMeta(
        stage=stage,
        severity=severity,
        blocking=meta_overrides.get("blocking", False)
        if meta_overrides
        else raw_meta.get("blocking", False),
        description=meta_overrides.get("description")
        if meta_overrides
        else raw_meta.get("description"),
        tags=meta_overrides.get("tags", [])
        if meta_overrides
        else raw_meta.get("tags", []),
        generated_from=raw_meta.get("generated_from"),
    )

    return Expectation(
        type=exp_type,
        kwargs=exp_dict.get("kwargs", {}),
        meta=meta,
    )
