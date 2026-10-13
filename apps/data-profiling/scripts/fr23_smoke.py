#!/usr/bin/env python
"""CLI smoke for FR-23 (unit path, no workspace required with mock runtime).

    cd apps/data-profiling
    PROFILER_RUNTIME=mock python scripts/fr23_smoke.py

Exit 0 on success. For empty-environment provision, pass --provision with a
Databricks warehouse (not the mock path).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiler.smoke import run_fr23_smoke  # noqa: E402


def main() -> int:
    summary = (__doc__ or "FR-23 smoke").splitlines()[0]
    p = argparse.ArgumentParser(description=summary)
    p.add_argument(
        "--registry",
        default="connections.yaml",
        help="Connection registry path (default connections.yaml)",
    )
    p.add_argument(
        "--provision",
        action="store_true",
        help="Run provision against a live warehouse (requires DATABRICKS_*)",
    )
    args = p.parse_args()
    executor = None
    if args.provision:
        from profiler.provision import DatabricksExecutor

        executor = DatabricksExecutor()
    return run_fr23_smoke(
        env=os.environ,
        registry_path=args.registry,
        executor=executor,
    )


if __name__ == "__main__":
    raise SystemExit(main())
