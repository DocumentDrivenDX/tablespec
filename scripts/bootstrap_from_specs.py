#!/usr/bin/env python
"""Path B demo: bootstrap runtime artifacts FROM UMF SPEC FILES.

Loads one or more UMF spec YAML files into a UMF set, COMPILES that set to runtime
artifacts, then runs the BACKBONE over the compiled artifacts. Doubles as the
asserted Path B pytest e2e (``tests/e2e/test_bootstrap_from_specs.py`` imports
:func:`main`).

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=... SPARK_LOCAL_IP=127.0.0.1 \
        uv run python scripts/bootstrap_from_specs.py --spec <a.yaml> --out <dir>

Pipeline:
    load_umf_from_yaml(spec)
      -> tablespec.e2e.paths.umfs_from_specs   (Path B entry point)
      -> tablespec.e2e.compile.compile_umfs     (persist artifacts + manifest)
      -> tablespec.e2e.backbone.run_backbone    (execute the compiled artifacts)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable so the conformance facades (under tests/) resolve
# when this script is run directly (not via pytest).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _infer_batches(spec_paths: list[Path]) -> dict[str, list[Path]]:
    """Locate each spec's ordered raw CSV batches by the corpus naming convention.

    For ``<table>.umf.yaml`` the batches are, in order:
      * every ``<table>.batchN.csv`` (sorted), else
      * the single ``<table>.raw.csv``.
    A spec with no sibling CSV contributes no batches (compile still runs).
    """
    batches: dict[str, list[Path]] = {}
    for spec in spec_paths:
        stem = spec.name
        for suffix in (".umf.yaml", ".yaml", ".yml"):
            if stem.endswith(suffix):
                table = stem[: -len(suffix)]
                break
        else:  # pragma: no cover - argparse guards extensions
            table = spec.stem
        d = spec.parent
        multi = sorted(d.glob(f"{table}.batch*.csv"))
        if multi:
            batches[table] = multi
        elif (d / f"{table}.raw.csv").exists():
            batches[table] = [d / f"{table}.raw.csv"]
    return batches


def main(argv: list[str] | None = None) -> int:
    """Run the Path B bootstrap demo. Returns a process exit code (0 = ok)."""
    from tablespec.e2e.backbone import run_backbone
    from tablespec.e2e.compile import compile_umfs
    from tablespec.e2e.paths import umfs_from_specs

    args = _parse_args(argv)
    spec_paths = [Path(s).resolve() for s in args.spec]
    out_dir = Path(args.out).resolve()

    print("== Path B: bootstrap from specs ==")
    print(f"specs: {[str(p) for p in spec_paths]}")

    # 1. LOAD the UMF set (Path B entry point).
    umfs = umfs_from_specs(list(spec_paths))
    gold_targets = [u.table_name for u in umfs if _has_gold(u)]
    print(f"loaded {len(umfs)} UMF(s): {[u.table_name for u in umfs]}")
    if gold_targets:
        print(f"gold targets: {gold_targets}")

    # 2. COMPILE -> persist artifacts + manifest.
    artifacts = compile_umfs(
        umfs,
        out_dir,
        source="specs",
        dialect=args.dialect,
        gold_targets=gold_targets,
    )
    print(f"\n-- compiled artifacts under {artifacts.root} --")
    _print_artifacts(artifacts)

    # 3. BACKBONE: execute the COMPILED artifacts.
    raw_batches = (
        {args.table: [Path(b).resolve() for b in args.batch]}
        if args.batch and args.table
        else _infer_batches(spec_paths)
    )
    if not raw_batches:
        print("\n(no raw batches found beside the specs; ran compile only)")
        return 0

    spark = _make_session(args.backend)
    print(f"\n-- backbone ({args.backend}) consuming compiled artifacts --")
    result = run_backbone(
        artifacts, spark=spark, raw_batches=raw_batches, backend=args.backend
    )
    _print_stages(result)
    return 0 if result.ok else 1


def _has_gold(umf) -> bool:  # noqa: ANN001
    """Whether *umf* derives a gold table (has any column derivation)."""
    return any(getattr(c, "derivation", None) is not None for c in umf.columns)


# Sail's Rust server shuts down as soon as its ``SparkConnectServer`` handle is GC'd;
# root the handle here so it survives for the life of the demo process.
_SAIL_SERVERS: list = []


def _make_session(backend: str):  # noqa: ANN201
    """Build the execution session for *backend* (reuses the conformance facades).

    For ``sail`` / ``duckdb`` (no JVM) a Sail Spark Connect session is used (the
    DuckDB backbone needs a session only as the GX validation substrate). For
    ``spark`` the classic JVM session is adopted via the conformance facade.
    """
    if backend in ("sail", "duckdb"):
        from pysail.spark import SparkConnectServer

        from tests.conftest import make_sail_connect_session

        server = SparkConnectServer()
        server.start()
        _SAIL_SERVERS.append(server)  # keep alive past this function
        host, port = server.listening_address  # type: ignore[misc]
        return make_sail_connect_session(host, port, "bootstrap-from-specs")
    from tests.conformance.engines import get_shared_spark_session

    return get_shared_spark_session()


def _print_artifacts(artifacts) -> None:  # noqa: ANN001
    print(f"  manifest: {artifacts.manifest_path}")
    for name, ta in artifacts.tables.items():
        print(f"  [{name}]")
        print(f"    ingest sql      : {ta.ingest_sql}")
        print(f"    ddl             : {ta.ddl_sql}")
        print(f"    pyspark schema  : {ta.pyspark_schema}")
        print(f"    json schema     : {ta.json_schema}")
        print(f"    suite           : {ta.suite_json}")
        print(f"    dbt ingest proj : {ta.dbt_ingest_project}")
        if ta.gold_plan_sql:
            print(f"    gold plan       : {ta.gold_plan_sql}")
    if artifacts.dbt_gold_project:
        print(f"  dbt gold project  : {artifacts.dbt_gold_project}")
    if artifacts.ldp_project:
        print(f"  ldp project       : {artifacts.ldp_project}")


def _print_stages(result) -> None:  # noqa: ANN001
    for s in result.stages:
        mark = "ok " if s.ok else "FAIL"
        print(f"  [{mark}] {s.name}: {s.detail}")
    print(f"\nbackbone {'PASSED' if result.ok else 'FAILED'}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse ``--spec`` (repeatable), ``--batch``, ``--out`` flags."""
    parser = argparse.ArgumentParser(description="Bootstrap runtime artifacts from UMF specs.")
    parser.add_argument("--spec", action="append", required=True, help="UMF spec YAML (repeatable).")
    parser.add_argument("--out", required=True, help="Compile output directory.")
    parser.add_argument("--table", help="Table name the --batch CSVs belong to.")
    parser.add_argument("--batch", action="append", default=[], help="Raw CSV batch (repeatable).")
    parser.add_argument("--dialect", default="duckdb", help="Cast dialect for the dbt projects.")
    parser.add_argument(
        "--backend",
        default="spark",
        choices=["spark", "sail", "duckdb"],
        help="Backbone execution backend.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
