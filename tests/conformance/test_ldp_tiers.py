"""LDP (Lakeflow Declarative Pipelines) conformance tiers (Phase 4).

LDP runs ONLY on Databricks; there is no LDP runtime in this environment, so the
generated pipeline is NOT executed end-to-end here. This module wires the LDP
emitter into the SAME conformance corpus as the row-parity matrix as a first-class,
honestly-gated engine across three tiers:

  A. CAST PARITY (executed, local) -- the ``LdpStructureEngine`` (``tier="structure"``)
     extracts the LDP ``ingested_<t>`` cast SELECT and runs it on duckdb over the
     case's REAL raw batches. Because that cast body is the SHARED cast layer
     (``build_ingest_select``), its canonical output must equal the SAME corpus ROW
     golden the Spark oracle produced -- proving the LDP cast layer is not a fork.

  B. STRUCTURE GOLDEN (compiled, local) -- the emitted LDP ingested-dataset SQL for
     each corpus case is byte-stable against a committed structure golden, and the
     extracted cast lines are character-identical to the shared select_block.
     Regenerate with ``UPDATE_LDP_STRUCTURE_GOLDEN=1``.

  C. DATABRICKS E2E (opt-in, REMOTE) -- the ``LdpDatabricksE2EEngine`` (``tier="e2e"``)
     would deploy the LDP pipeline to a real workspace and canonicalize the ingested
     table vs the SAME corpus row golden. It is skipped unless ``DATABRICKS_HOST`` is
     set (the ``databricks_e2e`` marker); there is no cluster here, so it skips with
     an explicit reason -- never silently passed.

Run::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv uv run pytest tests/conformance/test_ldp_tiers.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conformance.corpus.registry import Case, ingest_cases
from tests.conformance.engines import (
    LdpDatabricksE2EEngine,
    LdpStructureEngine,
)

pytestmark = [pytest.mark.no_spark]

# NO module-level duckdb importorskip: the STRUCTURE golden tier is pure text
# generation and must NOT depend on duckdb. The EXECUTED cast-body tier alone needs
# duckdb -- it skips per-test via ``LdpStructureEngine.availability`` (which gates on
# duckdb) so a missing duckdb cannot silently skip the structure golden too.

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "ldp_conformance"

_INGEST_CASES = list(ingest_cases())


def _structure_golden(case: Case) -> Path:
    return GOLDEN_DIR / f"{case.id}.ingested.sql"


# ---------------------------------------------------------------------------
# A. cast parity vs the SAME corpus row golden
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_ldp_cast_body_matches_row_golden(case: Case) -> None:
    """The LDP cast body, run on duckdb, reproduces the corpus row golden."""
    engine = LdpStructureEngine()
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)

    actual = engine.run(case)
    assert case.golden is not None and case.golden.exists(), (
        f"row golden missing for '{case.id}': {case.golden}"
    )
    expected = case.golden.read_text()
    assert actual == expected, (
        f"LDP cast-body output for '{case.id}' must equal the corpus row golden "
        f"(the LDP cast layer must not fork from the shared cast).\n"
        f"--- golden ---\n{expected}\n--- LDP ---\n{actual}"
    )


@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_ldp_cast_lines_are_shared_select_block(case: Case) -> None:
    """The LDP ingested cast lines contain the shared IngestSelect.select_block."""
    engine = LdpStructureEngine()
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)
    assert engine.select_block_is_shared(case), (
        f"LDP cast body for '{case.id}' is not the shared cast layer "
        f"(build_ingest_select.select_block not found verbatim)"
    )


def test_ldp_cast_body_tier_executed_some_case() -> None:
    """Guard: the EXECUTED cast-body tier must run >=1 case here (never all-skipped).

    The LDP cast layer must be PROVEN by execution on at least one single-batch,
    UMF-modelable corpus case. If duckdb were missing or the emitter regressed so no
    case is runnable, this fails loudly rather than the cast-parity tier passing on
    zero executed legs.
    """
    engine = LdpStructureEngine()
    runnable = [c for c in _INGEST_CASES if engine.availability(c) is None]
    assert runnable, (
        "the LDP cast-body tier could execute NO corpus case here -- a green tier "
        "would be green-on-nothing. Skip reasons: "
        f"{ {c.id: engine.availability(c) for c in _INGEST_CASES} }"
    )
    # Prove it by EXECUTION (not just the gate): run one case end-to-end.
    out = engine.run(runnable[0])
    assert out and out.strip()


# ---------------------------------------------------------------------------
# B. structure golden of the emitted LDP ingested-dataset SQL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_ldp_structure_golden(case: Case) -> None:
    """The emitted LDP ingested-dataset SQL is byte-stable vs a structure golden.

    Uses the PROD (spark/databricks) dialect so the pinned artifact is the real
    Spark/Databricks-flavored LDP SQL a workspace would deploy, and covers EVERY
    UMF-modelable case (INCLUDING multi-batch incremental cases -- their APPLY
    CHANGES structure must not drift).
    """
    import yaml

    engine = LdpStructureEngine()
    reason = engine.structure_availability(case)
    if reason is not None:
        pytest.skip(reason)

    assert case.umf is not None
    umf = yaml.safe_load(case.umf.read_text())
    table = umf["table_name"]
    files = engine.structure_files(case)  # prod (spark) dialect
    rel = f"ingested/ingested_{table}.sql"
    assert rel in files, f"LDP emitter produced no {rel} for '{case.id}'"
    emitted = files[rel]

    golden = _structure_golden(case)
    if os.environ.get("UPDATE_LDP_STRUCTURE_GOLDEN"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(emitted)

    assert golden.exists(), (
        f"LDP structure golden missing for '{case.id}': {golden}. "
        f"Regenerate with UPDATE_LDP_STRUCTURE_GOLDEN=1."
    )
    assert emitted == golden.read_text(), (
        f"LDP ingested-dataset SQL for '{case.id}' drifted from its structure golden "
        f"(regenerate with UPDATE_LDP_STRUCTURE_GOLDEN=1 if intended)."
    )


def test_ldp_structure_tier_executed_some_case() -> None:
    """Guard: the LDP structure tier must pin >=1 case here (never all-skipped green).

    The structure golden is pure text generation -- it must run for the bulk of the
    corpus in this env. If it produced only skips (e.g. the emitter regressed so no
    case is UMF-modelable), this fails loudly instead of the tier passing on nothing.
    """
    engine = LdpStructureEngine()
    runnable = [c for c in _INGEST_CASES if engine.structure_availability(c) is None]
    # Only the known DOUBLE-typed fixtures may skip; the majority of the corpus must
    # be modelable (a regression that broke modeling would drop this below half).
    assert len(runnable) >= (len(_INGEST_CASES) + 1) // 2, (
        "the LDP structure tier could model too few corpus cases "
        f"({len(runnable)}/{len(_INGEST_CASES)}); only the known DOUBLE fixtures may "
        "skip. Skip reasons: "
        f"{ {c.id: engine.structure_availability(c) for c in _INGEST_CASES} }"
    )
    # The structure golden MUST cover at least one MULTI-BATCH incremental case so the
    # APPLY CHANGES / incremental LDP structure is pinned (it would otherwise be able
    # to drift while only single-batch cases are golden). Prove a multi-batch case is
    # both present in the corpus AND structurally modelable here.
    multibatch = [c for c in runnable if c.is_multibatch]
    assert multibatch, (
        "the LDP structure tier pins no multi-batch case -- the incremental/APPLY "
        "CHANGES structure could drift undetected. Multi-batch corpus cases: "
        f"{[c.id for c in _INGEST_CASES if c.is_multibatch]}"
    )


# ---------------------------------------------------------------------------
# C. opt-in real-Databricks e2e tier (skipped here, not silently passed)
# ---------------------------------------------------------------------------


@pytest.mark.databricks_e2e
@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_ldp_databricks_e2e(case: Case) -> None:
    """Deploy + execute the LDP pipeline on a REAL workspace; match the row golden.

    Opt-in: skipped unless ``DATABRICKS_HOST`` is set. There is no cluster in this
    harness, so this is expected to SKIP here (with an explicit reason), and to run
    as a first-class row engine when a workspace is configured.
    """
    engine = LdpDatabricksE2EEngine()
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)
    # pragma: no cover - only reachable with a configured workspace.
    actual = engine.run(case)
    assert case.golden is not None
    assert actual == case.golden.read_text()


def test_ldp_e2e_engine_is_gated_off_here() -> None:
    """The e2e tier MUST be gated off in this cluster-less env (honest skip).

    A regression that made the e2e tier 'available' without a workspace would let
    it masquerade as executed. Assert it reports unavailable here with the
    DATABRICKS_HOST reason -- proving the opt-in gate is real, not a silent pass.
    """
    engine = LdpDatabricksE2EEngine()
    case = _INGEST_CASES[0]
    if os.environ.get("DATABRICKS_HOST"):
        pytest.skip("DATABRICKS_HOST is set -- the e2e tier is live, not gated off")
    reason = engine.availability(case)
    assert reason is not None and "DATABRICKS_HOST" in reason, (
        f"LDP e2e tier must be gated off without DATABRICKS_HOST; got reason={reason!r}"
    )
