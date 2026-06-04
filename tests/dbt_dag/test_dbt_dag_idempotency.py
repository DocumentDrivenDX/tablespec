"""DAG-level runtime idempotency for the multi-table GOLD dbt project.

The single-table idempotency suite (``tests/ingest_parity/test_dbt_idempotency``)
proves one ``ingested_<t>`` model's merge/append/full-refresh write contract. This
file proves the SAME contract holds end-to-end through a multi-table DAG, where a
staging change must PROPAGATE to a downstream gold model:

  * **re-run no-op.** Re-running ``dbt run`` against the SAME raw batch leaves both
    the incremental ``ingested_claims`` staging and the ``gold_member_claims`` mart
    byte-identical (canonical form) -- the merge upserts nothing.
  * **changed staging batch propagates.** Replacing ``raw_claims`` with a batch that
    UPDATES one claim and INSERTS one claim, then ``dbt run``, upserts staging AND
    the change flows through the gold join (new/updated rows appear, no duplicates).
    Re-running that batch is again a no-op.
  * **--full-refresh.** A new sole ``raw_claims`` row + ``dbt run --full-refresh``
    rebuilds the incremental staging from scratch (old claims gone) and the gold
    mart reflects only the surviving row.

Canonical comparison uses the shared ``to_json`` (NULL/decimal/timestamp stable
serialization), so a match is byte-identical, not just "same row count".

dbt(+duckdb) required; skips if the dbt CLI is unavailable. JVM-free (no_spark).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for dbt dag idempotency")
pytest.importorskip("dbt", reason="dbt-core required for dbt dag idempotency")

from tablespec.dbt import generate_dbt_dag_project  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

from tests.ingest_parity.canonical import to_json  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag"
TABLES = ["member", "claims", "member_claims"]

# Raw landing schemas (all-STRING + load metadata) per table.
RAW_COLS = {
    "member": ["member_id", "member_name", "state"],
    "claims": ["claim_id", "member_id", "claim_amount"],
}

GOLD_COLUMNS = ["claim_id", "member_id", "claim_amount", "member_name", "member_state"]
GOLD_SCALES = {"claim_amount": 2}
STAGING_CLAIMS_COLS = ["claim_id", "member_id", "claim_amount"]
STAGING_CLAIMS_SCALES = {"claim_amount": 2}


def _load_umfs() -> list[UMF]:
    return [
        UMF(**yaml.safe_load((FIXTURE_DIR / f"{t}.umf.yaml").read_text()))
        for t in TABLES
    ]


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _replace_raw(db: Path, table: str, rows: list[tuple]) -> None:
    """(Re)create the all-STRING ``raw_<table>`` with exactly *rows* (one batch).

    Mirrors the upstream landing contract: raw holds ONE batch per run; the
    incremental model merges/appends it into the persistent target.
    """
    cols = RAW_COLS[table]
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


def _canonical(db: Path, table_or_view: str, cols: list[str], scales) -> str:
    con = _connect(db)
    try:
        proj = ", ".join(f'"{c}"' for c in cols)
        records = con.execute(f"SELECT {proj} FROM {table_or_view}").fetchall()
    finally:
        con.close()
    rows = [dict(zip(cols, rec, strict=True)) for rec in records]
    return to_json(rows, cols, scales)


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


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


# Initial raw batches (mirror the committed CSV fixtures).
_MEMBER_BATCH = [
    ("1", "Alice Smith", "CA", "member.csv", "2026-01-01 00:00:00"),
    ("2", "Bob Jones", "NY", "member.csv", "2026-01-01 00:00:00"),
    ("3", "Carol White", "TX", "member.csv", "2026-01-01 00:00:00"),
]
_CLAIMS_BATCH1 = [
    ("100", "1", "250.50", "claims.csv", "2026-02-01 00:00:00"),
    ("101", "1", "75.00", "claims.csv", "2026-02-01 00:00:00"),
    ("102", "2", "500.00", "claims.csv", "2026-02-01 00:00:00"),
    ("103", "3", "12.25", "claims.csv", "2026-02-01 00:00:00"),
    ("104", "99", "999.99", "claims.csv", "2026-02-01 00:00:00"),  # orphan member
]


def test_dag_runtime_idempotency_propagation_and_full_refresh() -> None:
    """Re-run no-op, changed-staging-batch propagation, and --full-refresh, on the DAG."""
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_dagidem_"))
    try:
        generate_dbt_dag_project(_load_umfs(), out_dir=project)
        db = project / "gold.duckdb"

        # --- Initial load -------------------------------------------------
        _replace_raw(db, "member", _MEMBER_BATCH)
        _replace_raw(db, "claims", _CLAIMS_BATCH1)
        _dbt_run(project, db)

        gold0 = _canonical(db, "gold_member_claims", GOLD_COLUMNS, GOLD_SCALES)
        staging0 = _canonical(
            db, "ingested_claims", STAGING_CLAIMS_COLS, STAGING_CLAIMS_SCALES
        )
        con = _connect(db)
        try:
            n_staged = con.execute("SELECT count(*) FROM ingested_claims").fetchone()[0]
            n_gold = con.execute("SELECT count(*) FROM gold_member_claims").fetchone()[
                0
            ]
            # The orphan claim 104 (member_id=99, absent from member) survives the
            # LEFT JOIN with NULL member attrs -- proves gold keeps unmatched rows.
            orphan_name = con.execute(
                "SELECT member_name FROM gold_member_claims WHERE claim_id = 104"
            ).fetchone()
        finally:
            con.close()
        assert n_staged == 5, f"initial staging row count: {n_staged}"
        assert n_gold == 5, f"initial gold row count (LEFT JOIN): {n_gold}"
        assert orphan_name == (None,), (
            "orphan claim 104 should LEFT JOIN to NULL member"
        )

        # --- Re-run the SAME raw batch: a pure no-op (merge upserts nothing) ----
        _dbt_run(project, db)
        assert (
            _canonical(
                db, "ingested_claims", STAGING_CLAIMS_COLS, STAGING_CLAIMS_SCALES
            )
            == staging0
        ), (
            "re-running the same raw batch changed the incremental staging (not idempotent)"
        )
        assert (
            _canonical(db, "gold_member_claims", GOLD_COLUMNS, GOLD_SCALES) == gold0
        ), "re-running the same raw batch changed the gold mart (not idempotent)"

        # --- Changed staging batch must PROPAGATE to gold ----------------------
        # Update claim 100 (amount 250.50 -> 260.00) and insert claim 105 (member 2).
        _replace_raw(
            db,
            "claims",
            [
                ("100", "1", "260.00", "claims.csv", "2026-03-01 00:00:00"),  # upsert
                ("105", "2", "42.00", "claims.csv", "2026-03-01 00:00:00"),  # insert
            ],
        )
        _dbt_run(project, db)

        staging1 = _connect(db)
        try:
            claim_ids = {
                r[0]
                for r in staging1.execute(
                    "SELECT claim_id FROM ingested_claims ORDER BY 1"
                ).fetchall()
            }
            amt_100 = staging1.execute(
                "SELECT claim_amount FROM ingested_claims WHERE claim_id = 100"
            ).fetchone()[0]
            gold_amt_100 = staging1.execute(
                "SELECT claim_amount FROM gold_member_claims WHERE claim_id = 100"
            ).fetchone()[0]
            gold_member_105 = staging1.execute(
                "SELECT member_name FROM gold_member_claims WHERE claim_id = 105"
            ).fetchone()
        finally:
            staging1.close()
        # The merge upserted 100 and inserted 105; the original 101-104 persist.
        assert claim_ids == {100, 101, 102, 103, 104, 105}, (
            f"staging merge did not upsert/insert as expected: {sorted(claim_ids)}"
        )
        assert float(amt_100) == 260.00, "staging upsert of claim 100 did not take"
        # The change PROPAGATED into the gold join (new amount + the new claim row).
        assert float(gold_amt_100) == 260.00, "updated claim did not propagate to gold"
        assert gold_member_105 is not None and gold_member_105[0] == "Bob Jones", (
            "inserted claim 105 did not join to member 2 in gold"
        )

        gold1 = _canonical(db, "gold_member_claims", GOLD_COLUMNS, GOLD_SCALES)
        # Re-running the changed batch is itself a no-op (still idempotent).
        _dbt_run(project, db)
        assert (
            _canonical(db, "gold_member_claims", GOLD_COLUMNS, GOLD_SCALES) == gold1
        ), "re-running the changed batch was not idempotent"

        # --- --full-refresh rebuilds the incremental staging from scratch ------
        _replace_raw(
            db,
            "claims",
            [("900", "1", "9.99", "claims.csv", "2026-04-01 00:00:00")],
        )
        _dbt_run(project, db, "--full-refresh")
        con = _connect(db)
        try:
            staged = {
                r[0]
                for r in con.execute(
                    "SELECT claim_id FROM ingested_claims ORDER BY 1"
                ).fetchall()
            }
            gold_after = {
                r[0]
                for r in con.execute(
                    "SELECT claim_id FROM gold_member_claims ORDER BY 1"
                ).fetchall()
            }
        finally:
            con.close()
        # Old merged claims are gone; only the sole full-refresh batch survives.
        assert staged == {900}, f"--full-refresh did not rebuild staging: {staged}"
        assert gold_after == {900}, (
            f"--full-refresh staging rebuild did not propagate to gold: {gold_after}"
        )
    finally:
        shutil.rmtree(project, ignore_errors=True)
