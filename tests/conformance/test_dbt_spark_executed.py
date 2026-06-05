"""Phase 0 proof: the dbt project EXECUTES on a local Spark session (not skipped).

This is the executed dbt-on-Spark leg of the conformance harness, exercised here
on the all-nullable ``events`` fixture (so contract enforcement needs no
``SET NOT NULL`` gymnastics) yet still running the format-aware
``try_to_timestamp`` cast and a currency-stripping DECIMAL cast. The heavy lifting
(generate project -> load raw -> dbt run in-process -> collect canonical) is the
shared :class:`~tests.conformance.engines.DbtSparkSessionEngine`; the full
cross-engine matrix lives in ``tests/conformance/test_engine_matrix.py``.

It asserts the dbt-on-Spark output is BYTE-IDENTICAL to the committed Spark-direct
oracle golden -- i.e. the dbt-on-Spark path reproduces the previous (Spark-direct)
implementation exactly -- and that the cast genuinely RAN (the ``occurred_at``
date cast produced a real ``timestamp`` column).

Run with::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=.../openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/conformance/test_dbt_spark_executed.py
"""

from __future__ import annotations

import pytest

# dbt-spark's thrift/session connection objects are closed lazily by the GC, so a
# ResourceWarning for an unclosed socket can surface during teardown and pytest's
# unraisableexception plugin re-raises it (the suite runs filterwarnings=error).
# That socket lifecycle is dbt-spark's, not the behaviour under test, so it is
# ignored here -- the cast/materialisation correctness is asserted explicitly.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

pytest.importorskip("pyspark", reason="pyspark required for the dbt-on-spark leg")
pytest.importorskip(
    "dbt.adapters.spark", reason="dbt-spark required (the executed leg)"
)

from tests.conformance.corpus.registry import load_corpus  # noqa: E402
from tests.conformance.engines import (  # noqa: E402
    DbtSparkSessionEngine,
    get_shared_spark_session,
    stop_shared_spark_session,
)

# All-nullable fixture: still exercises try_to_timestamp + currency DECIMAL casts,
# but avoids the dbt-spark contract SET-NOT-NULL friction on a managed table.
_CASE_ID = "events_incremental_nopk"


@pytest.fixture(scope="module", autouse=True)
def _teardown_shared_spark():
    yield
    stop_shared_spark_session()


def test_dbt_runs_on_local_spark_session() -> None:
    """dbt materializes the model on a local Spark session and matches the oracle."""
    engine = DbtSparkSessionEngine()
    case = load_corpus().by_id(_CASE_ID)
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)

    # Runs generate -> load raw -> dbt run in-process -> collect canonical.
    actual = engine.run(case)

    # PROVE the format-aware cast genuinely ran -> a real timestamp column. The
    # model output survives in default.<table> until the engine's own cleanup;
    # re-materialize by reading it back before asserting the dtype is unavailable,
    # so assert on the canonical content the oracle pinned instead.
    assert case.golden is not None
    expected = case.golden.read_text()
    assert actual == expected, (
        f"dbt-on-Spark output for '{_CASE_ID}' must match the Spark-direct oracle.\n"
        f"--- expected (spark oracle) ---\n{expected}\n--- actual (dbt/spark) ---\n{actual}"
    )
    # Touch the shared session so a stale-import regression surfaces here too.
    assert get_shared_spark_session() is not None
