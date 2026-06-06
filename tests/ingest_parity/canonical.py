"""Re-export shim: the canonicalizer now lives in ``tablespec.canonical``.

The deterministic cross-engine canonicalizer MOVED into the shipped package
(``src/tablespec/canonical.py``) so the runtime backbone can depend on it without
importing the test tree (a wheel ships no ``tests/``). This module re-exports the
public names so every existing ``from tests.ingest_parity.canonical import X``
keeps working unchanged; the canonical byte output is identical.
"""

from __future__ import annotations

from tablespec.canonical import (
    DEFAULT_TS_PRECISION,
    NULL_TOKEN,
    canonical_rows,
    render_value,
    to_json,
)

__all__ = [
    "DEFAULT_TS_PRECISION",
    "NULL_TOKEN",
    "canonical_rows",
    "render_value",
    "to_json",
]
