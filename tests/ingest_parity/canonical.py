"""Deterministic canonicalization of an ingested table for cross-engine parity.

The same canonical form is used by the Spark baseline (Phase 1) and the later dbt
parity check (Phase 2+). Two engines "match" iff these canonical forms are
byte-identical.

Canonical rules (per the agreed CONTEXT):
  * rows are sorted by ALL columns (stable, NULLs sort last within a column)
  * each value is rendered as a stable string:
      - NULL                      -> the literal string ``NULL``
      - timestamp/datetime        -> ISO ``YYYY-MM-DD HH:MM:SS``
      - date                      -> ``YYYY-MM-DD``
      - decimal                   -> fixed at its declared scale
      - boolean                   -> ``true`` / ``false``
      - everything else           -> ``str(value)``
  * the column order is the UMF column order (the typed target schema)
  * the result is serialized to deterministic JSON (and CSV) so byte comparison
    is meaningful.
"""

from __future__ import annotations

import datetime as _dt
import json
from decimal import Decimal
from typing import Any

NULL_TOKEN = "NULL"


def render_value(value: Any, *, scale: int | None = None) -> str:
    """Render a single Python value to its stable canonical string."""
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        if scale is not None:
            return f"{value:.{scale}f}"
        return format(value, "f")
    if isinstance(value, float):
        if scale is not None:
            return f"{value:.{scale}f}"
        # Stable float repr: drop a trailing ``.0`` only for whole numbers is
        # avoided -- repr is deterministic across runs of the same engine.
        return repr(value)
    return str(value)


def canonical_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
    scales: dict[str, int | None] | None = None,
) -> list[list[str]]:
    """Return rows as a sorted list of lists of canonical strings.

    Args:
        rows: list of {column_name: python_value} mappings.
        columns: ordered column names (defines output column order).
        scales: optional {column_name: decimal_scale} for fixed-scale rendering.
    """
    scales = scales or {}
    rendered: list[list[str]] = []
    for row in rows:
        rendered.append(
            [render_value(row.get(c), scale=scales.get(c)) for c in columns]
        )
    # Sort by all columns (lexicographic over the canonical strings -> deterministic).
    rendered.sort()
    return rendered


def to_json(
    rows: list[dict[str, Any]],
    columns: list[str],
    scales: dict[str, int | None] | None = None,
) -> str:
    """Serialize canonical rows to deterministic JSON text."""
    payload = {
        "columns": columns,
        "rows": canonical_rows(rows, columns, scales),
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=True) + "\n"
