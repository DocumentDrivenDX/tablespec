#!/usr/bin/env python
"""Path A demo: bootstrap runtime artifacts FROM EXISTING SPARK TABLES.

Reflects (and, by default, profiles) one or more existing Spark tables into a UMF
set, COMPILES that set to runtime artifacts, then runs the BACKBONE over the
compiled artifacts. Doubles as the asserted Path A pytest e2e
(``tests/e2e/test_bootstrap_from_tables.py`` imports :func:`main`).

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=... SPARK_LOCAL_IP=127.0.0.1 \
        uv run python scripts/bootstrap_from_tables.py --table <t> --out <dir>

Pipeline:
    spark.table(t)
      -> tablespec.bootstrap.bootstrap_from_tables
         (schema reflection + optional profiling + compile)
      -> tablespec.e2e.backbone.run_backbone    (execute the compiled artifacts)

The demo SEEDS each named table from a sibling ``<table>.raw.csv`` (the corpus
fixtures already on disk) so "an existing Spark table" is reproducible without a
warehouse. A real deployment would point ``--table`` at catalog tables instead and
drop ``--seed-from``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# A small default fixture set so the demo is runnable out of the box. The default
# seeds the ``member`` e2e fixture -- the same clean table the asserted Path A e2e
# (``tests/e2e/test_bootstrap_from_tables.py``) uses -- so the out-of-the-box demo
# validates to green (a profile-enriched suite over a fixture with profile-derived
# ``in_set`` checks on DECIMAL columns intentionally FAILS the raw-stage validation,
# which is correct dirt-catching behaviour but not a clean demo default).
_DEFAULT_SEEDS: dict[str, Path] = {
    "member": _REPO_ROOT / "tests/e2e/fixtures/member.raw.csv",
}


def _seed_table(spark, table: str, csv_path: Path) -> None:  # noqa: ANN001
    """Create an 'existing' Spark table from a CSV (header-inferred typed schema).

    Path A reflects a table that ALREADY exists; the demo materializes one from a
    corpus CSV. The ingest metadata columns (``_source_file`` / ``_load_ts``) are
    NOT part of the user table, so they are dropped here -- a reflected source table
    carries only business columns.
    """
    df = (
        spark.read.option("header", True)
        .option("inferSchema", True)
        .option("quote", '"')
        .option("escape", '"')
        .option("multiLine", True)
        .csv(str(csv_path))
    )
    for meta in ("_source_file", "_load_ts"):
        if meta in df.columns:
            df = df.drop(meta)
    spark.sql(f"DROP TABLE IF EXISTS {table}")
    df.write.mode("overwrite").saveAsTable(table)


def main(argv: list[str] | None = None) -> int:
    """Run the Path A bootstrap demo. Returns a process exit code (0 = ok)."""
    from tablespec.e2e.backbone import run_backbone
    from tablespec.bootstrap import bootstrap_from_tables

    args = _parse_args(argv)
    tables = list(args.table) if args.table else list(_DEFAULT_SEEDS)
    out_dir = Path(args.out).resolve()
    profile = not args.no_profile

    print("== Path A: bootstrap from existing tables ==")
    print(f"tables: {tables}  profile={profile}  backend={args.backend}")

    spark = _make_session(args.backend)

    # Seed the 'existing' tables from corpus CSVs so the demo is self-contained.
    seeds = _resolve_seeds(tables, args.seed_from)
    raw_batches: dict[str, list[Path]] = {}
    for table in tables:
        csv = seeds.get(table)
        if csv is None:
            raise SystemExit(
                f"no seed CSV for table {table!r}; pass --seed-from {table}=<csv> "
                "or use one of the default fixture tables"
            )
        _seed_table(spark, table, csv)
        raw_batches[table] = [csv]
        print(f"seeded table {table} from {csv}")

    # 1. REFLECT (+ optionally PROFILE) and COMPILE in one public step.
    artifacts = bootstrap_from_tables(
        spark,
        tables,
        out_dir,
        profile=profile,
        dialect=args.dialect,
    )
    print(f"\n-- compiled artifacts under {artifacts.root} --")
    _print_artifacts(artifacts)

    # 2. BACKBONE: execute the COMPILED artifacts.
    print(f"\n-- backbone ({args.backend}) consuming compiled artifacts --")
    result = run_backbone(
        artifacts, spark=spark, raw_batches=raw_batches, backend=args.backend
    )
    _print_stages(result)
    return 0 if result.ok else 1


def _resolve_seeds(tables: list[str], seed_from: list[str]) -> dict[str, Path]:
    seeds: dict[str, Path] = dict(_DEFAULT_SEEDS)
    for item in seed_from:
        table, _, csv = item.partition("=")
        seeds[table] = Path(csv).resolve()
    return {t: seeds[t] for t in tables if t in seeds}


# Sail's Rust server shuts down as soon as its ``SparkConnectServer`` handle is GC'd;
# root the handle here so it survives for the life of the demo process.
_SAIL_SERVERS: list = []


def _make_session(backend: str):  # noqa: ANN201
    if backend in ("sail", "duckdb"):
        from pysail.spark import SparkConnectServer

        from tests.conftest import make_sail_connect_session

        server = SparkConnectServer()
        server.start()
        _SAIL_SERVERS.append(server)  # keep alive past this function
        host, port = server.listening_address  # type: ignore[misc]
        return make_sail_connect_session(host, port, "bootstrap-from-tables")
    from tests.conformance.engines import get_shared_spark_session

    return get_shared_spark_session()


def _print_artifacts(artifacts) -> None:  # noqa: ANN001
    print(f"  manifest: {artifacts.manifest_path}")
    print(f"  source={artifacts.source} profile_enriched={artifacts.profile_enriched}")
    for name, ta in artifacts.tables.items():
        print(f"  [{name}]")
        print(f"    ingest sql      : {ta.ingest_sql}")
        print(f"    ddl             : {ta.ddl_sql}")
        print(f"    pyspark schema  : {ta.pyspark_schema}")
        print(f"    json schema     : {ta.json_schema}")
        print(f"    suite           : {ta.suite_json}")
        print(f"    dbt ingest proj : {ta.dbt_ingest_project}")
    if artifacts.ldp_project:
        print(f"  ldp project       : {artifacts.ldp_project}")


def _print_stages(result) -> None:  # noqa: ANN001
    for s in result.stages:
        mark = "ok " if s.ok else "FAIL"
        print(f"  [{mark}] {s.name}: {s.detail}")
    print(f"\nbackbone {'PASSED' if result.ok else 'FAILED'}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse ``--table`` (repeatable), ``--out``, ``--no-profile`` flags."""
    parser = argparse.ArgumentParser(
        description="Bootstrap runtime artifacts from existing Spark tables."
    )
    parser.add_argument(
        "--table",
        action="append",
        default=None,
        help="Existing table to reflect (repeatable). Default: member (fixture).",
    )
    parser.add_argument("--out", required=True, help="Compile output directory.")
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip profiling; emit a schema-only baseline suite.",
    )
    parser.add_argument(
        "--seed-from",
        action="append",
        default=[],
        help="table=csv: seed an 'existing' table from a CSV (repeatable).",
    )
    parser.add_argument(
        "--dialect", default="duckdb", help="Cast dialect for the dbt projects."
    )
    parser.add_argument(
        "--backend",
        default="spark",
        choices=["spark", "sail", "duckdb"],
        help="Backbone execution backend.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
