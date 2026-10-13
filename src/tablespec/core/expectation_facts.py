"""Core helpers for reading expectation facts from dict UMF payloads.

This stays inside ``tablespec.core`` so backends can consume expectation facts
without reaching into the top-level ``tablespec.expectation_utils`` module.
"""

from __future__ import annotations

from typing import Any


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
