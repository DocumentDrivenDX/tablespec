#!/usr/bin/env python
"""3-table onboarding authoring-reduction benchmark (PRD success metric).

Times the *automated* Path B workflow used as the tablespec side of the
50% manual-authoring reduction claim:

    load 3 UMF specs → compile_umfs → (optional) backbone green stages

A hand-authored baseline is *not* executed here (that requires human
timing). This script records the automated path so the reduction formula:

    reduction = 1 - (t_tablespec / t_manual)

has a reproducible automated numerator. The denominator protocol is
documented in ``docs/guide/onboarding-benchmark.md``.

Usage::

    uv run python scripts/onboarding_benchmark.py --out /tmp/onboard-metrics

Exit 0 on success; writes ``onboarding_benchmark.json`` under ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Default 3-table onboarding sample (same fixtures as Path B e2e).
DEFAULT_SPECS = [
    _REPO_ROOT / "tests/e2e/fixtures/member.umf.yaml",
    _REPO_ROOT / "tests/e2e/fixtures/claims.umf.yaml",
    _REPO_ROOT / "tests/e2e/fixtures/claim_enriched.umf.yaml",
]


def run_benchmark(
    *,
    specs: list[Path],
    out_dir: Path,
    dialect: str = "duckdb",
    run_backbone: bool = False,
) -> dict:
    """Run the automated onboarding path and return a metrics dict."""
    from tablespec.e2e.compile import compile_umfs
    from tablespec.e2e.paths import umfs_from_specs

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    umfs = umfs_from_specs(specs)
    t_load = time.perf_counter() - t0

    t1 = time.perf_counter()
    artifacts = compile_umfs(
        umfs,
        out_dir / "artifacts",
        source="specs",
        dialect=dialect,
        gold_targets=["claim_enriched"],
    )
    t_compile = time.perf_counter() - t1

    tables = sorted(artifacts.tables.keys())
    per_table: dict[str, dict[str, bool]] = {}
    for name in tables:
        ta = artifacts.table(name)
        per_table[name] = {
            "umf_snapshot": ta.umf_snapshot.exists(),
            "ingest_sql": ta.ingest_sql.exists(),
            "ddl_sql": ta.ddl_sql.exists(),
            "pyspark_schema": ta.pyspark_schema.exists(),
            "json_schema": ta.json_schema.exists(),
            "suite_json": ta.suite_json.exists(),
            "dbt_ingest": ta.dbt_ingest_project is not None
            and (ta.dbt_ingest_project / "dbt_project.yml").exists(),
        }

    backbone_s: float | None = None
    backbone_ok: bool | None = None
    if run_backbone:
        from tablespec.e2e.backbone import run_backbone

        t2 = time.perf_counter()
        # Path B e2e supplies batches via fixture convention; optional here.
        result = run_backbone(artifacts, backend="duckdb", batches={})
        backbone_s = time.perf_counter() - t2
        backbone_ok = result.ok if hasattr(result, "ok") else True

    total = t_load + t_compile + (backbone_s or 0.0)
    metrics = {
        "sample": "member + claims + claim_enriched (tests/e2e/fixtures)",
        "table_count": len(tables),
        "tables": tables,
        "dialect": dialect,
        "seconds": {
            "load_specs": round(t_load, 4),
            "compile_umfs": round(t_compile, 4),
            "backbone": None if backbone_s is None else round(backbone_s, 4),
            "total_automated": round(total, 4),
        },
        "artifacts_present": per_table,
        "manifest": str(artifacts.manifest_path),
        "dbt_gold_project": artifacts.dbt_gold_project is not None,
        "ldp_project": artifacts.ldp_project is not None,
        "backbone_ok": backbone_ok,
        "manual_baseline_protocol": (
            "docs/guide/onboarding-benchmark.md#manual-baseline-protocol"
        ),
        "reduction_formula": "1 - (seconds.total_automated / t_manual_minutes*60)",
    }

    out_path = out_dir / "onboarding_benchmark.json"
    out_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    metrics["metrics_path"] = str(out_path)
    return metrics


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/tablespec-onboarding-benchmark"),
        help="Output directory for metrics + compiled artifacts",
    )
    p.add_argument(
        "--dialect",
        default="duckdb",
        help="Compile dialect (default duckdb for local runs)",
    )
    p.add_argument(
        "--backbone",
        action="store_true",
        help="Also time backbone (requires batches; experimental)",
    )
    p.add_argument(
        "--spec",
        action="append",
        type=Path,
        dest="specs",
        help="UMF spec path (repeatable); default is the 3-table e2e sample",
    )
    args = p.parse_args(argv)
    specs = args.specs or DEFAULT_SPECS
    for s in specs:
        if not s.exists():
            print(f"missing spec: {s}", file=sys.stderr)
            return 2
    metrics = run_benchmark(
        specs=list(specs),
        out_dir=args.out,
        dialect=args.dialect,
        run_backbone=args.backbone,
    )
    print(json.dumps(metrics, indent=2))
    print(f"\nwrote {metrics['metrics_path']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
