"""LIVE DAG covering the non-trivial ref branches the member_claims e2e omits.

The member_claims e2e exercises only bare same-pipeline ``gold -> ingested`` edges.
This fixture exercises the three OTHER resolution branches the renderer/registry
support, END TO END (rendered ref text AND the dbt manifest), so the manifest
edges are asserted against the IR -- not merely against generated text:

  * **qualified-local canonical bind.** ``member`` has ``canonical_name:
    mart.member``; claims/enriched reference ``mart.member`` -> it binds to
    ``ingested_member`` (never a phantom external source).
  * **alias-resolved ref.** ``provider`` declares alias ``prov``; the reference
    ``prov`` resolves to ``ingested_provider``.
  * **external qualified source.** ``extpipe.refs`` is genuinely absent + qualified
    -> a ``source('external', 'extpipe__refs')`` leaf.

The test asserts the IR edges, the rendered ref/source literals, that dbt
parse/compile SUCCEED, and that the dbt manifest ``parent_map`` (model edges) +
``sources`` match the IR exactly -- i.e. dbt actually UNDERSTOOD the static
``{{ ref }}`` / ``{{ source }}`` literals as graph edges, not just text. The
manifest's ``parent_map`` is populated at parse/compile time from those literals,
so a passing parse/compile + manifest audit is a faithful binding check.

Note: ``dbt run`` of THIS fixture is intentionally out of scope. The external
relation's COLUMN (``extpipe.refs.v``) is not knowable to the core
``SQLPlanGenerator`` (the external schema is, by definition, outside the UMF set),
so the generated final-assembly SELECT references a column the join step cannot
expose -- a known core-generator limitation for external-table COLUMN projection,
unrelated to dbt edge binding. The qualified-local + alias branches DO run cleanly
(proven by the member_claims / gold-chain live suites and asserted here via
compile). Edge binding -- the thing under test -- is fully covered by the manifest.
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

duckdb = pytest.importorskip("duckdb", reason="duckdb required for ref-branch dag test")
pytest.importorskip("dbt", reason="dbt-core required for ref-branch dag test")

from tablespec.dbt import generate_dbt_dag_project  # noqa: E402
from tablespec.dbt.registry import NodeRegistry  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag_refbranches"
TABLES = ["member", "provider", "claims", "enriched"]
RAW_COLS = {
    "member": ["member_id", "member_name"],
    "provider": ["provider_id", "provider_name"],
    "claims": ["claim_id", "member_id", "provider_id", "ref_id"],
}

# IR-predicted model->parent edges. gold_enriched depends on all three resolved
# local staging models PLUS the external source.
EXPECTED_MODEL_PARENTS = {
    "ingested_member": {"raw_member"},
    "ingested_provider": {"raw_provider"},
    "ingested_claims": {"raw_claims"},
    "gold_enriched": {
        "ingested_claims",
        "ingested_member",
        "ingested_provider",
        "extpipe__refs",
    },
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
        # The EXTERNAL source must physically exist for dbt run; it is declared in
        # sources.yml under the 'external' group (schema main) as 'extpipe__refs'.
        con.execute('CREATE TABLE extpipe__refs ("ref_id" INTEGER, "v" VARCHAR)')
        con.execute("INSERT INTO extpipe__refs VALUES (500, 'REF-A'), (501, 'REF-B')")
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


def test_ref_branches_ir_and_rendered_literals() -> None:
    """IR + rendered text: qualified bind, alias bind, and external source."""
    reg = NodeRegistry(_load_umfs())
    assert reg.gold_tables == {"enriched"}
    assert reg.staging_tables == {"member", "provider", "claims"}
    assert reg.plan.nodes["gold_enriched"].depends_on == {
        "ingested_claims",
        "ingested_member",
        "ingested_provider",
        "extpipe__refs",
    }
    assert reg.dangling_refs == set()
    # Exactly one external node; the qualified-local + alias refs are NOT external.
    ext = [n for n in reg.plan.nodes.values() if n.external]
    assert [n.node_id for n in ext] == ["extpipe__refs"]

    files = generate_dbt_dag_project(_load_umfs())
    body = files["models/marts/gold_enriched.sql"]
    # qualified-local canonical bind + alias bind -> model refs (NOT external).
    assert "{{ ref('ingested_member') }}" in body
    assert "{{ ref('ingested_provider') }}" in body
    # external qualified source -> the dedicated external source group.
    assert "{{ source('external', 'extpipe__refs') }}" in body
    # sources.yml declares the external table under the 'external' group.
    sources = files["models/sources.yml"]
    assert "  - name: external" in sources
    assert "      - name: extpipe__refs" in sources


def test_ref_branches_compile_and_manifest_matches_ir() -> None:
    """LIVE: dbt parse/compile succeed; manifest edges + sources match the IR.

    parse/compile build the manifest ``parent_map`` from the static ref/source
    literals -- so a passing compile + edge audit proves dbt BOUND each branch
    (qualified-local, alias, external) to the right node. (``run`` is out of scope
    for the external-COLUMN projection; see the module docstring.)
    """
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_refbranch_"))
    try:
        generate_dbt_dag_project(_load_umfs(), out_dir=project)
        db = project / "gold.duckdb"
        _load_raw_tables(db)

        for stage in ("parse", "compile"):
            res = _dbt(project, db, stage)
            assert res.returncode == 0, (
                f"dbt {stage} failed:\n{res.stdout}\n{res.stderr}"
            )

        manifest = json.loads((project / "target" / "manifest.json").read_text())

        # Model edges (parent_map) == the IR-predicted edges. Crucially the
        # qualified/alias refs land on the ingested models, and the external ref on
        # the external source node -- proving binding, not text coincidence.
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

        # The external source is declared with source_name 'external' (and is the
        # ONLY external source -- no phantom 'external' edges crept in elsewhere).
        ext_sources = {
            s["name"]: s["source_name"]
            for s in manifest.get("sources", {}).values()
            if s["source_name"] == "external"
        }
        assert ext_sources == {"extpipe__refs": "external"}, (
            f"external source edge mismatch: {ext_sources}"
        )
    finally:
        shutil.rmtree(project, ignore_errors=True)
