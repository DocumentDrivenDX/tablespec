"""Asserted Path B e2e: specs -> compile -> backbone (consumes only artifacts).

Drives the same ``scripts/bootstrap_from_specs.main`` the demo runs and asserts the
compiled artifact tree + every backbone stage. The backbone consumes ONLY the
persisted artifacts (it loads them from disk via ``CompiledArtifacts.load``), so a
green run proves the compile output is a self-sufficient runtime contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import bootstrap_from_specs
from tablespec.e2e.compile import compile_umfs
from tablespec.e2e.manifest import CompiledArtifacts
from tablespec.e2e.paths import umfs_from_specs

# See test_bootstrap_from_tables: Spark's py4j gateway leaves transient sockets for
# lazy GC, which ``filterwarnings = error`` would surface as unraisable
# ResourceWarnings at a test boundary -- pure session noise, downgraded here.
pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPECS = [
    FIXTURES / "member.umf.yaml",
    FIXTURES / "claims.umf.yaml",
    FIXTURES / "claim_enriched.umf.yaml",
]


def test_compile_persists_every_seam(tmp_path: Path) -> None:
    """The orchestrator writes every pinned artifact + a loadable manifest."""
    umfs = umfs_from_specs(SPECS)
    artifacts = compile_umfs(
        umfs, tmp_path, source="specs", gold_targets=["claim_enriched"]
    )

    # manifest + per-table bundles exist on disk.
    assert artifacts.manifest_path.exists()
    for name in ("member", "claims", "claim_enriched"):
        ta = artifacts.table(name)
        for p in (
            ta.umf_snapshot,
            ta.ingest_sql,
            ta.ddl_sql,
            ta.pyspark_schema,
            ta.json_schema,
            ta.suite_json,
        ):
            assert p.exists(), f"{name}: missing {p}"
        assert ta.dbt_ingest_project is not None
        assert (ta.dbt_ingest_project / "dbt_project.yml").exists()

    # gold-target-only artifact.
    assert artifacts.table("claim_enriched").gold_plan_sql is not None
    assert artifacts.table("claim_enriched").gold_plan_sql.exists()
    assert artifacts.table("member").gold_plan_sql is None

    # whole-compile projects.
    assert artifacts.dbt_gold_project is not None
    assert (artifacts.dbt_gold_project / "dbt_project.yml").exists()
    assert artifacts.ldp_project is not None
    assert (artifacts.ldp_project / "ingested" / "ingested_member.sql").exists()

    # the suite is the COMPILED expectation list (raw + ingested co-mingled).
    suite = json.loads(artifacts.table("member").suite_json.read_text())
    assert isinstance(suite, list) and suite

    # round-trips purely from disk.
    reloaded = CompiledArtifacts.load(tmp_path)
    assert reloaded.source == "specs"
    assert set(reloaded.tables) == {"member", "claims", "claim_enriched"}


def test_main_runs_backbone_green(tmp_path: Path, spark_session) -> None:  # noqa: ANN001
    """The demo entry point compiles + runs the backbone to a green result.

    Requests the session-scoped ``spark_session`` fixture so the backbone ADOPTS the
    fixture-owned session (``get_shared_spark_session`` reuses any active session and
    never stops it), letting the fixture tear it down cleanly at session end.
    """
    out = tmp_path / "out"
    rc = bootstrap_from_specs.main(
        [
            "--spec",
            str(SPECS[0]),
            "--spec",
            str(SPECS[1]),
            "--spec",
            str(SPECS[2]),
            "--out",
            str(out),
            "--backend",
            "spark",
        ]
    )
    assert rc == 0, "Path B backbone must pass end-to-end on the local Spark backend"
    # The compile output is left on disk for inspection / re-run.
    assert (out / "manifest.json").exists()
