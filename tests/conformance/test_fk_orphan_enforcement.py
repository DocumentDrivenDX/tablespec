"""EXECUTED orphan-FK enforcement for gold_fk_integrity (Phase 4 must-fix).

FK referential integrity is NOT a canonical-row comparison: ``generate_sql_plan``
uses FK metadata only for join planning, never emits an orphan check. It is
enforced at the dbt ``relationships`` schema-test tier instead. The matrix-review
must-fix requires this orphan-FK negative to be ACTUALLY EXECUTED and GATING here
(not merely asserted to exist in the corpus).

This tier generates the dbt project for the ``claims`` table with its
``member_id -> member.member_id`` foreign key (and the referenced ``member`` model
so the ``relationships`` test resolves to a model dbt builds), loads the raw landing
tables on duckdb, and runs ``dbt build`` (model materialization + schema tests). It
asserts, on REAL data and a REAL dbt run:

  * ``dbt build`` PASSES on ``claims.clean.csv`` (every claim's member_id exists in
    member) -- the relationships test is green; and
  * ``dbt build`` FAILS on ``claims.orphan.csv`` (the injected orphan ``member_id=7``)
    -- the relationships test detects the orphan and the run is non-zero.

Both legs run the SAME generated project; only the raw ``claims`` rows differ. The
negative leg's failure must come from the relationships TEST (not a load/compile
error), which is asserted on the captured dbt output.

Run::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv uv run pytest \
      tests/conformance/test_fk_orphan_enforcement.py
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from tablespec.models.umf import UMF
from tablespec.schemas.dbt_generator import generate_dbt_project
from tests.conformance.corpus.registry import gold_cases

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for the orphan-FK tier")
pytest.importorskip("dbt", reason="dbt-core required for the orphan-FK tier")
pytest.importorskip(
    "dbt.adapters.duckdb", reason="dbt-duckdb adapter required for the orphan-FK tier"
)
if shutil.which("dbt") is None:  # pragma: no cover - env guard
    pytest.skip("dbt CLI not on PATH", allow_module_level=True)

_FK_CASE = next(c for c in gold_cases() if c.id == "gold_fk_integrity")


def _load_raw(con, table: str, csv: Path, cols: list[str]) -> None:
    """Create ``main.raw_<table>`` with the provenance columns the ingest model reads."""
    con.execute("CREATE SCHEMA IF NOT EXISTS main")
    con.execute(f"DROP TABLE IF EXISTS main.raw_{table}")
    coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
    con.execute(
        f"CREATE TABLE main.raw_{table} "
        f'({coldefs}, "_source_file" VARCHAR, "_load_ts" TIMESTAMP)'
    )
    proj = ", ".join(f'"{c}"' for c in cols)
    con.execute(
        f"INSERT INTO main.raw_{table} SELECT {proj}, "
        f"'{table}.csv', TIMESTAMP '2026-01-01 00:00:00' "
        f"FROM read_csv_auto('{csv}', header=true, all_varchar=true)"
    )


def _run_dbt_build(project: Path, db_path: Path) -> subprocess.CompletedProcess:
    """Run ``dbt build`` (materialize + schema tests) and capture the result."""
    import os

    env = dict(os.environ, DBT_DUCKDB_PATH=str(db_path))
    return subprocess.run(
        [
            "dbt",
            "build",
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


def _build_with_claims(claims_csv_name: str) -> subprocess.CompletedProcess:
    """Generate the FK project, load member + the chosen claims CSV, run ``dbt build``."""
    assert _FK_CASE.gold_dir is not None
    d = _FK_CASE.gold_dir
    claims_raw = yaml.safe_load((d / "claims.umf.yaml").read_text())
    member = UMF(**yaml.safe_load((d / "member.umf.yaml").read_text()))

    project = Path(tempfile.mkdtemp(prefix="fk_orphan_"))
    try:
        files = generate_dbt_project(
            claims_raw,
            dialect="duckdb",
            target="duckdb",
            related=[member],
            out_dir=project,
        )
        # The relationships test must be emitted on the FK column.
        assert "relationships:" in files["models/schema.yml"], (
            "no relationships test emitted for the claims.member_id FK"
        )

        db_path = project / "fk.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            _load_raw(con, "member", d / "member.raw.csv", ["member_id", "member_name"])
            _load_raw(con, "claims", d / claims_csv_name, ["claim_id", "member_id"])
        finally:
            con.close()
        return _run_dbt_build(project, db_path)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_orphan_fk_tier_is_wired_here() -> None:
    """Guard: the orphan-FK tier must EXECUTE here (duckdb + dbt-duckdb installed).

    The module skips only if duckdb/dbt/dbt-duckdb are absent. They are installed in
    this env, so the tier must NOT be all-skipped (green-on-nothing). Reaching this
    test at all (past the module-level importorskip) proves the deps resolved; assert
    the FK fixtures + relationships emission are wired so the two real legs run.
    """
    assert _FK_CASE.gold_dir is not None and _FK_CASE.gold_dir.is_dir()
    d = _FK_CASE.gold_dir
    assert (d / "claims.clean.csv").exists() and (d / "claims.orphan.csv").exists()
    claims_raw = yaml.safe_load((d / "claims.umf.yaml").read_text())
    member = UMF(**yaml.safe_load((d / "member.umf.yaml").read_text()))
    files = generate_dbt_project(
        claims_raw, dialect="duckdb", target="duckdb", related=[member]
    )
    assert "relationships:" in files["models/schema.yml"], (
        "the orphan-FK tier is not wired: no relationships test emitted for the FK"
    )


def test_relationships_test_passes_on_clean_data() -> None:
    """dbt build (incl. the relationships test) PASSES on clean FK data."""
    result = _build_with_claims("claims.clean.csv")
    assert result.returncode == 0, (
        "dbt build must PASS on clean FK data (every member_id resolves).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "relationships_" in result.stdout, (
        "the relationships test was not run on the clean data (no test executed)"
    )


def test_relationships_test_fails_on_orphan_fk() -> None:
    """dbt build FAILS on the injected orphan FK (member_id=7 absent from member)."""
    result = _build_with_claims("claims.orphan.csv")
    assert result.returncode != 0, (
        "dbt build must FAIL on the orphan FK (member_id=7 has no member row), "
        "but it succeeded -- orphan-FK enforcement is NOT gating.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    # The failure must come from the relationships TEST detecting the orphan ROW --
    # not a load/compile error and not a test-ERROR. dbt reports a failed
    # relationships test as ``FAIL <n>`` with ``Got <n> result, configured to fail
    # if != 0`` where <n> is the orphan count. Require that specific signal so a
    # broken/erroring test cannot satisfy the negative (it must prove member_id=7 was
    # caught as exactly one orphan).
    out = result.stdout + result.stderr
    assert "relationships_claims_member_id" in out, (
        "the FK relationships test did not run on the orphan data.\n"
        f"--- output ---\n{out}"
    )
    assert "FAIL 1" in out and "Got 1 result, configured to fail if != 0" in out, (
        "the orphan-FK negative did not fail via the relationships test detecting "
        "exactly the one injected orphan (member_id=7). A test ERROR or unrelated "
        f"failure does not prove orphan detection.\n--- output ---\n{out}"
    )
