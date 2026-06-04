"""LIVE acyclic gold -> gold DAG: a downstream gold model depends on an upstream one.

The member_claims e2e fixture only exercises gold -> ingested edges. This file
covers the renderer's GOLD producer path (renderer.py: a resolved node whose role
is GOLD renders ``{{ ref('gold_<t>') }}``) END TO END:

  * the downstream gold (``summary``) derives from the UPSTREAM gold (``enriched``),
    so its rendered body must carry ``{{ ref('gold_enriched') }}`` -- a model->model
    edge, never an ``ingested_enriched`` (there is no such staging) nor a phantom
    external source.
  * the IR is acyclic and ``dbt parse/compile/run`` all SUCCEED.
  * the dbt manifest ``parent_map`` carries the exact model->model edge
    ``gold_summary -> gold_enriched`` (plus the upstream gold's own staging edges),
    proving the static ref was understood by dbt, not just present as text.
  * the run produces the correct joined data (the downstream value chains through
    the upstream gold).

dbt(+duckdb) required; skips if absent. JVM-free (no_spark).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for gold-chain dag test")
pytest.importorskip("dbt", reason="dbt-core required for gold-chain dag test")

from tablespec.dbt import generate_dbt_dag_project  # noqa: E402
from tablespec.dbt.registry import NodeRegistry  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag_gold_chain"
TABLES = ["member", "claims", "enriched", "summary"]
RAW_COLS = {
    "member": ["member_id", "member_name"],
    "claims": ["claim_id", "member_id"],
}

# The IR-predicted model->parent edges for the gold chain.
EXPECTED_MODEL_PARENTS = {
    "ingested_member": {"raw_member"},
    "ingested_claims": {"raw_claims"},
    "gold_enriched": {"ingested_claims", "ingested_member"},
    "gold_summary": {"gold_enriched"},  # the model->model edge under test
}


def _load_umfs() -> list[UMF]:
    return [
        UMF(**yaml.safe_load((FIXTURE_DIR / f"{t}.umf.yaml").read_text()))
        for t in TABLES
    ]


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _load_raw_tables(db: Path) -> None:
    con = _connect(db)
    try:
        for t, cols in RAW_COLS.items():
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE raw_{t} ({coldefs})")
            proj = ", ".join(f'"{c}"' for c in cols)
            proj += ', "_source_file", cast("_load_ts" as timestamp)'
            csv = FIXTURE_DIR / f"{t}.raw.csv"
            con.execute(
                f"INSERT INTO raw_{t} SELECT {proj} "
                f"FROM read_csv_auto('{csv}', header=true, all_varchar=true)"
            )
    finally:
        con.close()


def _dbt(project: Path, db: Path, *cmd: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db))
    return subprocess.run(
        ["dbt", *cmd, "--profiles-dir", str(project), "--project-dir", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def test_gold_chain_ir_is_acyclic_and_renders_gold_ref() -> None:
    """IR-level: the downstream gold depends on the upstream gold; body refs it."""
    reg = NodeRegistry(_load_umfs())
    assert reg.gold_tables == {"enriched", "summary"}
    assert reg.staging_tables == {"member", "claims"}
    assert reg.plan.nodes["gold_summary"].depends_on == {"gold_enriched"}
    assert reg.plan.detect_cycle() is None

    files = generate_dbt_dag_project(_load_umfs())
    body = files["models/marts/gold_summary.sql"]
    # The downstream gold refs the UPSTREAM GOLD model, not a (nonexistent) staging.
    assert "{{ ref('gold_enriched') }}" in body
    assert "ingested_enriched" not in body
    assert "source('external'" not in body


def test_gold_chain_runs_and_manifest_has_model_to_model_edge() -> None:
    """LIVE: dbt parse/compile/run succeed and the model->model edge is in the manifest."""
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_goldchain_"))
    try:
        generate_dbt_dag_project(_load_umfs(), out_dir=project)
        db = project / "gold.duckdb"
        _load_raw_tables(db)

        for stage in ("parse", "compile", "run"):
            res = _dbt(project, db, stage)
            assert res.returncode == 0, (
                f"dbt {stage} failed:\n{res.stdout}\n{res.stderr}"
            )

        # Manifest parent_map must carry the gold_summary -> gold_enriched edge.
        manifest = json.loads((project / "target" / "manifest.json").read_text())
        model_parents: dict[str, set[str]] = {}
        for node, parents in manifest["parent_map"].items():
            if not node.startswith("model."):
                continue
            name = node.split(".")[-1]
            model_parents[name] = {p.split(".")[-1] for p in parents}
        assert model_parents == EXPECTED_MODEL_PARENTS, (
            f"manifest model edges diverge from the IR.\n"
            f"  manifest: {model_parents}\n  expected: {EXPECTED_MODEL_PARENTS}"
        )

        # The downstream value chained THROUGH the upstream gold: claim 100 -> member 1
        # -> 'Alice Smith' must appear as summary.who.
        con = _connect(db)
        try:
            who = con.execute(
                "SELECT who FROM gold_summary WHERE claim_id = 100"
            ).fetchone()
            n = con.execute("SELECT count(*) FROM gold_summary").fetchone()[0]
        finally:
            con.close()
        assert who == ("Alice Smith",), f"downstream gold value did not chain: {who}"
        assert n == 3, f"expected 3 summary rows, got {n}"
    finally:
        shutil.rmtree(project, ignore_errors=True)
