"""Behavioral execution of the DuckDB cast SQL emitted by ``cast_column_sql``.

These run the *generated* DuckDB expression against a live DuckDB connection (no
JVM, no Spark) and assert the NULL-on-failure cast contract every dialect must
honour: currency strip, empty/whitespace -> NULL, unparseable -> NULL, and a
correctly-parsed happy path for each cast type. This is the duckdb-side companion
to the Spark baseline -- it proves the emitted SQL actually behaves, not just that
the string is shaped right.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb required for cast exec tests")

from tablespec.casting_utils import cast_column_sql  # noqa: E402

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _eval(expr: str, value, *, tz: bool = False):
    """Run ``SELECT {expr}`` over a one-row table holding *value* as VARCHAR."""
    con = duckdb.connect()
    try:
        if tz:
            con.execute("SET TimeZone='UTC'")
        con.execute("CREATE TEMP TABLE t(v VARCHAR)")
        con.execute("INSERT INTO t VALUES (?)", [value])
        (result,) = con.execute(f"SELECT {expr} FROM t").fetchone()
    finally:
        con.close()
    return result


# ---------------------------------------------------------------------------
# Numerics: currency strip, empty -> NULL, unparseable -> NULL
# ---------------------------------------------------------------------------


def test_integer_happy_path():
    expr = cast_column_sql("v", "INTEGER", dialect="duckdb")
    assert _eval(expr, "42") == 42


def test_integer_currency_stripped():
    expr = cast_column_sql("v", "INTEGER", dialect="duckdb")
    # leading '$' is stripped before the cast
    assert _eval(expr, "$100") == 100


def test_integer_empty_string_is_null():
    expr = cast_column_sql("v", "INTEGER", dialect="duckdb")
    assert _eval(expr, "") is None
    assert _eval(expr, "   ") is None  # whitespace-only -> NULL


def test_integer_unparseable_is_null():
    expr = cast_column_sql("v", "INTEGER", dialect="duckdb")
    assert _eval(expr, "not_a_number") is None


def test_decimal_scale_preserved():
    expr = cast_column_sql("v", "DECIMAL", precision=14, scale=3, dialect="duckdb")
    result = _eval(expr, "$1234.500")
    assert result == Decimal("1234.500")


def test_double_unparseable_is_null():
    expr = cast_column_sql("v", "DOUBLE", dialect="duckdb")
    assert _eval(expr, "abc") is None
    assert _eval(expr, "3.14") == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# Booleans
# ---------------------------------------------------------------------------


def test_boolean_happy_and_null():
    expr = cast_column_sql("v", "BOOLEAN", dialect="duckdb")
    assert _eval(expr, "true") is True
    assert _eval(expr, "false") is False
    assert _eval(expr, "maybe") is None  # unparseable -> NULL, not an abort


# ---------------------------------------------------------------------------
# Dates / timestamps: format parse, padding strictness, unparseable -> NULL
# ---------------------------------------------------------------------------


def test_date_with_format_parses():
    expr = cast_column_sql("v", "DATE", "MM/DD/YYYY", dialect="duckdb")
    assert _eval(expr, "06/03/2026") == _dt.date(2026, 6, 3)


def test_date_unpadded_input_nulls_under_padded_format():
    """The padding pre-filter NULLs '6/3/2026' under MM/DD/YYYY (Spark parity)."""
    expr = cast_column_sql("v", "DATE", "MM/DD/YYYY", dialect="duckdb")
    assert _eval(expr, "6/3/2026") is None


def test_date_unparseable_is_null():
    expr = cast_column_sql("v", "DATE", "YYYY-MM-DD", dialect="duckdb")
    assert _eval(expr, "garbage") is None


def test_date_no_format_parses_iso():
    expr = cast_column_sql("v", "DATE", dialect="duckdb")
    assert _eval(expr, "2026-06-03") == _dt.date(2026, 6, 3)


def test_timestamp_with_format_parses():
    expr = cast_column_sql("v", "TIMESTAMP", "YYYY-MM-DD HH:MM:SS", dialect="duckdb")
    assert _eval(expr, "2026-06-03 12:30:45", tz=True) == _dt.datetime(
        2026, 6, 3, 12, 30, 45
    )


def test_string_passthrough_executes():
    expr = cast_column_sql("v", "VARCHAR", dialect="duckdb")
    assert _eval(expr, "hello") == "hello"


@pytest.mark.parametrize(
    ("umf_format", "good", "parsed"),
    [
        ("YYYY-MM-DD", "2026-01-31", _dt.date(2026, 1, 31)),
        ("YYYYMMDD", "20260131", _dt.date(2026, 1, 31)),
        ("MM-DD-YYYY", "01-31-2026", _dt.date(2026, 1, 31)),
        ("YYYY/MM/DD", "2026/01/31", _dt.date(2026, 1, 31)),
        ("MMDDYYYY", "01312026", _dt.date(2026, 1, 31)),
    ],
)
def test_date_format_matrix(umf_format, good, parsed):
    expr = cast_column_sql("v", "DATE", umf_format, dialect="duckdb")
    assert _eval(expr, good) == parsed


def test_timestamp_12_hour_am_pm_executes():
    expr = cast_column_sql("v", "TIMESTAMP", "MM/DD/YYYY hh:mm:ss A", dialect="duckdb")
    assert _eval(expr, "01/31/2026 01:30:45 PM", tz=True) == _dt.datetime(
        2026, 1, 31, 13, 30, 45
    )


def test_timestamp_fractional_seconds_executes():
    expr = cast_column_sql(
        "v", "TIMESTAMP", "YYYY-MM-DD HH:MM:SS.SSSSSS", dialect="duckdb"
    )
    result = _eval(expr, "2026-01-31 12:30:45.123456", tz=True)
    assert result == _dt.datetime(2026, 1, 31, 12, 30, 45, 123456)


def test_datetime_type_executes_like_timestamp():
    """UMF DATETIME maps to TIMESTAMP (no date truncation) and executes."""
    expr = cast_column_sql("v", "DATETIME", "YYYY-MM-DD HH:MM:SS", dialect="duckdb")
    assert _eval(expr, "2026-01-31 08:15:00", tz=True) == _dt.datetime(
        2026, 1, 31, 8, 15, 0
    )


def test_timestamp_no_format_executes_and_nulls_garbage():
    expr = cast_column_sql("v", "TIMESTAMP", dialect="duckdb")
    assert _eval(expr, "2026-01-31 08:15:00", tz=True) == _dt.datetime(
        2026, 1, 31, 8, 15, 0
    )
    assert _eval(expr, "not-a-ts") is None


def test_decimal_unparseable_is_null():
    expr = cast_column_sql("v", "DECIMAL", precision=10, scale=2, dialect="duckdb")
    assert _eval(expr, "xyz") is None
    assert _eval(expr, "") is None


def test_boolean_numeric_and_textual_variants():
    expr = cast_column_sql("v", "BOOLEAN", dialect="duckdb")
    # DuckDB accepts textual true/false (and case variants); unparseable -> NULL
    assert _eval(expr, "TRUE") is True
    assert _eval(expr, "False") is False
    assert _eval(expr, "2") is None


def test_unsupported_format_raises_before_execution():
    """An off-registry format is rejected at SQL-build time (no silent divergence)."""
    with pytest.raises(ValueError, match="cross-engine ingest"):
        cast_column_sql("v", "DATE", "DD.MM.YYYY", dialect="duckdb")
