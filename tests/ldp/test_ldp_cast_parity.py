"""Cross-engine cast parity for the PROTOTYPE LDP emitter.

Proves the LDP ingested-dataset cast bodies are the SHARED cast layer
(``cast_column_sql`` via ``build_ingest_select``), not a fork:

  1. The cast SELECT lines embedded in the LDP ``ingested_<t>`` SQL are
     CHARACTER-IDENTICAL to the dbt path's ``IngestSelect.select_block`` for the
     same UMF + dialect (same source of truth).
  2. The LDP ingested cast body is duckdb-runnable and produces the SAME typed
     result as the dbt/direct cast body over the SAME raw rows (run on real duckdb,
     canonicalized with the existing parity harness).

LDP itself runs only on Databricks; this does NOT execute the LDP pipeline -- it
proves the CAST LAYER is shared by running the extracted SELECT on duckdb. The
streaming/APPLY-CHANGES runtime is out of scope (see the package docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tablespec.ldp import generate_ldp_project
from tablespec.models.umf import UMF
from tablespec.schemas.ingest_generator import build_ingest_select

from ..ingest_parity.canonical import to_json

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for LDP cast parity")

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ldp"


def _load(table: str) -> UMF:
    return UMF(**yaml.safe_load((FIXTURE_DIR / f"{table}.umf.yaml").read_text()))


def _extract_select_body(ldp_sql: str) -> str:
    """Pull the cast SELECT column block out of an LDP ingested dataset's SQL.

    Works for both the APPLY CHANGES form (``SELECT\\n<cols>\\n  FROM STREAM``) and
    the streaming/mat-view form (``AS SELECT\\n<cols>\\nFROM``). Returns the column
    lines between the ``SELECT`` and the ``FROM`` exactly as emitted.
    """
    lines = ldp_sql.splitlines()
    start = next(
        i
        for i, ln in enumerate(lines)
        if ln.strip().endswith("SELECT") or ln.strip() == "SELECT"
    )
    body: list[str] = []
    for ln in lines[start + 1 :]:
        if ln.strip().upper().startswith("FROM "):
            break
        body.append(ln)
    return "\n".join(body)


def test_ldp_cast_body_is_identical_to_dbt_select_block() -> None:
    """The LDP ingested cast lines == the shared IngestSelect.select_block (no fork)."""
    for table in ["claims", "member", "events"]:
        umf = _load(table)
        # Generate the single table in isolation: the ingested cast body is
        # independent of the rest of the set (no gold edges needed).
        ldp_sql = generate_ldp_project([umf], dialect="duckdb").get(
            f"ingested/ingested_{table}.sql"
        )
        assert ldp_sql is not None, f"no ingested dataset for {table}"

        shared = build_ingest_select(
            umf.model_dump(exclude_none=True), dialect="duckdb"
        )
        emitted = _extract_select_body(ldp_sql)
        # The shared select_block (with its own indentation) must appear verbatim.
        assert shared.select_block in emitted, (
            f"LDP cast body for {table} is not the shared cast layer.\n"
            f"--- shared ---\n{shared.select_block}\n--- emitted ---\n{emitted}"
        )


def _connect():
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    return con


def test_ldp_cast_body_runs_on_duckdb_matching_shared_cast() -> None:
    """The extracted LDP cast SELECT runs on duckdb == the shared dbt/direct cast."""
    umf = _load("claims")
    umf_data = umf.model_dump(exclude_none=True)
    columns = [c["name"] for c in umf_data["columns"]]
    scales = {
        c["name"]: (c.get("scale") if c.get("scale") is not None else 2)
        for c in umf_data["columns"]
        if (c.get("data_type") or "").upper() == "DECIMAL"
    }

    # A small raw batch (all-string landing rows, incl. a malformed status + bad
    # decimal that must NULL/round-trip identically under the shared cast).
    raw_rows = [
        ("1", "10", "$100.50", "PAID"),
        ("2", "20", "  ", "DENIED"),
        ("3", "", "abc", "BOGUS"),
    ]

    shared = build_ingest_select(umf_data, dialect="duckdb")
    ldp_sql = generate_ldp_project([umf], dialect="duckdb")[
        "ingested/ingested_claims.sql"
    ]
    ldp_body = _extract_select_body(ldp_sql)

    def _run(select_block: str) -> str:
        con = _connect()
        try:
            con.execute(
                "CREATE TABLE raw_claims "
                "(claim_id VARCHAR, member_id VARCHAR, claim_amount VARCHAR, "
                "status VARCHAR)"
            )
            con.executemany("INSERT INTO raw_claims VALUES (?, ?, ?, ?)", raw_rows)
            recs = con.execute(f"SELECT\n{select_block}\nFROM raw_claims").fetchall()
        finally:
            con.close()
        rows = [dict(zip(columns, rec, strict=True)) for rec in recs]
        return to_json(rows, columns, scales)

    shared_json = _run(shared.select_block)
    ldp_json = _run(ldp_body)
    assert ldp_json == shared_json, (
        "LDP cast body produced a DIFFERENT duckdb result than the shared cast "
        f"(cast layer forked!).\n--- shared ---\n{shared_json}\n--- ldp ---\n{ldp_json}"
    )
    # Sanity: the typed cast actually happened (decimal scale, NULL-on-failure).
    assert '"100.50"' in shared_json  # $-strip + decimal scale
    assert "NULL" in shared_json  # bad decimal / empty -> NULL
