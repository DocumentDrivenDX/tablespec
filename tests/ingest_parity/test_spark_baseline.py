"""Phase 1 Spark baseline for raw->ingest parity (the conformance ORACLE).

For each ingest case in the unified corpus this test runs the
:class:`~tests.conformance.engines.SparkDirectEngine` -- the ORACLE: it loads the
UMF + all-STRING CSV batch(es), runs ``tablespec.generate_ingest_sql(umf)`` on a
real Delta-Spark session (an initial load plus, for multi-batch cases, the
dedup-latest + MERGE/append replay), canonicalizes the resulting
``ingested_<table>`` (see ``canonical.py``), and asserts it equals the committed
golden under ``tests/golden/ingest_parity/<case>.spark.expected.json``.

This Spark output is the source of truth the dbt/duckdb and dbt/spark paths are
checked against (see ``tests/conformance/test_engine_matrix.py`` for the full
cross-engine matrix). The engine adapter centralizes the load/run/collect logic
that used to be duplicated across the parity test modules.

Baseline assumption (IMPORTANT for parity): the session runs with
``spark.sql.ansi.enabled=false`` so malformed numeric/boolean/date inputs become
NULL instead of aborting the job (``cast_column_sql`` emits plain ``cast(...)``).

Run with the Spark-compatible JDK, e.g.::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/ingest_parity/test_spark_baseline.py
"""

from __future__ import annotations

import pytest

from tests.conformance.corpus.registry import Case, ingest_cases
from tests.conformance.engines import SparkDirectEngine, stop_shared_spark_session

pyspark = pytest.importorskip("pyspark", reason="PySpark required for Spark baseline")

# Spark's py4j gateway leaves sockets to be GC'd; under the repo-wide
# ``filterwarnings = error`` policy the resulting ResourceWarning would be
# escalated into a spurious failure. These are transport-cleanup artifacts, not
# defects in the ingest logic under test, so suppress them for this module only.
pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_ENGINE = SparkDirectEngine()
_INGEST_CASES = ingest_cases()


@pytest.fixture(scope="module", autouse=True)
def _teardown_shared_spark():
    yield
    stop_shared_spark_session()


@pytest.mark.slow
@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_spark_ingest_baseline(case: Case, request) -> None:
    reason = _ENGINE.availability(case)
    if reason is not None:
        pytest.skip(reason)

    assert case.golden is not None
    actual = _ENGINE.run(case)

    golden = case.golden
    if request.config.getoption("--update-golden", default=False):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)

    assert golden.exists(), (
        f"golden missing for '{case.id}': {golden}. Regenerate with --update-golden."
    )
    expected = golden.read_text()
    assert actual == expected, (
        f"Spark baseline mismatch for '{case.id}'.\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{actual}"
    )
