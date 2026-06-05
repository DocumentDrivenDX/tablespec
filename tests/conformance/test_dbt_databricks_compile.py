"""The DATABRICKS (prod) target proven well-formed OFFLINE -- the parse tier.

dbt-databricks is COMPILE-ONLY in this environment (no cluster). IMPORTANT nuance,
verified in this env: ``dbt compile`` for the databricks adapter is NOT offline --
it opens a SQL-warehouse connection to populate the relation cache and retries
~30x with backoff against an unreachable host (it hangs, it does not "compile
without a cluster"). The genuinely offline, no-cluster validation is ``dbt parse``:
it builds the full manifest and registers the databricks adapter WITHOUT
connecting. That proves the project is well-formed for Databricks.

This is the Phase 4 ``DbtDatabricksCompileEngine`` (``tier="compile"``) wired into
the SAME engine module as the row-parity matrix. Because the prod target cannot
execute rows here -- and ``dbt parse`` does NOT render ``{{ source/ref/config }}``
to physical SQL (that needs the hanging ``dbt compile``) -- it is judged against a
committed PARSE golden: the PARSED MODEL BODY (``raw_code``) + the resolved config
the databricks adapter registered. That body still carries the literal Databricks
cast SQL a cluster would run (the ``{{ }}`` Jinja is intentionally NOT expanded).
Two checks gate the prod target:

  1. ``dbt parse`` succeeds and the manifest is built under the ``databricks``
     adapter (the contract / materialization config survives parsing); and
  2. the parsed model body is byte-stable vs the committed parse golden, and
     carries the Databricks==Spark ``try_to_timestamp`` cast a cluster would run.

Regenerate the parse goldens with ``UPDATE_DATABRICKS_GOLDEN=1``.

Run under::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv uv run pytest \
      tests/conformance/test_dbt_databricks_compile.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tests.conformance.corpus.registry import Case, ingest_cases
from tests.conformance.engines import (
    DbtDatabricksCompileEngine,
    _databricks_compile_availability,
)

# dbt's file-backed logger and the databricks adapter close their handles lazily
# during GC; the resulting ResourceWarning would be escalated by the suite-wide
# ``filterwarnings = error`` into a spurious failure. That handle lifecycle is
# dbt's, not the behaviour under test (the parsed-body correctness is asserted
# explicitly), so it is ignored here.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
    # dbt-databricks imports trigger a Pydantic V1-config DeprecationWarning that the
    # suite-wide filterwarnings=error would escalate; it is third-party, not the
    # behaviour under test.
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]

# NOTE: NO module-level ``importorskip`` here. dbt-databricks is expected installed
# in this env (Setup added it), so the dedicated guard below ASSERTS it is available
# (and FAILS if absent) -- a module-skip would let an under-installed CI report this
# tier green-on-nothing. The parametrized parse cases skip INDIVIDUALLY only if the
# adapter is genuinely missing, with a visible reason.
GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "databricks_compile"

# Databricks SQL == Spark SQL for our casts: the databricks dialect must emit the
# identical Java-token try_to_timestamp a Databricks cluster would execute. The
# events fixture has a date/timestamp column whose cast we assert is present.
_CAST_FIXTURE = "events_incremental_nopk"
_EXPECTED_CAST = "try_to_timestamp(occurred_at, 'yyyy-MM-dd HH:mm:ss')"

# A representative subset of the ingest corpus exercised through the prod target:
# a keyless-incremental table (events), a snapshot+pk table (members), and an
# incremental+pk table (claims). Each materialization shape must parse correctly
# under the databricks adapter.
_COMPILE_CASE_IDS = (
    "events_incremental_nopk",
    "members_snapshot_pk",
    "claims_incremental_pk",
)
_COMPILE_CASES = [c for c in ingest_cases() if c.id in _COMPILE_CASE_IDS]

# Fail loudly if a corpus rename / typo silently shrinks the Databricks parse
# matrix (an absent ID would just drop a case otherwise).
_FOUND_IDS = {c.id for c in _COMPILE_CASES}
assert _FOUND_IDS == set(_COMPILE_CASE_IDS), (
    "the Databricks parse matrix lost expected case(s): "
    f"missing {set(_COMPILE_CASE_IDS) - _FOUND_IDS}"
)


def _golden_path(case: Case) -> Path:
    return GOLDEN_DIR / f"{case.id}.databricks.parsed.sql"


def test_databricks_parse_tier_is_available_here() -> None:
    """Guard: the parse tier MUST execute here (dbt-databricks is installed).

    There is intentionally NO module-level ``importorskip``, so this guard runs even
    when the adapter is absent and FAILS (rather than the whole module silently
    skipping). Setup installed dbt-databricks in this env, so the tier must NOT be
    all-skipped: a green parse tier that ran zero cases (an under-installed CI) would
    be green-on-nothing.
    """
    sample = _COMPILE_CASES[0]
    reason = _databricks_compile_availability()
    assert reason is None, (
        "dbt-databricks is expected available in this env, but the parse tier is "
        f"unavailable ({reason}) -- the parse golden tier would be all-skipped."
    )
    # The golden for the first case exists (committed), so the tier is genuinely wired.
    assert _golden_path(sample).exists(), (
        f"parse golden missing for '{sample.id}' -- the parse tier is not wired"
    )


@pytest.mark.parametrize("case", _COMPILE_CASES, ids=[c.id for c in _COMPILE_CASES])
def test_databricks_parse_golden(case: Case) -> None:
    """The prod (Databricks) target parses to a byte-stable model body, offline.

    The artifact is the PARSED model body (``raw_code`` + resolved config) the
    databricks adapter registered -- NOT warehouse-compiled SQL (that needs the
    hanging ``dbt compile``). The ``{{ source/config }}`` Jinja is intentionally not
    expanded; the cast SQL a cluster would run IS present and asserted separately.
    """
    engine = DbtDatabricksCompileEngine()
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)

    parsed = engine.run(case)  # dbt parse under the databricks adapter (offline)
    golden = _golden_path(case)

    if os.environ.get("UPDATE_DATABRICKS_GOLDEN"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(parsed)

    assert golden.exists(), (
        f"databricks parse golden missing for '{case.id}': {golden}. "
        f"Regenerate with UPDATE_DATABRICKS_GOLDEN=1."
    )
    expected = golden.read_text()
    assert parsed == expected, (
        f"databricks parsed model body for '{case.id}' drifted from the parse golden "
        f"(regenerate with UPDATE_DATABRICKS_GOLDEN=1 if intended).\n"
        f"--- golden ---\n{expected}\n--- parsed ---\n{parsed}"
    )
    # The parsed body is annotated as produced under the databricks adapter.
    assert parsed.startswith("-- adapter: databricks\n"), (
        "parsed artifact was not produced under the databricks adapter"
    )
    assert "parsed_model_body" in parsed, (
        "the artifact must be honestly labeled the parsed model body (not compiled)"
    )


def test_databricks_parsed_body_carries_spark_cast() -> None:
    """The databricks-parsed model carries the try_to_timestamp cast a cluster runs."""
    engine = DbtDatabricksCompileEngine()
    case = next(c for c in ingest_cases() if c.id == _CAST_FIXTURE)
    reason = engine.availability(case)
    if reason is not None:
        pytest.skip(reason)
    parsed = engine.run(case)
    assert _EXPECTED_CAST in parsed, (
        "the databricks-parsed model node does not carry the try_to_timestamp cast "
        "a Databricks cluster would execute"
    )
    # The materialization config survived parsing under the databricks adapter.
    umf = yaml.safe_load(case.umf.read_text())  # type: ignore[arg-type]
    assert umf["table_name"] == "events"
    assert "-- materialized: incremental\n" in parsed
