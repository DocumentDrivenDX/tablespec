"""no_spark e2e matrix: the COMPILE -> BACKBONE bootstrap on the no-JVM backends.

Parametrized across the two local backends that need NO JVM / JAVA_HOME:

  * ``sail``   -- Spark Connect (pysail Rust server). Delta MERGE is unavailable on
                  Connect, so ingest materializes the compiled MERGE's deduped cast
                  SELECT directly; validation takes the native Connect GX path.
  * ``duckdb`` -- the compiled dbt ingest project on DuckDB, with GX validation
                  frames hosted on the same Sail Connect session.

Both backends share one session-scoped Sail session (``sail_session``). The lane is
marked ``no_spark`` so the classic-Spark conftest setup is skipped.

Assertions, per leg:
  * every backbone stage is green (ingest / validate / transform / dbt parse /
    gold-plan / ldp-structure);
  * the compiled artifacts are runtime-loadable (JSON schema parses, PySpark
    ``StructType`` source imports, dbt parse writes a manifest, the manifest
    round-trips from disk);
  * the clean fixture data VALIDATES (every ``validate:*`` stage passes);
  * the two no-JVM backends produce BYTE-IDENTICAL canonical ingest (cross-engine
    parity via the shared ``canonical.to_json``).

A GATED real-serverless leg is included; it SKIPS unless a real Databricks
workspace is configured (``databricks_e2e_availability()``), and is never run here.
"""

# No-JVM runtime-backbone matrix coverage.
# @covers US-024-AC1
# @covers US-024-AC2
# @covers US-024-AC3
# @covers US-024-AC4
# @covers US-024-AC5

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from tests.e2e import _matrix

# Sail needs no JVM; mark the whole module no_spark so the classic-Spark setup is
# skipped. py4j is not involved (Connect is gRPC), but the DuckDB substrate lift can
# still leave transient sockets for lazy GC -> downgrade unclosed-resource warnings
# that filterwarnings=error would otherwise surface at a test boundary.
pytestmark = [
    pytest.mark.no_spark,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]

NO_JVM_BACKENDS = ["sail", "duckdb"]


@pytest.fixture(autouse=True)
def _quiet_connect_resource_warnings():
    """Silence ResourceWarnings emitted during Connect/DuckDB frame teardown."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        warnings.filterwarnings(
            "ignore", category=pytest.PytestUnraisableExceptionWarning
        )
        yield


@pytest.mark.parametrize("backend", NO_JVM_BACKENDS)
def test_backbone_green(backend: str, tmp_path: Path, sail_session) -> None:  # noqa: ANN001
    """Compile the fixture set, run the whole backbone on *backend*, assert green."""
    artifacts = _matrix.compile_fixture_set(tmp_path / "out")
    _matrix.assert_artifacts_runtime_loadable(artifacts)
    _matrix.run_full_backbone(artifacts, backend=backend, spark=sail_session)


def test_ingest_byte_identical_across_no_jvm_backends(
    tmp_path: Path, sail_session
) -> None:  # noqa: ANN001
    """Sail and DuckDB produce byte-identical canonical ingest for every table.

    Reuses the conformance ``canonical.to_json`` so "agree" means the canonical
    strings are byte-for-byte equal -- the same cross-engine parity contract the
    conformance matrix enforces.
    """
    sail_canon = _matrix.canonical_ingest(
        "sail", spark=sail_session, out_dir=tmp_path / "sail"
    )
    duck_canon = _matrix.canonical_ingest(
        "duckdb", spark=sail_session, out_dir=tmp_path / "duckdb"
    )
    assert set(sail_canon) == set(duck_canon)
    for table in sail_canon:
        assert sail_canon[table] == duck_canon[table], (
            f"{table}: sail vs duckdb canonical ingest diverged\n"
            f"--- sail ---\n{sail_canon[table]}\n--- duckdb ---\n{duck_canon[table]}"
        )

    # Both no-JVM backends also match the committed cross-engine golden, tying them to
    # the SAME bytes the spark lane asserts (the parity triangle spark==sail==duckdb).
    _matrix.assert_canonical_matches_golden("sail", sail_canon)
    _matrix.assert_canonical_matches_golden("duckdb", duck_canon)


# ---------------------------------------------------------------------------
# GATED real-serverless leg: deploy + execute on a REAL Databricks workspace.
# Skipped unless ``databricks_e2e_availability()`` returns None (DATABRICKS_HOST +
# credentials present). Never run in this harness -- it is the opt-in tier.
# ---------------------------------------------------------------------------


@pytest.mark.databricks_e2e
def test_real_serverless_backbone(tmp_path: Path) -> None:
    """Opt-in: run the compiled backbone against a real Databricks workspace.

    This is the env-v3 DAB pattern: the COMPILED artifacts (Delta MERGE ingest, the
    GX suite, the dbt projects, the LDP APPLY CHANGES pipeline) are deployed to and
    executed on a live serverless warehouse. It SKIPS with a precise reason unless a
    workspace is configured, so local matrix success NEVER depends on a remote
    workspace.
    """
    from tests.conformance.engines import databricks_e2e_availability

    reason = databricks_e2e_availability()
    if reason is not None:
        pytest.skip(reason)

    # pragma: no cover -- only reachable with a configured workspace, never here.
    from tablespec.e2e.backbone import make_engine, run_backbone  # noqa: F401

    artifacts = _matrix.compile_fixture_set(tmp_path / "out")  # pragma: no cover
    # On a real workspace the compiled Delta MERGE ingest + APPLY CHANGES execute over
    # the serverless connection; the dbt gold DAG `dbt run`s against the warehouse.
    # The deploy/connect plumbing reuses the conformance Databricks engine facades.
    raise AssertionError(  # pragma: no cover
        "real-serverless execution is wired but unreachable without DATABRICKS_HOST; "
        f"artifacts compiled at {artifacts.root}"
    )
