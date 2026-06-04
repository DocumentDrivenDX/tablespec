"""E2E: relationships + accepted_values generic tests against REAL dbt + duckdb.

UMF -> generate dbt project -> load real raw CSVs into duckdb -> ``dbt build``
-> ``dbt test`` -> assert on the actual exit code AND ``run_results.json`` per
test node. Negative paths are explicit must-fail assertions:

  * AC1.8 (NEGATIVE) orphan FK row -> relationships test FAILS.
  * AC1.9 valid set (incl a NULL nullable-FK row) -> relationships test PASSES,
    and AC1.4 the NULL is NOT reported as an orphan.
  * AC1.10 (NEGATIVE) out-of-set value -> accepted_values FAILS; in-set PASSES.

dbt(+duckdb) required; skips if absent. JVM-free (no_spark), marked slow.
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

duckdb = pytest.importorskip("duckdb", reason="duckdb required for schema-test e2e")
pytest.importorskip("dbt", reason="dbt-core required for schema-test e2e")

from tablespec.dbt import generate_dbt_dag_project, generate_dbt_project  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

FK_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "fk_referential"
AV_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "accepted_values"


def _umf(path: Path) -> UMF:
    return UMF(**yaml.safe_load(path.read_text()))


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _load_raw(db: Path, table: str, cols: list[str], csv: Path) -> None:
    """Create raw_<table> as all-VARCHAR + audit cols and load the CSV rows."""
    con = _connect(db)
    try:
        coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
        con.execute(f"CREATE TABLE raw_{table} ({coldefs})")
        proj = ", ".join(f'"{c}"' for c in cols)
        proj += ', "_source_file", cast("_load_ts" as timestamp)'
        con.execute(
            f"INSERT INTO raw_{table} SELECT {proj} "
            f"FROM read_csv('{csv}', header=true, all_varchar=true, nullstr='')"
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


def _run_results(project: Path) -> dict[str, dict]:
    """Map ``run_results.json`` -> {node_unique_id: result}."""
    data = json.loads((project / "target" / "run_results.json").read_text())
    return {r["unique_id"]: r for r in data["results"]}


def _result_for(results: dict[str, dict], needle: str) -> dict:
    matches = [r for uid, r in results.items() if needle in uid]
    assert matches, f"no run-result node matching {needle!r} in {list(results)}"
    assert len(matches) == 1, f"ambiguous match for {needle!r}: {[*results]}"
    return matches[0]


# ---------------------------------------------------------------------------
# AC1.4 / AC1.8 / AC1.9 relationships PASS vs FAIL
# ---------------------------------------------------------------------------


def _build_fk_project(child_csv: Path) -> Path:
    """Generate the fk_referential DAG project and load raw data for one variant."""
    umfs = [
        _umf(FK_DIR / f"{t}.umf.yaml") for t in ("parent", "child", "child_enriched")
    ]
    project = Path(tempfile.mkdtemp(prefix="tablespec_fk_"))
    generate_dbt_dag_project(umfs, out_dir=project)
    db = project / "gold.duckdb"
    _load_raw(db, "parent", ["parent_id", "parent_name"], FK_DIR / "parent.raw.csv")
    _load_raw(db, "child", ["child_id", "parent_id"], child_csv)
    return project


def test_relationships_valid_passes() -> None:
    """AC1.9 + AC1.4: valid set (incl NULL nullable-FK) -> dbt test PASSES."""
    _require_dbt()
    project = _build_fk_project(FK_DIR / "child.valid.csv")
    try:
        db = project / "gold.duckdb"
        built = _dbt(project, db, "build")
        assert built.returncode == 0, (
            f"dbt build failed:\n{built.stdout}\n{built.stderr}"
        )

        results = _run_results(project)
        rel = _result_for(results, "relationships_gold_child_enriched_parent_id")
        assert rel["status"] == "pass", f"relationships should pass: {rel}"
        assert rel.get("failures", 0) == 0

        # AC1.4: the NULL nullable-FK row (child_id 103) is present and NOT an orphan.
        con = _connect(db)
        try:
            n_null = con.execute(
                "SELECT count(*) FROM gold_child_enriched WHERE parent_id IS NULL"
            ).fetchone()[0]
        finally:
            con.close()
        assert n_null == 1, "the NULL nullable-FK row must survive into the gold model"
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_relationships_orphan_fails() -> None:
    """AC1.8 (NEGATIVE): an orphan FK row makes the relationships test FAIL."""
    _require_dbt()
    project = _build_fk_project(FK_DIR / "child.orphan.csv")
    try:
        db = project / "gold.duckdb"
        # `build` runs models THEN tests; the orphan makes the test node fail, so
        # the overall invocation must report non-zero.
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail on the orphan FK but succeeded:\n{built.stdout}"
        )
        results = _run_results(project)
        rel = _result_for(results, "relationships_gold_child_enriched_parent_id")
        assert rel["status"] == "fail", f"relationships should FAIL on orphan: {rel}"
        assert rel.get("failures", 0) >= 1, f"expected >=1 orphan failure: {rel}"
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC1.10 accepted_values PASS vs FAIL
# ---------------------------------------------------------------------------


def _build_av_project(csv: Path) -> Path:
    umf = _umf(AV_DIR / "lob_table.umf.yaml")
    project = Path(tempfile.mkdtemp(prefix="tablespec_av_"))
    generate_dbt_project(umf.model_dump(exclude_none=True), out_dir=project)
    db = project / "ingest.duckdb"
    _load_raw(db, "lob_table", ["record_id", "lob", "note"], csv)
    return project


def test_accepted_values_valid_passes() -> None:
    """AC1.10 (positive): all in-set values -> accepted_values test PASSES."""
    _require_dbt()
    project = _build_av_project(AV_DIR / "lob_table.valid.csv")
    try:
        db = project / "ingest.duckdb"
        built = _dbt(project, db, "build")
        assert built.returncode == 0, (
            f"dbt build failed:\n{built.stdout}\n{built.stderr}"
        )
        results = _run_results(project)
        av = _result_for(results, "accepted_values_lob_table_lob")
        assert av["status"] == "pass", f"accepted_values should pass: {av}"
        assert av.get("failures", 0) == 0
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_accepted_values_bad_fails() -> None:
    """AC1.10 (NEGATIVE): an out-of-set value makes accepted_values FAIL."""
    _require_dbt()
    project = _build_av_project(AV_DIR / "lob_table.bad.csv")
    try:
        db = project / "ingest.duckdb"
        built = _dbt(project, db, "build")
        assert built.returncode != 0, (
            f"dbt build MUST fail on the out-of-set value but succeeded:\n{built.stdout}"
        )
        results = _run_results(project)
        av = _result_for(results, "accepted_values_lob_table_lob")
        assert av["status"] == "fail", f"accepted_values should FAIL: {av}"
        assert av.get("failures", 0) >= 1, f"expected >=1 out-of-set failure: {av}"
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC1.1 integration: dbt understands the relationships ref (manifest edge)
# ---------------------------------------------------------------------------


def test_relationships_manifest_edge() -> None:
    """AC1.1 (integration): the relationships test node depends on ingested_parent."""
    _require_dbt()
    umfs = [
        _umf(FK_DIR / f"{t}.umf.yaml") for t in ("parent", "child", "child_enriched")
    ]
    project = Path(tempfile.mkdtemp(prefix="tablespec_fkmani_"))
    try:
        generate_dbt_dag_project(umfs, out_dir=project)
        db = project / "gold.duckdb"
        parsed = _dbt(project, db, "parse")
        assert parsed.returncode == 0, (
            f"dbt parse failed:\n{parsed.stdout}\n{parsed.stderr}"
        )

        manifest = json.loads((project / "target" / "manifest.json").read_text())
        # Find the relationships test node and assert it depends on BOTH the model
        # under test and the referenced ingested_parent model.
        rel_nodes = {
            uid: node
            for uid, node in manifest["nodes"].items()
            if "relationships_gold_child_enriched_parent_id" in uid
        }
        assert rel_nodes, "relationships test node missing from manifest"
        (node,) = rel_nodes.values()
        dep_models = {m.split(".")[-1] for m in node["depends_on"]["nodes"]}
        assert "ingested_parent" in dep_models, dep_models
        assert "gold_child_enriched" in dep_models, dep_models
    finally:
        shutil.rmtree(project, ignore_errors=True)
