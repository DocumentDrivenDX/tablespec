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
    REQUIRED_LOCAL_ROW_ENGINES,
    Engine,
    SQLPlanGeneratorGoldEngine,
    row_engines,
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
# The row-parity matrix is the locally-EXECUTED (tier="row") engines only; the
# compile (databricks) and structure (LDP) tiers are judged against artifact/row
# goldens by their own dedicated tests (test_dbt_databricks_compile.py /
# test_ldp_tiers.py). All tiers are still enumerated by all_engines() so the
# skipped-but-green guard can count what executed here.
_ENGINES = row_engines()


def _param(engine: Engine, case: Case):
    """Build the (engine, case) param, marking KNOWN divergences as STRICT xfail.

    The three known gold divergences (gold_pivot, gold_window_aggregation,
    gold_survivorship_priority) are genuine generator/corpus defects the harness
    surfaced. They are STRICT-xfail (not availability-skips) so that:

      * they are distinguishable from environment-unavailability skips, AND
      * if a generator fix makes one of them suddenly PASS, the strict xfail FAILS
        (xpass) -- flipping the gate and forcing the divergence note + golden to be
        promoted, rather than the fix passing silently.

    A divergence case that still cannot execute raises inside ``engine.run`` and is
    reported as an expected failure (xfail), keeping the gate red-but-known.
    """
    if case.divergence and isinstance(engine, SQLPlanGeneratorGoldEngine):
        return pytest.param(
            engine,
            case,
            marks=pytest.mark.xfail(
                strict=True,
                reason=f"known divergence (strict xfail, flips on a fix): "
                f"{case.divergence}",
            ),
        )
    return pytest.param(engine, case)


# Result-parity matrix pairs: only (engine, case) the engine declares it handles.
_MATRIX = [
    _param(engine, case)
    for case in _CASES
    for engine in _ENGINES
    if engine.handles(case)
]
_MATRIX_IDS = [f"{e.name}-{c.id}" for c in _CASES for e in _ENGINES if e.handles(c)]


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

    # KNOWN DIVERGENCE (strict-xfail via _param). The divergence is the precise
    # signal that the duckdb + spark backends do NOT agree on a correct result:
    # for the current generator one backend either RAISES (duckdb's reserved-word /
    # column-map defects) or silently produces WRONG rows (spark renders the missing
    # survivorship column as all-NULL), so the two never agree. This body therefore
    # runs BOTH backends and asserts byte-identical agreement. Under the current
    # generator that assert (or the duckdb raise) FAILS -> expected xfail. A generator
    # FIX makes both backends execute AND agree -> the body PASSES -> the strict xfail
    # XPASSES -> the gate FLIPS (xpass fails the suite), forcing the divergence note +
    # a promoted golden. (Cross-backend agreement is a stronger 'fixed' signal than a
    # weak non-empty check, which the spark backend could satisfy with wrong NULLs.)
    if case.divergence:
        from tests.conformance.engines import SQLPlanGeneratorGoldEngine as _Gold

        duck = _Gold(backend="duckdb").run(case)  # raises today on the duckdb defect
        spark = _Gold(backend="spark").run(case)
        assert duck == spark, (
            f"divergence case '{case.id}' still diverges across backends "
            f"(duckdb != spark):\n--- duckdb ---\n{duck}\n--- spark ---\n{spark}"
        )
        return

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
    # Known divergences cannot execute to a stable canonical (the generator/corpus
    # defect makes ``run`` raise); they are STRICT-xfail in the golden-conformance
    # matrix. Skip pairwise here with the divergence reason so the failure surfaces
    # only once (as the strict xfail), never as a hard pairwise error.
    if case.divergence:
        pytest.skip(
            f"known divergence (strict xfail in golden tier): {case.divergence}"
        )
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


# ---------------------------------------------------------------------------
# C. Skipped-but-green guard (matrix-review must-fix).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", REQUIRED_LOCAL_ROW_ENGINES)
def test_required_engine_actually_executed(engine_name: str) -> None:
    """A required engine must EXECUTE >=1 case here -- never report green on skips.

    The matrix can look green when a required Spark/dbt engine was SKIPPED for every
    case (environment unavailable) rather than executed. This guard closes that
    'skipped-but-reported-green' lens: for each engine the harness asserts is
    available in THIS environment (Spark JDK present, dbt adapters installed), it
    must find at least one corpus case it can run AND actually run it to a non-empty
    canonical output. If the engine is unexpectedly unavailable (a broken JDK / a
    missing adapter), THIS test FAILS loudly instead of the matrix passing on zero
    executed engine-legs.
    """
    engine = next(e for e in _ENGINES if e.name == engine_name)
    runnable = [
        c
        for c in _CASES
        if engine.handles(c) and engine.availability(c) is None and not c.divergence
    ]
    assert runnable, (
        f"REQUIRED engine {engine_name!r} could run NO corpus case in this "
        f"environment -- it was skipped for every case, so a green matrix would be "
        f"green-on-nothing. Availability reasons: "
        f"{ {c.id: engine.availability(c) for c in _CASES if engine.handles(c)} }"
    )
    # Actually execute one case end-to-end so 'available' is proven by EXECUTION,
    # not merely by the availability gate returning None.
    sample = runnable[0]
    out = engine.run(sample)
    assert out and out.strip(), (
        f"REQUIRED engine {engine_name!r} executed '{sample.id}' but produced empty "
        f"canonical output (it did not really run)."
    )


def test_matrix_has_required_row_engines_registered() -> None:
    """The row-parity matrix must register exactly the REQUIRED local engines.

    A drop of a required engine from ``row_engines()`` would shrink the matrix
    silently (fewer legs, still green). Pin the registered set so a regression that
    removes an executed engine fails here.
    """
    registered = sorted(e.name for e in _ENGINES)
    assert registered == sorted(REQUIRED_LOCAL_ROW_ENGINES), (
        f"row-engine set drifted from the required set.\n"
        f"  registered: {registered}\n  required:   {sorted(REQUIRED_LOCAL_ROW_ENGINES)}"
    )
