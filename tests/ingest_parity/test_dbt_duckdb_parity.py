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

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

duckdb = pytest.importorskip("duckdb", reason="duckdb required for dbt parity")
pytest.importorskip("dbt", reason="dbt-core required for dbt parity")

from tablespec.schemas.dbt_generator import generate_dbt_project  # noqa: E402

from .canonical import to_json  # noqa: E402
from .test_spark_baseline import _TWO_BATCH  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ingest"
GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "ingest_parity"


def _discover_fixtures() -> list[str]:
    return sorted(p.name[: -len(".umf.yaml")] for p in FIXTURE_DIR.glob("*.umf.yaml"))


def _connect(db_path: Path):
    """Open a DuckDB connection pinned to UTC (matches the Spark baseline)."""
    con = duckdb.connect(str(db_path))
    con.execute("SET TimeZone='UTC'")
    return con


def _batches_for(fixture: str) -> list[Path]:
    if fixture in _TWO_BATCH:
        return [
            FIXTURE_DIR / f"{fixture}.batch1.csv",
            FIXTURE_DIR / f"{fixture}.batch2.csv",
        ]
    return [FIXTURE_DIR / f"{fixture}.raw.csv"]


def _load_raw(db_path: Path, umf: dict[str, Any], csv_path: Path) -> None:
    """(Re)create the all-STRING ``raw_<table>`` landing table from a CSV batch.

    Mirrors the Spark baseline's ``_load_raw``: every UMF column is read as a
    string; ``_load_ts`` is cast to a timestamp. The table is dropped and rebuilt
    each batch so the model's per-batch dedup window has exactly the current batch
    to work on (the dbt incremental write then merges/appends into the target).
    """
    table = umf["table_name"]
    cols = [c["name"] for c in umf["columns"]]
    con = _connect(db_path)
    try:
        con.execute(f"DROP TABLE IF EXISTS raw_{table}")
        coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
        con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
        projection = ", ".join(f'"{c}"' for c in cols)
        projection += ', "_source_file", cast("_load_ts" as timestamp)'
        con.execute(
            f"INSERT INTO raw_{table} "
            f"SELECT {projection} "
            f"FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)"
        )
    finally:
        con.close()


def _decimal_scales(umf: dict[str, Any]) -> dict[str, int | None]:
    scales: dict[str, int | None] = {}
    for col in umf["columns"]:
        if (col.get("data_type") or "").upper() == "DECIMAL":
            scales[col["name"]] = col["scale"] if col.get("scale") is not None else 2
    return scales


def _collect_canonical(db_path: Path, umf: dict[str, Any]) -> str:
    table = umf["table_name"]
    columns = [c["name"] for c in umf["columns"]]
    con = _connect(db_path)
    try:
        projection = ", ".join(f'"{c}"' for c in columns)
        records = con.execute(f"SELECT {projection} FROM {table}").fetchall()
    finally:
        con.close()
    rows = [dict(zip(columns, rec, strict=True)) for rec in records]
    return to_json(rows, columns, _decimal_scales(umf))


def _run_dbt(project: Path, db_path: Path) -> None:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db_path))
    result = subprocess.run(
        [
            "dbt",
            "run",
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
        raise AssertionError(
            "dbt run failed:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


@pytest.mark.slow
@pytest.mark.parametrize("fixture", _discover_fixtures())
def test_dbt_duckdb_parity(fixture: str) -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")

    umf_path = FIXTURE_DIR / f"{fixture}.umf.yaml"
    umf = yaml.safe_load(umf_path.read_text())

    project = Path(tempfile.mkdtemp(prefix=f"tablespec_dbt_{fixture}_"))
    try:
        generate_dbt_project(umf, dialect="duckdb", out_dir=project)
        db_path = project / "ingest.duckdb"

        for batch in _batches_for(fixture):
            assert batch.exists(), f"missing raw batch: {batch}"
            _load_raw(db_path, umf, batch)
            _run_dbt(project, db_path)

        actual = _collect_canonical(db_path, umf)
    finally:
        shutil.rmtree(project, ignore_errors=True)

    golden = GOLDEN_DIR / f"{fixture}.spark.expected.json"
    assert golden.exists(), f"Spark golden missing for '{fixture}': {golden}"
    expected = golden.read_text()
    assert actual == expected, (
        f"dbt/duckdb parity mismatch for '{fixture}' (must match the Spark golden).\n"
        f"--- expected (spark golden) ---\n{expected}\n--- actual (dbt/duckdb) ---\n{actual}"
    )
