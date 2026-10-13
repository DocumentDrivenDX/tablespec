"""Provision the app's metadata home (FEAT-034 PROV-01..04).

The explicit deployment step from ADR-019 decision 3: create or verify the
schema, the output volume, and the governance tables at the declared location,
then report what was created and what already existed. Safe to re-run — a
second run against a provisioned environment reports no changes.

Run it once per environment before first app start:

    python scripts/provision.py \
        --catalog my_catalog --schema my_profiler --volume ab_runs \
        --warehouse-id <sql-warehouse-id>

With no flags it provisions whatever `resolve_config()` resolves, so a
deployment that already exports PROFILER_METADATA_* needs no arguments:

    python scripts/provision.py

Exit codes: 0 on success (whether or not anything changed), 1 on failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/provision.py` from the app root without an
# install step; the app is deployed as a source tree, not a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiler.config import resolve_config  # noqa: E402
from profiler.provision import provision  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--catalog", help="Metadata catalog (overrides resolved config)")
    p.add_argument("--schema", help="Metadata schema (overrides resolved config)")
    p.add_argument("--volume", help="Output volume (overrides resolved config)")
    p.add_argument("--warehouse-id", help="SQL warehouse used to run the DDL")
    p.add_argument(
        "--grant-to",
        default="account users",
        help="Principal granted SELECT on the governance tables "
        "(empty string to skip granting)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved target and exit without changing anything",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    config = resolve_config()
    overrides = {
        k: v
        for k, v in (
            ("metadata_catalog", args.catalog),
            ("metadata_schema", args.schema),
            ("output_volume", args.volume),
            ("warehouse_id", args.warehouse_id),
        )
        if v
    }
    if overrides:
        from dataclasses import replace

        # A CLI flag is the most explicit input there is, so it outranks the
        # deployment tier it is overriding.
        config = replace(
            config,
            **overrides,
            sources={**config.sources, **{k: "cli" for k in overrides}},
        )

    print(f"Target metadata home: {config.metadata_fqn}")
    print(f"Output volume:        {config.output_volume_path}")
    for setting in ("metadata_catalog", "metadata_schema", "output_volume"):
        print(f"  {setting:18} <- {config.source_of(setting)}")

    if args.dry_run:
        print("\nDry run — nothing was changed.")
        return 0

    if not config.warehouse_id:
        print(
            "\nERROR: no SQL warehouse resolved. Provisioning runs DDL through a "
            "warehouse.\nSet DATABRICKS_WAREHOUSE_ID or pass --warehouse-id.",
            file=sys.stderr,
        )
        return 1

    try:
        report = provision(config, grant_to=args.grant_to or None)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: provisioning failed: {exc}", file=sys.stderr)
        return 1

    print()
    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
