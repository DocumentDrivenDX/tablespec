"""Public Path B bootstrap facade (no Spark)."""

from __future__ import annotations

from pathlib import Path

from tablespec import bootstrap_from_specs

FIXTURES = Path(__file__).resolve().parents[1] / "e2e" / "fixtures"
SPECS = [
    FIXTURES / "member.umf.yaml",
    FIXTURES / "claims.umf.yaml",
    FIXTURES / "claim_enriched.umf.yaml",
]


def test_bootstrap_from_specs_public_api(tmp_path: Path) -> None:
    artifacts = bootstrap_from_specs(
        SPECS,
        tmp_path / "out",
        dialect="duckdb",
        gold_targets=["claim_enriched"],
    )
    assert artifacts.manifest_path.exists()
    assert artifacts.source == "specs"
    assert artifacts.table("member").ingest_sql.exists()
    assert artifacts.table("claim_enriched").gold_plan_sql is not None


def test_bootstrap_from_specs_accepts_split_dirs_and_json(tmp_path: Path) -> None:
    from tablespec import UMFLoader, load_umf_from_yaml

    loader = UMFLoader()
    split_dir = tmp_path / "tables" / "member"
    loader.migrate_legacy_inline_yaml(FIXTURES / "member.umf.yaml", split_dir)
    json_spec = tmp_path / "claims.json"
    loader.save_json(load_umf_from_yaml(FIXTURES / "claims.umf.yaml"), json_spec)

    artifacts = bootstrap_from_specs(
        [split_dir, json_spec],
        tmp_path / "out",
        dialect="duckdb",
    )
    assert artifacts.manifest_path.exists()
    assert artifacts.table("member").ingest_sql.exists()
    assert artifacts.table("claims").ingest_sql.exists()
