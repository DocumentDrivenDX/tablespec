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
