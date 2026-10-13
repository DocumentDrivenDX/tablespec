"""Unit gate for the 3-table onboarding authoring-reduction benchmark."""

# @covers product-completeness onboarding metric harness

from __future__ import annotations

import json
from pathlib import Path

from scripts.onboarding_benchmark import DEFAULT_SPECS, run_benchmark


def test_onboarding_benchmark_writes_metrics(tmp_path: Path) -> None:
    metrics = run_benchmark(
        specs=list(DEFAULT_SPECS),
        out_dir=tmp_path,
        dialect="duckdb",
        run_backbone=False,
    )

    assert metrics["table_count"] == 3
    assert set(metrics["tables"]) == {"member", "claims", "claim_enriched"}
    assert metrics["seconds"]["compile_umfs"] > 0
    assert metrics["seconds"]["total_automated"] > 0
    assert metrics["dbt_gold_project"] is True or metrics["ldp_project"] is not None

    path = Path(metrics["metrics_path"])
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["sample"].startswith("member")
    for name in ("member", "claims", "claim_enriched"):
        arts = loaded["artifacts_present"][name]
        assert arts["ingest_sql"]
        assert arts["suite_json"]
