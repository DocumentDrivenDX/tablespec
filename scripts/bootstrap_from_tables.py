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
      -> tablespec.e2e.paths.umfs_from_tables  (SparkToUmfMapper [+ profiler])
      -> tablespec.e2e.compile.compile_umfs     (persist artifacts + manifest)
      -> tablespec.e2e.backbone.run_backbone    (execute the compiled artifacts)
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    """Run the Path A bootstrap demo. Returns a process exit code (0 = ok)."""
    raise NotImplementedError


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse ``--table`` (repeatable), ``--out``, ``--no-profile`` flags."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
