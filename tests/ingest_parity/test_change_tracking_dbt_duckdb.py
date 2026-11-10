# SPDX-License-Identifier: MIT OR Apache-2.0
"""``mode: change_tracking`` through a real ``dbt run`` on DuckDB, both strategies.

Same scenario as the Spark tests in ``tests/unit/test_ingestion_append_change_tracking.py``:
delivery 1 is a full baseline (no operation), delivery 2 has increments -- key 2
updated twice (version 9, then 10), key 3 inserted (v8) and deleted (v11, key
only in ``CT_k``) -- and delivery 3 re-baselines without key 1. ``merge`` sees
one batch per run; ``rebuild`` sees the accumulated raw history. Assertions are
aggregates: (row count, sum of keys, sum of amounts).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.no_spark,
    pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt CLI not on PATH"),
]

duckdb = pytest.importorskip("duckdb", reason="duckdb required")
pytest.importorskip("dbt", reason="dbt-core required")

from tablespec.dbt.single_table import generate_dbt_project  # noqa: E402

_RAW_DDL = (
    "CREATE OR REPLACE TABLE raw_ch (k VARCHAR, amt VARCHAR, CT_k VARCHAR, "
    "SYS_CHANGE_OPERATION VARCHAR, SYS_CHANGE_VERSION VARCHAR, delivery INTEGER, "
    "_source_file VARCHAR, _load_ts TIMESTAMP)"
)
_INSERT = "INSERT INTO raw_ch VALUES (?, ?, ?, ?, ?, ?, 'f', TIMESTAMP '2026-01-01')"
_TOTALS = "SELECT count(*), sum(k), sum(amt) FROM ch"

_DELIVERIES = [
    [("1", "10", None, None, None, 1), ("2", "20", None, None, None, 1)],
    [
        ("2", "21", "2", "U", "9", 2),
        ("2", "22", "2", "U", "10", 2),
        (None, None, "3", "D", "11", 2),
        ("3", "30", "3", "I", "8", 2),
    ],
    [("2", "22", None, None, None, 3), ("3", "31", None, None, None, 3)],
]


def _umf(strategy: str) -> dict:
    return {
        "table_name": "ch",
        "primary_key": ["k"],
        "columns": [
            {"name": "k", "data_type": "BIGINT"},
            {"name": "amt", "data_type": "DECIMAL", "precision": 12, "scale": 2},
        ],
        "ingestion": {
            "mode": "change_tracking",
            "order_by": ["delivery"],
            "change_tracking": {
                "strategy": strategy,
                "key_columns": ["CT_k"],
                "version_column": "SYS_CHANGE_VERSION",
            },
        },
    }


def _totals(tmp_path: Path, strategy: str, deliveries: int) -> tuple:
    project = tmp_path / strategy
    generate_dbt_project(_umf(strategy), dialect="duckdb", out_dir=project)
    db = project / "ingest.duckdb"
    for i, rows in enumerate(_DELIVERIES[:deliveries]):
        con = duckdb.connect(str(db))
        try:
            if i == 0 or strategy == "merge":  # merge: one batch per run
                con.execute(_RAW_DDL)
            con.executemany(_INSERT, rows)
        finally:
            con.close()
        result = subprocess.run(
            [
                "dbt",
                "run",
                "--profiles-dir",
                str(project),
                "--project-dir",
                str(project),
            ],
            env=dict(os.environ, DBT_DUCKDB_PATH=str(db)),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout[-4000:]
    con = duckdb.connect(str(db))
    try:
        count, keys, amounts = con.execute(_TOTALS).fetchone()
    finally:
        con.close()
    return (count, keys, float(amounts))


@pytest.mark.parametrize("strategy", ["merge", "rebuild"])
def test_dbt_change_tracking_baseline_then_increments(tmp_path, strategy):
    assert _totals(tmp_path, strategy, 2) == (2, 3, 32.0)


def test_dbt_change_tracking_rebuild_rebaseline_supersedes(tmp_path):
    assert _totals(tmp_path, "rebuild", 3) == (2, 5, 53.0)
