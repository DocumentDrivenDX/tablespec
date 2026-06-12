"""Focused conformance slice for dump-dialect delimited fixtures."""

from __future__ import annotations

import pytest

from tests.conformance.corpus.registry import ingest_cases
from tests.conformance.engines import row_engines

pytestmark = [
    pytest.mark.slow,
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_DUMP_CASES = [case for case in ingest_cases() if case.has_tag("dump")]
_ROW_ENGINES = row_engines()


@pytest.mark.parametrize("case", _DUMP_CASES, ids=[c.id for c in _DUMP_CASES])
def test_dump_cases_match_golden(case):
    assert case.golden is not None
    expected = case.golden.read_text()
    ran = False
    for engine in _ROW_ENGINES:
        if not engine.handles(case):
            continue
        reason = engine.availability(case)
        if reason is not None:
            pytest.skip(f"{engine.name} unavailable for '{case.id}': {reason}")
        actual = engine.run(case)
        assert actual == expected, (
            f"{engine.name} output for '{case.id}' must equal the dump golden.\n"
            f"--- expected ---\n{expected}\n--- actual ---\n{actual}"
        )
        ran = True
    assert ran, f"no row engine executed dump case '{case.id}'"
