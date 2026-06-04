"""Model-contract e2e/functional/integration tests (item 2: model_contracts).

UMF -> generate dbt project (enforced contract: per-column ``data_type`` +
``not_null`` constraints) -> load real raw CSVs into duckdb -> ``dbt build`` ->
assert on the actual exit code, ``run_results.json``, and the duckdb catalog. The
NEGATIVE paths are explicit must-fail assertions:

  * AC2.3 matching types over real seed data -> ``dbt build`` SUCCEEDS and the
    duckdb catalog column types EQUAL the contract types.
  * AC2.4 (NEGATIVE) a SELECT that casts a column to a type drifting from the
    contract ``data_type`` -> ``dbt build`` FAILS with a contract mismatch.
  * AC2.5 (NEGATIVE) a NULL in a ``not_null``-constrained column -> ``dbt build``
    FAILS with a NOT NULL constraint error.

Contracts are enforced by the adapter at BUILD/materialization time, NOT at
``parse`` (per AC2.4). dbt(+duckdb) required; skips if absent. JVM-free, slow.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for contract e2e")
pytest.importorskip("dbt", reason="dbt-core required for contract e2e")

from tablespec.dbt import generate_dbt_project  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

CD_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "contract_drift"
_RAW_COLS = ["metric_id", "amount", "as_of_date", "label"]


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def _umf() -> UMF:
    return UMF(**yaml.safe_load((CD_DIR / "metrics.umf.yaml").read_text()))


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _load_raw(db: Path, csv: Path) -> None:
    """Create raw_metrics as all-VARCHAR + audit cols and load the CSV rows."""
    con = _connect(db)
    try:
        coldefs = ", ".join(f'"{c}" VARCHAR' for c in _RAW_COLS)
        coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
        con.execute(f"CREATE TABLE raw_metrics ({coldefs})")
        proj = ", ".join(f'"{c}"' for c in _RAW_COLS)
        con.execute(
            f"INSERT INTO raw_metrics SELECT {proj}, 'seed.csv', now() "
            f"FROM read_csv('{csv}', header=true, all_varchar=true, nullstr='')"
        )
    finally:
        con.close()


def _build_project(csv_name: str) -> tuple[Path, Path]:
    """Generate the contract_drift project and load one raw CSV variant."""
    project = Path(tempfile.mkdtemp(prefix="tablespec_contract_"))
    generate_dbt_project(_umf().model_dump(exclude_none=True), out_dir=project)
    db = project / "ingest.duckdb"
    _load_raw(db, CD_DIR / csv_name)
    return project, db


def _drift_amount_to_varchar(project: Path) -> None:
    """Mutate the model SELECT so ``amount`` casts to VARCHAR (drift from DECIMAL).

    The contract still declares ``amount DECIMAL(18,2)``, so the SELECT output type
    no longer matches the enforced contract -> dbt build must fail.
    """
    model = project / "models" / "metrics.sql"
    sql = model.read_text()
    new = re.sub(
        r"^.*AS amount,$",
        "        CAST(amount AS VARCHAR) AS amount,",
        sql,
        flags=re.M,
    )
    assert new != sql, "drift replacement did not apply (model SELECT shape changed?)"
    model.write_text(new)


def _dbt(project: Path, db: Path, *cmd: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db))
    return subprocess.run(
        ["dbt", *cmd, "--profiles-dir", str(project), "--project-dir", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _model_result(project: Path) -> dict:
    """Return the single model node result from ``run_results.json``."""
    data = json.loads((project / "target" / "run_results.json").read_text())
    models = [r for r in data["results"] if r["unique_id"].startswith("model.")]
    assert len(models) == 1, (
        f"expected one model node, got {[m['unique_id'] for m in models]}"
    )
    return models[0]


# ---------------------------------------------------------------------------
# AC2.3 matching types pass build + catalog types equal contract types
# ---------------------------------------------------------------------------


def test_contract_build_passes_matching() -> None:
    """AC2.3: matching SELECT types over real seed data -> build PASSES; catalog
    column types EQUAL the declared contract types."""
    _require_dbt()
    project, db = _build_project("metrics.valid.csv")
    try:
        built = _dbt(project, db, "build")
        assert built.returncode == 0, (
            f"matching-contract build should succeed:\n{built.stdout}\n{built.stderr}"
        )
        con = _connect(db)
        try:
            rows = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name='metrics' ORDER BY ordinal_position"
            ).fetchall()
        finally:
            con.close()
        catalog = dict(rows)
        # The duckdb catalog types must equal the contract's declared types.
        assert catalog["metric_id"] == "INTEGER", catalog
        assert catalog["amount"] == "DECIMAL(18,2)", catalog
        assert catalog["as_of_date"] == "DATE", catalog
        assert catalog["label"] == "VARCHAR", catalog
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC2.4 (NEGATIVE) SELECT type drift FAILS the contract at build time
# ---------------------------------------------------------------------------


def test_contract_type_drift_fails() -> None:
    """AC2.4 (NEGATIVE): a SELECT casting ``amount`` to VARCHAR drifts from the
    declared DECIMAL contract -> ``dbt build`` FAILS with a contract mismatch."""
    _require_dbt()
    project, db = _build_project("metrics.valid.csv")
    try:
        _drift_amount_to_varchar(project)
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail on the drifting contract type but succeeded:\n"
            f"{built.stdout}"
        )
        result = _model_result(project)
        assert result["status"] == "error", f"model node should error: {result}"
        # The error references the enforced contract failing.
        msg = (result.get("message") or "").lower()
        assert "contract" in msg, f"expected a contract-mismatch message: {result}"
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_contract_type_drift_parse_succeeds() -> None:
    """AC2.4 (path pinning): contract DRIFT is enforced at BUILD, not parse --
    ``dbt parse`` of the drifting project still succeeds (the failure is a
    build-time, not parse-time, signal)."""
    _require_dbt()
    project, db = _build_project("metrics.valid.csv")
    try:
        _drift_amount_to_varchar(project)
        parsed = _dbt(project, db, "parse")
        assert parsed.returncode == 0, (
            f"dbt parse should succeed even with SELECT-output drift "
            f"(contracts enforce at build):\n{parsed.stdout}\n{parsed.stderr}"
        )
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC2.5 (NEGATIVE) not-null constraint violation FAILS the build
# ---------------------------------------------------------------------------


def test_contract_not_null_violation_fails() -> None:
    """AC2.5 (NEGATIVE): seed data with a NULL in the ``not_null``-constrained
    ``label`` column -> ``dbt build`` FAILS with a NOT NULL constraint error."""
    _require_dbt()
    project, db = _build_project("metrics.null_label.csv")
    try:
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail on the NOT NULL violation but succeeded:\n"
            f"{built.stdout}"
        )
        result = _model_result(project)
        assert result["status"] == "error", f"model node should error: {result}"
        msg = (result.get("message") or "").lower()
        assert "not null" in msg or "not_null" in msg, (
            f"expected a NOT NULL constraint error: {result}"
        )
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC2.x column-shape negatives (must-fix from acceptance review)
# ---------------------------------------------------------------------------


def test_contract_missing_column_fails() -> None:
    """NEGATIVE: a SELECT that DROPS a contracted column -> build FAILS (the
    contract requires every declared column to be produced)."""
    _require_dbt()
    project, db = _build_project("metrics.valid.csv")
    try:
        model = project / "models" / "metrics.sql"
        sql = model.read_text()
        # Drop the ``as_of_date`` projection entirely (column missing from output).
        new = re.sub(r"^.*AS as_of_date,$\n", "", sql, flags=re.M)
        assert new != sql, "missing-column mutation did not apply"
        model.write_text(new)
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail when a contracted column is missing:\n{built.stdout}"
        )
        result = _model_result(project)
        assert result["status"] == "error", result
        assert "contract" in (result.get("message") or "").lower(), result
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_contract_extra_column_fails() -> None:
    """NEGATIVE: a SELECT that ADDS an undeclared column -> build FAILS (the
    contract forbids columns not in the declared set)."""
    _require_dbt()
    project, db = _build_project("metrics.valid.csv")
    try:
        model = project / "models" / "metrics.sql"
        sql = model.read_text()
        # Add an undeclared ``surprise`` column to the projection.
        new = re.sub(
            r"^(.*AS label)$",
            r"\1,\n        1 AS surprise",
            sql,
            flags=re.M,
        )
        assert new != sql, "extra-column mutation did not apply"
        model.write_text(new)
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail when an undeclared column is added:\n{built.stdout}"
        )
        result = _model_result(project)
        assert result["status"] == "error", result
        assert "contract" in (result.get("message") or "").lower(), result
    finally:
        shutil.rmtree(project, ignore_errors=True)
