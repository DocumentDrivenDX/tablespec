"""Idempotency + incremental-write behaviour of the dbt(+duckdb) ingest path.

These run the generated single-table dbt project against a live DuckDB (no JVM)
and assert the WRITE contract dbt owns:

  * incremental + primary_key -> MERGE: an initial load then an upsert batch
    produces exactly one row per key (no duplicates), with the newest values
    winning; re-running the SAME batch is a no-op (idempotent).
  * snapshot -> table rebuild: each run fully replaces the target (full-refresh).

The byte-for-byte Spark-vs-duckdb parity lives in ``test_dbt_duckdb_parity``; this
file isolates the upsert/no-duplicate/full-refresh semantics directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb required for dbt idempotency")
pytest.importorskip("dbt", reason="dbt-core required for dbt idempotency")

from tablespec.dbt.single_table import generate_dbt_project  # noqa: E402

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]


_UMF = {
    "table_name": "acct",
    "primary_key": ["acct_id"],
    "ingestion": {"mode": "incremental", "order_by": ["_load_ts"]},
    "columns": [
        {"name": "acct_id", "data_type": "INTEGER", "nullable": False},
        {"name": "balance", "data_type": "INTEGER", "nullable": True},
    ],
}

_SNAPSHOT_UMF = {
    "table_name": "dim_acct",
    "ingestion": {"mode": "snapshot"},
    "columns": [
        {"name": "acct_id", "data_type": "INTEGER", "nullable": False},
        {"name": "label", "data_type": "VARCHAR", "nullable": True},
    ],
}


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _load_raw(db: Path, table: str, cols: list[str], rows: list[tuple]) -> None:
    """(Re)create the all-STRING ``raw_<table>`` with *rows* (one batch)."""
    con = _connect(db)
    try:
        con.execute(f"DROP TABLE IF EXISTS raw_{table}")
        coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
        con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
        placeholders = ", ".join("?" for _ in range(len(cols) + 2))
        con.executemany(f"INSERT INTO raw_{table} VALUES ({placeholders})", rows)
    finally:
        con.close()


def _dbt_run(project: Path, db: Path, *extra: str) -> None:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db))
    result = subprocess.run(
        [
            "dbt",
            "run",
            *extra,
            "--profiles-dir",
            str(project),
            "--project-dir",
            str(project),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"dbt run failed:\n{result.stdout}\n{result.stderr}")


def _rows(db: Path, table: str, cols: list[str]) -> list[tuple]:
    con = _connect(db)
    try:
        proj = ", ".join(f'"{c}"' for c in cols)
        return sorted(con.execute(f"SELECT {proj} FROM {table} ORDER BY 1").fetchall())
    finally:
        con.close()


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def test_incremental_merge_upserts_no_duplicates():
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_idem_"))
    try:
        generate_dbt_project(_UMF, dialect="duckdb", out_dir=project)
        db = project / "ingest.duckdb"
        cols = ["acct_id", "balance"]

        # Batch 1: two keys.
        _load_raw(
            db,
            "acct",
            cols,
            [
                ("1", "100", "f1", "2026-01-01 00:00:00"),
                ("2", "200", "f1", "2026-01-01 00:00:00"),
            ],
        )
        _dbt_run(project, db)
        assert _rows(db, "acct", cols) == [(1, 100), (2, 200)]

        # Batch 2: update key 1, insert key 3, and a within-batch duplicate of
        # key 3 (newest _load_ts wins via the dedup window).
        _load_raw(
            db,
            "acct",
            cols,
            [
                ("1", "150", "f2", "2026-01-02 00:00:00"),  # upsert
                ("3", "300", "f2", "2026-01-02 00:00:00"),  # insert (older)
                ("3", "333", "f2", "2026-01-02 01:00:00"),  # newer dup -> wins
            ],
        )
        _dbt_run(project, db)
        # key 1 updated, key 2 untouched, key 3 inserted with newest value, no dups.
        assert _rows(db, "acct", cols) == [(1, 150), (2, 200), (3, 333)]

        # Re-running the SAME batch 2 is idempotent (merge -> no new rows).
        _dbt_run(project, db)
        assert _rows(db, "acct", cols) == [(1, 150), (2, 200), (3, 333)]
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_incremental_full_refresh_rebuilds():
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_idem_fr_"))
    try:
        generate_dbt_project(_UMF, dialect="duckdb", out_dir=project)
        db = project / "ingest.duckdb"
        cols = ["acct_id", "balance"]

        _load_raw(db, "acct", cols, [("1", "100", "f1", "2026-01-01 00:00:00")])
        _dbt_run(project, db)
        assert _rows(db, "acct", cols) == [(1, 100)]

        # A different sole row + --full-refresh drops and rebuilds the table.
        _load_raw(db, "acct", cols, [("9", "999", "f2", "2026-02-01 00:00:00")])
        _dbt_run(project, db, "--full-refresh")
        assert _rows(db, "acct", cols) == [(9, 999)]
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_snapshot_table_replaces_each_run():
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_idem_snap_"))
    try:
        generate_dbt_project(_SNAPSHOT_UMF, dialect="duckdb", out_dir=project)
        db = project / "ingest.duckdb"
        cols = ["acct_id", "label"]

        _load_raw(db, "dim_acct", cols, [("1", "a", "f1", "2026-01-01 00:00:00")])
        _dbt_run(project, db)
        assert _rows(db, "dim_acct", cols) == [(1, "a")]

        # New full snapshot fully replaces the prior contents (drop/reload).
        _load_raw(
            db,
            "dim_acct",
            cols,
            [
                ("2", "b", "f2", "2026-02-01 00:00:00"),
                ("3", "c", "f2", "2026-02-01 00:00:00"),
            ],
        )
        _dbt_run(project, db)
        assert _rows(db, "dim_acct", cols) == [(2, "b"), (3, "c")]
    finally:
        shutil.rmtree(project, ignore_errors=True)
