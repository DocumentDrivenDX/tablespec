"""spark_only e2e matrix: the COMPILE -> BACKBONE bootstrap on classic JVM Spark.

The classic-Spark leg of the platform matrix. It compiles the SAME fixture UMF set
and runs the SAME backbone as the no_spark lane
(``tests/e2e/test_e2e_matrix_no_spark.py``), but executes the COMPILED Delta MERGE
ingest SQL on a JVM Spark + Delta session and validates via classic GX. The shared
per-leg assertions live in ``tests/e2e/_matrix`` so both lanes assert the identical
contract.

Marked ``spark_only`` (a JVM-backed session is required) and adopts the
session-scoped ``spark_session`` fixture so the backbone reuses the fixture-owned
session (cleanly torn down at session end). Spark's py4j gateway leaves transient
sockets for lazy GC, which ``filterwarnings = error`` would surface as unraisable
ResourceWarnings at a test boundary -- pure session noise, downgraded here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e import _matrix

pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]


def test_backbone_green(tmp_path: Path, spark_session) -> None:  # noqa: ANN001
    """Compile the fixture set, run the whole backbone on classic Spark, assert green."""
    artifacts = _matrix.compile_fixture_set(tmp_path / "out")
    _matrix.assert_artifacts_runtime_loadable(artifacts)
    _matrix.run_full_backbone(artifacts, backend="spark", spark=spark_session)


def test_ingest_byte_identical_to_golden(tmp_path: Path, spark_session) -> None:  # noqa: ANN001
    """Classic-Spark canonical ingest is byte-identical to the committed golden.

    The golden is the SAME cross-engine canonical the no_spark lane asserts for Sail
    and DuckDB, so this ties the classic-Spark leg to identical bytes (the parity
    triangle spark == sail == duckdb) without importing across lanes.
    """
    canon = _matrix.canonical_ingest("spark", spark=spark_session, out_dir=tmp_path / "spark")
    _matrix.assert_canonical_matches_golden("spark", canon)
