"""Shared fixtures for the e2e bootstrap platform matrix.

The matrix runs the COMPILE -> BACKBONE bootstrap across three local execution
backends:

  * ``spark``  -- classic JVM Spark + Delta (the ``spark_only`` lane;
                  ``tests/e2e/test_e2e_matrix_spark.py``).
  * ``sail``   -- Spark Connect via pysail's Rust server, NO JVM (the ``no_spark``
                  lane).
  * ``duckdb`` -- the compiled dbt ingest project on DuckDB, with the GX validation
                  frames hosted on a Sail Connect session (so this lane needs NO JVM
                  either and joins the ``no_spark`` lane).

A single Sail Connect server/session is shared (session scope) by both no-JVM
backends. The server object MUST be held for the whole session: pysail shuts the
Rust server down as soon as the ``SparkConnectServer`` handle is GC'd, so a
function-local handle would tear the server down mid-test (this is exactly the bug
the demo scripts had until the server was rooted in a long-lived scope).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPECS = [
    FIXTURES / "member.umf.yaml",
    FIXTURES / "claims.umf.yaml",
    FIXTURES / "claim_enriched.umf.yaml",
]
GOLD_TARGETS = ["claim_enriched"]
#: Per-table ordered raw CSV batches (clean source extracts -- no ingest metadata).
RAW_BATCHES: dict[str, list[Path]] = {
    "member": [FIXTURES / "member.raw.csv"],
    "claims": [FIXTURES / "claims.raw.csv"],
}

try:
    from pysail.spark import SparkConnectServer  # noqa: F401

    _HAS_SAIL = True
except ImportError:  # pragma: no cover - pysail is a dev-group dependency
    _HAS_SAIL = False


@pytest.fixture(scope="session")
def sail_session():
    """Session-scoped Sail (Spark Connect) session backed by a long-lived server.

    No JVM / JAVA_HOME is required. The ``SparkConnectServer`` handle is held for the
    whole session so pysail does not GC-shutdown the Rust server between tests.
    """
    if not _HAS_SAIL:  # pragma: no cover - pysail always present in the dev env
        pytest.skip("pysail not available -- install the dev group")

    from pysail.spark import SparkConnectServer

    from tests.conftest import make_sail_connect_session

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address  # type: ignore[misc]
        session = make_sail_connect_session(host, port, "tablespec-e2e-matrix")
        try:
            yield session
        finally:
            try:
                session.stop()
            except Exception:  # pragma: no cover - teardown best-effort
                pass
            try:
                server.stop()
            except Exception:  # pragma: no cover - teardown best-effort
                pass
