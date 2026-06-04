"""Item (3) state_modified_ci -- e2e: the derived selection resolves in real dbt.

UMF dirs -> ``core.selection.change_set`` -> ``dbt.selection.select_expression``
-> real ``dbt ls`` / ``dbt build`` on real duckdb. Proves the selection EXPRESSION
(not just its text) resolves through dbt's own graph to exactly the right node
set:

  * AC3.1/AC3.3 (e2e): editing ONLY ``member`` -> ``dbt ls --select <derived>``
    returns exactly ``{ingested_member, gold_member_claims}`` (member's model +
    its descendants), and EXCLUDES the unrelated ``ingested_claims``; a focused
    ``dbt build --select <derived>`` builds exactly that subset.
  * AC3.2 (e2e, NEGATIVE-OF-WHOLE-PROJECT): no UMF change -> empty ChangeSet ->
    the derived (unsatisfiable) selector makes ``dbt ls`` print ZERO model nodes
    and ``dbt build`` report 0 models -- it must NEVER fall through to building
    the whole project.

dbt(+duckdb) required; skips if absent. JVM-free (``no_spark``), ``slow``.
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

duckdb = pytest.importorskip("duckdb", reason="duckdb required for state:modified e2e")
pytest.importorskip("dbt", reason="dbt-core required for state:modified e2e")

from tablespec.core.selection import change_set  # noqa: E402
from tablespec.dbt import generate_dbt_dag_project  # noqa: E402
from tablespec.dbt.registry import NodeRegistry  # noqa: E402
from tablespec.dbt.selection import EMPTY_SELECTION, select_expression  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag"
TABLES = ["member", "claims", "member_claims"]
RAW_COLS = {
    "member": ["member_id", "member_name", "state"],
    "claims": ["claim_id", "member_id", "claim_amount"],
}


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def _copy_snapshot(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        shutil.copy(FIXTURE_DIR / f"{t}.umf.yaml", dest / f"{t}.umf.yaml")
    return dest


def _edit_member(umf_dir: Path) -> None:
    path = umf_dir / "member.umf.yaml"
    data = yaml.safe_load(path.read_text())
    data["columns"][0]["description"] = "EDITED for state:modified e2e"
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _load_umfs(umf_dir: Path) -> list[UMF]:
    return [
        UMF(**yaml.safe_load((umf_dir / f"{t}.umf.yaml").read_text())) for t in TABLES
    ]


def _load_raw_tables(db: Path) -> None:
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
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


def _ls_models(project: Path, db: Path, expr: str) -> set[str]:
    """Return the set of MODEL node names ``dbt ls --select <expr>`` resolves to."""
    res = _dbt(
        project,
        db,
        "ls",
        "--select",
        expr,
        "--resource-type",
        "model",
        "--output",
        "name",
    )
    assert res.returncode == 0, f"dbt ls failed:\n{res.stdout}\n{res.stderr}"
    # ``--output name`` prints one bare node name per line; dbt also prints log
    # lines to stdout, so keep only lines that are exactly a known model name shape.
    names: set[str] = set()
    for line in res.stdout.splitlines():
        tok = line.strip()
        if tok.startswith(("ingested_", "gold_")):
            names.add(tok)
    return names


def test_state_modified_selects_descendants_excludes_unrelated() -> None:
    """AC3.1/AC3.3 (e2e): edit only member -> select member's model + descendants."""
    _require_dbt()
    work = Path(tempfile.mkdtemp(prefix="tablespec_statemod_"))
    try:
        old_dir = _copy_snapshot(work / "old")
        new_dir = _copy_snapshot(work / "new")
        _edit_member(new_dir)

        project = work / "project"
        generate_dbt_dag_project(_load_umfs(new_dir), out_dir=project)
        db = project / "gold.duckdb"
        _load_raw_tables(db)
        assert _dbt(project, db, "parse").returncode == 0

        # CI baseline: the prior pipeline state already exists in the warehouse
        # (all models materialized once). A focused incremental CI run then
        # rebuilds ONLY the impacted subset on top of that state.
        baseline = _dbt(project, db, "run")
        assert baseline.returncode == 0, (
            f"baseline dbt run failed:\n{baseline.stdout}\n{baseline.stderr}"
        )

        cs = change_set(old_dir, new_dir)
        assert cs.modified == frozenset({"member"})
        reg = NodeRegistry(_load_umfs(new_dir))
        expr = select_expression(cs, reg)
        assert expr == "ingested_member+"

        # dbt's graph resolves the '+' fanout: member's model AND its descendant
        # gold_member_claims, but NOT the unrelated ingested_claims.
        selected = _ls_models(project, db, expr)
        assert selected == {"ingested_member", "gold_member_claims"}, selected
        assert "ingested_claims" not in selected

        # A focused build over the derived selection builds exactly that subset
        # of MODELS. (``dbt run`` is the model-only build step; the committed
        # member_claims fixture intentionally contains one orphan claim that makes
        # the relationships data-test FAIL by design -- a data-quality outcome,
        # not a selection outcome -- so the selection assertion uses ``run`` to
        # stay focused on WHICH models are built, deterministically.)
        res = _dbt(project, db, "run", "--select", expr)
        assert res.returncode == 0, f"dbt run failed:\n{res.stdout}\n{res.stderr}"
        results = json.loads((project / "target" / "run_results.json").read_text())[
            "results"
        ]
        built_models = {
            r["unique_id"].split(".")[-1]
            for r in results
            if r["unique_id"].startswith("model.")
        }
        assert built_models == {"ingested_member", "gold_member_claims"}, built_models
        assert "ingested_claims" not in built_models
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_state_unchanged_selects_nothing() -> None:
    """AC3.2 (e2e): no change -> empty selector -> 0 nodes, 0 models built.

    NEGATIVE-OF-WHOLE-PROJECT: the empty ChangeSet must NOT build the project.
    """
    _require_dbt()
    work = Path(tempfile.mkdtemp(prefix="tablespec_statemod_none_"))
    try:
        old_dir = _copy_snapshot(work / "old")
        new_dir = _copy_snapshot(work / "new")  # identical -> no change

        project = work / "project"
        generate_dbt_dag_project(_load_umfs(new_dir), out_dir=project)
        db = project / "gold.duckdb"
        _load_raw_tables(db)
        assert _dbt(project, db, "parse").returncode == 0

        cs = change_set(old_dir, new_dir)
        assert cs.is_empty
        reg = NodeRegistry(_load_umfs(new_dir))
        expr = select_expression(cs, reg)
        assert expr == EMPTY_SELECTION

        # dbt ls resolves ZERO models for the unsatisfiable selector.
        assert _ls_models(project, db, expr) == set()

        # dbt build over the empty selector: exit 0, ZERO models built (it must
        # never fall through to building all three models).
        res = _dbt(project, db, "build", "--select", expr)
        assert res.returncode == 0, f"dbt build failed:\n{res.stdout}\n{res.stderr}"
        results = json.loads((project / "target" / "run_results.json").read_text())[
            "results"
        ]
        built_models = [
            r["unique_id"] for r in results if r["unique_id"].startswith("model.")
        ]
        assert built_models == [], (
            f"empty ChangeSet must build 0 models, built: {built_models}"
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
