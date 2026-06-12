"""Helpers for reading unified and legacy UMF expectations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tablespec.core.expectation_facts import expectation_dicts_from_umf_data

if TYPE_CHECKING:
    from tablespec.models.umf import UMF

__all__ = ["expectation_dicts_from_umf", "expectation_dicts_from_umf_data"]


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
