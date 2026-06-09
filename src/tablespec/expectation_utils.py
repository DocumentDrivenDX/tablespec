"""Helpers for reading unified and legacy UMF expectations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tablespec.models.umf import UMF


def expectation_dicts_from_umf(umf: UMF) -> list[dict[str, Any]]:
    """Return GX-style expectation dicts, preferring ``UMF.expectations``."""
    if umf.expectations and umf.expectations.expectations:
        return [
            expectation.to_gx_dict() for expectation in umf.expectations.expectations
        ]
    legacy = getattr(umf, "validation_rules", None)
    if isinstance(legacy, dict):
        return list(legacy.get("expectations", []) or [])
    if legacy and getattr(legacy, "expectations", None):
        return list(legacy.expectations)
    return []


def expectation_dicts_from_umf_data(umf_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return GX-style expectation dicts from dict UMF data.

    The unified suite is authoritative. Legacy ``validation_rules`` are retained
    only as a compatibility fallback for older UMF payloads.
    """
    suite = umf_data.get("expectations") or {}
    expectations = [
        expectation
        for expectation in suite.get("expectations") or []
        if isinstance(expectation, dict)
    ]
    if expectations:
        return expectations

    legacy = (umf_data.get("validation_rules") or {}).get("expectations") or []
    return [expectation for expectation in legacy if isinstance(expectation, dict)]
