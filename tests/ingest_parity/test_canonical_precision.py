"""Unit tests for the extended canonicalization contract (Phase 2).

These assert the configurable-timestamp-precision + explicit-timezone behavior of
``canonical.render_value`` / ``to_json`` directly (no engine required), so the
contract in docs/helix/03-test/conformance-acceptance.md Section 3 is verified
even though the ingest cast registry has no tz-offset format to drive it through a
real engine. Marked fast / no_spark.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from .canonical import DEFAULT_TS_PRECISION, render_value, to_json

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_default_precision_is_microsecond() -> None:
    assert DEFAULT_TS_PRECISION == 6


def test_naive_datetime_renders_microseconds_no_suffix() -> None:
    v = dt.datetime(2026, 6, 3, 12, 30, 45, 123456)
    assert render_value(v) == "2026-06-03 12:30:45.123456"


def test_naive_whole_second_carries_fractional_zeros_at_micro() -> None:
    v = dt.datetime(2026, 6, 3, 12, 30, 45)
    assert render_value(v) == "2026-06-03 12:30:45.000000"


def test_second_resolution_drops_fraction() -> None:
    v = dt.datetime(2026, 6, 3, 12, 30, 45, 123456)
    assert render_value(v, ts_precision=0) == "2026-06-03 12:30:45"


def test_fraction_is_truncated_not_rounded() -> None:
    # .123456 truncated to 3 digits is .123 (NOT rounded to .123 -> .123; pick a
    # value where rounding would differ: .123999 -> trunc .123, round would be .124)
    v = dt.datetime(2026, 6, 3, 12, 30, 45, 123999)
    assert render_value(v, ts_precision=3) == "2026-06-03 12:30:45.123"


def test_tz_aware_normalizes_to_utc_with_z_suffix() -> None:
    # 12:30:45 at -05:00 == 17:30:45 UTC, rendered with a trailing Z.
    tz = dt.timezone(dt.timedelta(hours=-5))
    v = dt.datetime(2026, 6, 3, 12, 30, 45, 500000, tzinfo=tz)
    assert render_value(v) == "2026-06-03 17:30:45.500000Z"


def test_tz_aware_utc_renders_z() -> None:
    v = dt.datetime(2026, 6, 3, 12, 30, 45, tzinfo=dt.timezone.utc)
    assert render_value(v) == "2026-06-03 12:30:45.000000Z"


def test_tz_aware_and_naive_same_walltime_never_byte_equal() -> None:
    """A tz-aware and a naive value at the same UTC wall-clock must NOT match.

    This is the divergence-visibility guarantee: an engine that drops tz info (or
    adds it) produces a byte-different canonical string and cannot silently pass.
    """
    naive = dt.datetime(2026, 6, 3, 12, 30, 45)
    aware = dt.datetime(2026, 6, 3, 12, 30, 45, tzinfo=dt.timezone.utc)
    assert render_value(naive) != render_value(aware)
    assert render_value(naive) == "2026-06-03 12:30:45.000000"
    assert render_value(aware) == "2026-06-03 12:30:45.000000Z"


def test_to_json_threads_precision() -> None:
    rows = [{"ts": dt.datetime(2026, 1, 1, 0, 0, 0, 250000)}]
    sec = to_json(rows, ["ts"], ts_precision=0)
    micro = to_json(rows, ["ts"], ts_precision=6)
    assert '"2026-01-01 00:00:00"' in sec
    assert '"2026-01-01 00:00:00.250000"' in micro
    assert sec != micro


def test_decimal_and_bool_unaffected_by_precision() -> None:
    assert render_value(Decimal("1.5"), scale=2, ts_precision=6) == "1.50"
    assert render_value(True, ts_precision=6) == "true"
    assert render_value(None, ts_precision=6) == "NULL"
