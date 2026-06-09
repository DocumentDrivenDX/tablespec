"""Regression tests for the documented public dialect contract."""

from __future__ import annotations

from pathlib import Path


DOC = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "helix"
    / "03-test"
    / "conformance-acceptance.md"
)


def _conformance_acceptance_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_databricks_opt_in_tier_preserves_public_dialect() -> None:
    text = _conformance_acceptance_text()

    assert (
        "real Databricks workspace execution is available only through this opt-in tier"
        in text
    )
    assert 'public `dialect="databricks"` spelling remains an accepted contract' in text
    assert 'Public Databricks-facing compile UX accepts `dialect="databricks"`' in text


def test_databricks_local_coverage_does_not_demote_dialect() -> None:
    text = _conformance_acceptance_text()

    assert "Local Spark-family parity proves the shared cast semantics" in text
    assert "does not replace or" in text
    assert 'reject public `dialect="databricks"` acceptance' in text
    assert '`dialect="databricks"`' in text
