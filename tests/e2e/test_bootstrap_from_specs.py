"""Asserted Path B e2e: specs -> compile -> backbone (consumes only artifacts).

Drives the same ``scripts/bootstrap_from_specs.main`` the demo runs and asserts the
compiled artifact tree + every backbone stage. The backbone consumes ONLY the
persisted artifacts (it loads them from disk via ``CompiledArtifacts.load``), so a
green run proves the compile output is a self-sufficient runtime contract.
"""

# Bootstrap Path B and compile-orchestrator coverage.
# @covers US-023-AC1
# @covers US-023-AC2
# @covers US-023-AC3
# @covers US-023-AC4
# @covers US-023-AC5
# @covers US-023-AC6
# @covers US-024-AC1
# @covers US-024-AC2

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


def _compile_specs(out_dir: Path, *, dialect: str) -> CompiledArtifacts:
    umfs = umfs_from_specs(SPECS)
    return compile_umfs(
        umfs,
        out_dir,
        source="specs",
        dialect=dialect,
        gold_targets=["claim_enriched"],
    )


def test_compile_umfs_accepts_databricks_dialect(tmp_path: Path) -> None:
    """The orchestrator writes every pinned artifact + a loadable manifest."""
    artifacts = _compile_specs(tmp_path, dialect="databricks")

    # manifest + per-table bundles exist on disk.
    assert artifacts.manifest_path.exists()
    assert artifacts.dialect == "databricks"
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
    assert reloaded.dialect == "databricks"
    assert set(reloaded.tables) == {"member", "claims", "claim_enriched"}


def test_compile_umfs_preserves_public_dialect_in_manifest(
    tmp_path: Path,
) -> None:
    """The manifest records the public dialect while Spark-family SQL stays shared."""
    spark_artifacts = _compile_specs(tmp_path / "spark", dialect="spark")
    databricks_artifacts = _compile_specs(tmp_path / "databricks", dialect="databricks")

    spark_manifest = json.loads(spark_artifacts.manifest_path.read_text())
    databricks_manifest = json.loads(databricks_artifacts.manifest_path.read_text())
    assert spark_manifest["dialect"] == "spark"
    assert databricks_manifest["dialect"] == "databricks"

    # The public dialect is preserved in the manifest, but the shared Spark-family
    # emitters stay byte-identical for the downstream SQL consumers.
    assert (
        spark_artifacts.table("member").ingest_sql.read_text()
        == databricks_artifacts.table("member").ingest_sql.read_text()
    )
    assert (
        spark_artifacts.table("member").dbt_ingest_project is not None
        and databricks_artifacts.table("member").dbt_ingest_project is not None
    )
    assert (
        spark_artifacts.table("member").dbt_ingest_project / "models" / "member.sql"
    ).read_text() == (
        databricks_artifacts.table("member").dbt_ingest_project
        / "models"
        / "member.sql"
    ).read_text()
    assert spark_artifacts.ldp_project is not None
    assert databricks_artifacts.ldp_project is not None
    assert (
        spark_artifacts.ldp_project / "ingested" / "ingested_member.sql"
    ).read_text() == (
        databricks_artifacts.ldp_project / "ingested" / "ingested_member.sql"
    ).read_text()


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
