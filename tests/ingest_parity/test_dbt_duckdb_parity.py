"""Phase 2 dbt(+DuckDB) parity check against the Spark baseline.

For each committed fixture under ``tests/fixtures/ingest/`` this test:

  1. loads the UMF spec and the raw all-STRING CSV batch(es),
  2. generates a dbt(+DuckDB) project with ``generate_dbt_project(umf)``,
  3. for each batch: (re)creates the ``raw_<table>`` landing table in DuckDB from
     the CSV, then runs ``dbt run`` so dbt owns the write
     (merge / append / table-rebuild per the model config),
  4. canonicalizes the resulting ``<table>`` model output (see ``canonical.py``), and
  5. asserts it is BYTE-IDENTICAL to the committed Spark golden under
     ``tests/golden/ingest_parity/<fixture>.spark.expected.json``.

The Spark baseline (``test_spark_baseline.py``) is the source of truth; this test
proves the dbt/duckdb path reproduces it exactly. Two-batch fixtures exercise the
dedup-latest window on the MERGE batch (incremental+pk) and the blind-append
accumulation (keyless incremental), matching the baseline.

Run with::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      uv run pytest tests/ingest_parity/test_dbt_duckdb_parity.py
"""

from __future__ import annotations

import pytest

# dbt(+duckdb) parity: reproduces the Spark baseline goldens WITHOUT a JVM.
# Marked no_spark so the JVM-free lane can run it (skips if the dbt CLI is absent).
pytestmark = [pytest.mark.no_spark]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for dbt parity")
pytest.importorskip("dbt", reason="dbt-core required for dbt parity")

from tests.conformance.corpus.registry import Case, ingest_cases  # noqa: E402
from tests.conformance.engines import DbtDuckDBEngine  # noqa: E402

_ENGINE = DbtDuckDBEngine()
_INGEST_CASES = ingest_cases()


@pytest.mark.slow
@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_dbt_duckdb_parity(case: Case) -> None:
    reason = _ENGINE.availability(case)
    if reason is not None:
        pytest.skip(reason)

    assert case.golden is not None
    actual = _ENGINE.run(case)

    golden = case.golden
    assert golden.exists(), f"Spark golden missing for '{case.id}': {golden}"
    expected = golden.read_text()
    assert actual == expected, (
        f"dbt/duckdb parity mismatch for '{case.id}' (must match the Spark golden).\n"
        f"--- expected (spark golden) ---\n{expected}\n--- actual (dbt/duckdb) ---\n{actual}"
    )


# Sub-second cross-engine parity for the fractional-second registry additions.
# The shared canonical form renders timestamps at SECOND resolution (per the agreed
# CONTEXT), so the .SSSSSS / .SSS goldens above only prove the formats PARSE and
# agree to the second. These constants are the EXACT microsecond values Spark's
# try_to_timestamp produces for the same inputs+formats (independently verified on
# the Spark-compatible JDK during Phase 3); this test asserts the emitted DuckDB
# cast SQL reproduces them micro-for-micro, closing the must-fix B gap below the
# canonical granularity.
_FRACTIONAL_MICRO_PARITY: list[tuple[str, str, str]] = [
    (
        "2026-06-03 12:30:45.123456",
        "YYYY-MM-DD HH:MM:SS.SSSSSS",
        "2026-06-03 12:30:45.123456",
    ),
    (
        "2026-12-31 23:59:59.000001",
        "YYYY-MM-DD HH:MM:SS.SSSSSS",
        "2026-12-31 23:59:59.000001",
    ),
    (
        "2000-01-01 00:00:00.500000",
        "YYYY-MM-DD HH:MM:SS.SSSSSS",
        "2000-01-01 00:00:00.500000",
    ),
    (
        "2026-06-03 12:30:45.123",
        "YYYY-MM-DD HH:MM:SS.SSS",
        "2026-06-03 12:30:45.123000",
    ),
    (
        "2026-12-31 23:59:59.999",
        "YYYY-MM-DD HH:MM:SS.SSS",
        "2026-12-31 23:59:59.999000",
    ),
]


@pytest.mark.parametrize(("raw", "umf_format", "spark_micro"), _FRACTIONAL_MICRO_PARITY)
def test_duckdb_fractional_seconds_match_spark_micros(
    raw: str, umf_format: str, spark_micro: str
) -> None:
    """DuckDB try_strptime preserves the SAME microseconds Spark does (sub-second)."""
    from tablespec.casting_utils import cast_column_sql

    expr = cast_column_sql("v", "TIMESTAMP", umf_format, dialect="duckdb")
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute("CREATE TEMP TABLE t(v VARCHAR)")
        con.execute("INSERT INTO t VALUES (?)", [raw])
        (parsed,) = con.execute(f"SELECT {expr} FROM t").fetchone()
    finally:
        con.close()
    assert parsed is not None, f"DuckDB unexpectedly NULLed {raw!r} for {umf_format}"
    assert parsed.strftime("%Y-%m-%d %H:%M:%S.%f") == spark_micro


# Fractional WIDTH boundary: Spark ".SSS" (millisecond) accepts at most 3
# fractional digits and NULLs a 4+/6-digit fraction, whereas DuckDB's %f would
# greedily consume up to 6. The registry pairs ".SSS" with %g (1-3 digits) and the
# padding pre-filter caps it at \d{1,3}, so DuckDB NULLs exactly what Spark NULLs.
# Each input below is one Spark NULLs; DuckDB must NULL it too (else the canonical
# second-resolution form would diverge from NULL to a real timestamp).
_FRACTIONAL_NULL_PARITY: list[tuple[str, str]] = [
    ("2026-12-31 23:59:59.999999", "YYYY-MM-DD HH:MM:SS.SSS"),
    ("2026-12-31 23:59:59.9999", "YYYY-MM-DD HH:MM:SS.SSS"),
]


@pytest.mark.parametrize(("raw", "umf_format"), _FRACTIONAL_NULL_PARITY)
def test_duckdb_fractional_seconds_null_match_spark(raw: str, umf_format: str) -> None:
    """A too-wide fraction Spark NULLs under ``.SSS`` also NULLs in DuckDB."""
    from tablespec.casting_utils import cast_column_sql

    expr = cast_column_sql("v", "TIMESTAMP", umf_format, dialect="duckdb")
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute("CREATE TEMP TABLE t(v VARCHAR)")
        con.execute("INSERT INTO t VALUES (?)", [raw])
        (parsed,) = con.execute(f"SELECT {expr} FROM t").fetchone()
    finally:
        con.close()
    assert parsed is None, (
        f"DuckDB parsed {raw!r} under {umf_format} but Spark NULLs it (width divergence)"
    )
