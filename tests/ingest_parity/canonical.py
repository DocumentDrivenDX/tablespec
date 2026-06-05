"""Deterministic canonicalization of an ingested table for cross-engine parity.

The same canonical form is used by the Spark baseline (Phase 1) and the later dbt
parity check (Phase 2+). Two engines "match" iff these canonical forms are
byte-identical.

Canonical rules (per the agreed CONTEXT + the Phase-1 conformance acceptance
contract in ``docs/helix/03-test/conformance-acceptance.md`` Section 3):
  * rows are sorted by ALL columns (stable, NULLs sort last within a column)
  * each value is rendered as a stable string:
      - NULL                      -> the literal string ``NULL``
      - timestamp/datetime        -> ``YYYY-MM-DD HH:MM:SS`` when ``ts_precision``
        is 0, else ``YYYY-MM-DD HH:MM:SS.ffffff`` truncated (NOT rounded) to
        ``ts_precision`` fractional digits. Default precision is microsecond (6)
        so sub-second divergence is visible by default. TZ-aware values are
        normalized to UTC and rendered with a trailing ``Z``; naive values get NO
        suffix (so a tz-aware<->naive divergence can never silently match).
      - date                      -> ``YYYY-MM-DD``
      - decimal                   -> fixed at its declared scale
      - boolean                   -> ``true`` / ``false``
      - everything else           -> ``str(value)``
  * the column order is the UMF column order (the typed target schema)
  * the result is serialized to deterministic JSON (and CSV) so byte comparison
    is meaningful.

Timestamp precision contract (Section 3 of the acceptance doc):
  * ``to_json(..., ts_precision=6)`` threads the precision through to
    ``render_value(value, *, ts_precision=6)``.
  * The default is **microsecond (6)** so sub-second divergence between engines is
    visible by default. The existing second-resolution ingest corpus pins
    ``ts_precision=0`` explicitly at its call sites (preserving the committed
    goldens byte-for-byte); only the new sub-second / tz cases use the microsecond
    default. Every engine leg MUST canonicalize a given case at the SAME precision.
"""

from __future__ import annotations

import datetime as _dt
import json
from decimal import Decimal
from typing import Any

NULL_TOKEN = "NULL"

#: Default timestamp fractional precision (microseconds). Sub-second divergence is
#: visible by default; the second-resolution ingest corpus opts down to 0.
DEFAULT_TS_PRECISION = 6


def _render_datetime(value: _dt.datetime, *, ts_precision: int) -> str:
    """Render a ``datetime`` with explicit TZ + truncated fractional seconds.

    * A tz-aware value is normalized to UTC and rendered with a trailing ``Z``.
    * A naive value renders with NO suffix.
    The two are therefore NEVER byte-equal, so a tz-aware<->naive divergence
    cannot silently pass.

    Fractional seconds are TRUNCATED (not rounded) to ``ts_precision`` digits.
    ``ts_precision == 0`` renders no fractional part (second resolution).
    """
    suffix = ""
    if value.tzinfo is not None:
        value = value.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        suffix = "Z"
    base = value.strftime("%Y-%m-%d %H:%M:%S")
    if ts_precision <= 0:
        return base + suffix
    # ``microsecond`` is 0..999999; left-pad to 6 digits then TRUNCATE to width.
    micros = f"{value.microsecond:06d}"
    frac = micros[:ts_precision]
    return f"{base}.{frac}{suffix}"


def render_value(
    value: Any,
    *,
    scale: int | None = None,
    ts_precision: int = DEFAULT_TS_PRECISION,
) -> str:
    """Render a single Python value to its stable canonical string.

    Args:
        value: the Python value to render.
        scale: optional fixed decimal scale for DECIMAL/float rendering.
        ts_precision: fractional-second digits for datetimes (0 == second
            resolution; default 6 == microsecond). Truncated, not rounded.
    """
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        return _render_datetime(value, ts_precision=ts_precision)
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
    *,
    ts_precision: int = DEFAULT_TS_PRECISION,
) -> list[list[str]]:
    """Return rows as a sorted list of lists of canonical strings.

    Args:
        rows: list of {column_name: python_value} mappings.
        columns: ordered column names (defines output column order).
        scales: optional {column_name: decimal_scale} for fixed-scale rendering.
        ts_precision: fractional-second digits for datetimes (see ``render_value``).
    """
    scales = scales or {}
    rendered: list[list[str]] = []
    for row in rows:
        rendered.append(
            [
                render_value(row.get(c), scale=scales.get(c), ts_precision=ts_precision)
                for c in columns
            ]
        )
    # Sort by all columns (lexicographic over the canonical strings -> deterministic).
    rendered.sort()
    return rendered


def to_json(
    rows: list[dict[str, Any]],
    columns: list[str],
    scales: dict[str, int | None] | None = None,
    *,
    ts_precision: int = DEFAULT_TS_PRECISION,
) -> str:
    """Serialize canonical rows to deterministic JSON text.

    Args:
        rows: list of {column_name: python_value} mappings.
        columns: ordered column names (defines output column order).
        scales: optional {column_name: decimal_scale} for fixed-scale rendering.
        ts_precision: fractional-second digits for datetimes. The default is
            microsecond (6); the second-resolution ingest corpus passes 0 at its
            call sites to keep the committed goldens byte-for-byte.
    """
    payload = {
        "columns": columns,
        "rows": canonical_rows(rows, columns, scales, ts_precision=ts_precision),
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=True) + "\n"
