"""Regression tests for the documented public dialect contract."""

from __future__ import annotations

from pathlib import Path

from tablespec.dialects import CAST_DIALECTS, normalize_cast_dialect

DOC = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "helix"
    / "03-test"
    / "conformance-acceptance.md"
)

COMPILE_MODULE = (
    Path(__file__).resolve().parents[2] / "src" / "tablespec" / "e2e" / "compile.py"
)


def _conformance_acceptance_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_conformance_accepted_dialect_list_includes_databricks() -> None:
    """Accepted public dialects must name spark, duckdb, and databricks."""
    text = _conformance_acceptance_text()

    assert "Accepted public cast dialects" in text
    assert "`spark`" in text and "`duckdb`" in text and "`databricks`" in text
    assert 'dialect="databricks"' in text or '`dialect="databricks"`' in text
    # Module-level contract matches the docs.
    assert set(CAST_DIALECTS) == {"spark", "databricks", "duckdb"}


def test_conformance_accepted_dialect_list_rejects_spark_duckdb_only() -> None:
    """Docs must not regress to spark/duckdb-only accepted dialect language."""
    text = _conformance_acceptance_text()

    assert "not spark/duckdb-only" in text
    assert "spark/duckdb-only" in text  # explicit rejection of the old wording
    # Normalization decision remains explicit.
    assert "normalize" in text.lower()
    assert "byte-identical" in text or "identical" in text


def test_databricks_opt_in_tier_preserves_public_dialect() -> None:
    text = _conformance_acceptance_text()

    assert (
        "real Databricks workspace execution is available only through this opt-in tier"
        in text
    )
    assert 'public `dialect="databricks"` spelling remains an accepted contract' in text
    assert (
        'compile UX accepts\n`dialect="databricks"`' in text
        or 'accepts `dialect="databricks"`' in text
        or "Public Databricks-facing compile UX accepts" in text
    )


def test_databricks_local_coverage_does_not_demote_dialect() -> None:
    text = _conformance_acceptance_text()

    assert "Local Spark-family parity proves the shared cast semantics" in text
    assert "does not replace or" in text
    assert 'reject public `dialect="databricks"` acceptance' in text
    assert '`dialect="databricks"`' in text


def test_databricks_compile_artifacts_state_normalization_decision() -> None:
    """Compile orchestrator documents Spark-family normalization of databricks."""
    text = COMPILE_MODULE.read_text(encoding="utf-8")

    assert "databricks" in text
    assert "normalize" in text
    assert "identical" in text
    # Runtime behavior: public spelling accepted; render path is spark.
    assert normalize_cast_dialect("databricks") == "spark"
    assert normalize_cast_dialect("spark") == "spark"
    assert normalize_cast_dialect("duckdb") == "duckdb"
