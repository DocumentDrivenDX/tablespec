"""The EXECUTED cross-engine conformance matrix (Phase 3).

ONE parametrized test drives the product ``(case x engine)`` over the unified
corpus (``tests/conformance/corpus/cases.yaml``) and the locally-executable engine
adapters (``tests/conformance/engines.py``). For each pair it asserts:

  * **A. Golden conformance** -- ``canonical(engine.run(case)) == case.golden``,
    byte-identical at the case's pinned ``ts_precision``. The golden is the
    SparkDirect oracle output for ingest cases and the Spark-backend
    ``SQLPlanGeneratorGold`` output for gold cases (the "previous implementation").
  * **B. Pairwise agreement** -- a separate test asserts every two AVAILABLE
    engines for a case produce byte-identical canonical output, so a
    shared-golden-but-divergent-render bug is localized to the engine pair.

Engines that cannot run a case-tier in this environment are ``skip``ped with an
explicit, visible reason (never silently passed). Run under the Spark JDK::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv \
      JAVA_HOME=/home/linuxbrew/.linuxbrew/opt/openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/conformance/test_engine_matrix.py

Regenerate the (pending) gold goldens with ``--update-golden`` (the Spark backend
of the gold oracle writes them).
"""

from __future__ import annotations

import pytest

from tests.conformance.corpus.registry import Case, load_cases
from tests.conformance.engines import (
    Engine,
    SQLPlanGeneratorGoldEngine,
    all_engines,
    stop_shared_spark_session,
)

# The matrix touches Spark (JVM) engines; mark slow + suppress the py4j socket
# ResourceWarnings the suite-wide ``filterwarnings = error`` would otherwise
# escalate into spurious failures (transport cleanup, not behaviour under test).
pytestmark = [
    pytest.mark.slow,
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_CASES = load_cases()
_ENGINES = all_engines()

# Result-parity matrix pairs: only (engine, case) the engine declares it handles.
_MATRIX = [
    (engine, case) for case in _CASES for engine in _ENGINES if engine.handles(case)
]
_MATRIX_IDS = [f"{e.name}-{c.id}" for e, c in _MATRIX]


@pytest.fixture(scope="module", autouse=True)
def _teardown_shared_spark():
    """Stop the process-wide Spark session after the whole module runs."""
    yield
    stop_shared_spark_session()


def _golden_for(case: Case):
    """Resolve a case's golden path (ingest + gold both store under golden/)."""
    if case.golden is not None:
        return case.golden
    # Pending gold cases declare no golden path; derive the canonical location.
    from tests.conformance.corpus.registry import REPO_ROOT

    return (
        REPO_ROOT
        / "tests"
        / "golden"
        / "ingest_parity"
        / f"{case.id}.spark.expected.json"
    )


def _is_oracle(engine: Engine, case: Case) -> bool:
    """Whether *engine* is THE oracle that defines *case*'s golden.

    Ingest goldens come from SparkDirect; gold goldens come from the Spark backend
    of SQLPlanGeneratorGold. Only the oracle may write the golden under
    ``--update-golden`` (every other engine must MATCH it).
    """
    if case.kind == "ingest":
        return engine.name == "SparkDirect"
    return isinstance(engine, SQLPlanGeneratorGoldEngine) and engine.backend == "spark"


@pytest.mark.parametrize(("engine", "case"), _MATRIX, ids=_MATRIX_IDS)
def test_engine_matches_golden(engine: Engine, case: Case, request) -> None:
    """A. Golden conformance: every available engine reproduces the case golden."""
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(f"{engine.name} unavailable for '{case.id}': {reason}")

    actual = engine.run(case)
    golden = _golden_for(case)

    update = request.config.getoption("--update-golden", default=False)
    if update and _is_oracle(engine, case):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)

    assert golden.exists(), (
        f"golden missing for '{case.id}': {golden}. Regenerate with --update-golden "
        f"(oracle engine only)."
    )
    expected = golden.read_text()
    assert actual == expected, (
        f"{engine.name} output for '{case.id}' must equal the oracle golden.\n"
        f"--- expected (golden) ---\n{expected}\n--- actual ({engine.name}) ---\n{actual}"
    )


# Pairwise agreement: for each case, assert every two AVAILABLE engines agree.
_PAIRWISE_CASES = list(_CASES)


@pytest.mark.parametrize("case", _PAIRWISE_CASES, ids=[c.id for c in _PAIRWISE_CASES])
def test_engines_agree_pairwise(case: Case, request) -> None:
    """B. Pairwise agreement: any two available engines produce identical canonical."""
    handled = [e for e in _ENGINES if e.handles(case)]
    available = [e for e in handled if e.availability(case) is None]
    unavailable = {
        e.name: e.availability(case)
        for e in handled
        if e.availability(case) is not None
    }
    if len(available) < 2:
        pytest.skip(
            f"<2 engines available for '{case.id}' (cannot check pairwise); "
            f"skipped engines: {unavailable}"
        )
    # Surface any engine that could NOT participate via the test report's
    # user_properties so a silently-missing engine is detectable even when this
    # test runs in isolation (the golden-conformance test additionally emits one
    # explicit skip per such engine, per acceptance Section 5.E skip-visibility).
    if unavailable:
        request.node.user_properties.append(("pairwise_unavailable", unavailable))

    outputs = {e.name: e.run(case) for e in available}
    names = sorted(outputs)
    reference = names[0]
    for other in names[1:]:
        assert outputs[reference] == outputs[other], (
            f"pairwise divergence for '{case.id}' between {reference} and {other}.\n"
            f"--- {reference} ---\n{outputs[reference]}\n--- {other} ---\n{outputs[other]}"
        )
