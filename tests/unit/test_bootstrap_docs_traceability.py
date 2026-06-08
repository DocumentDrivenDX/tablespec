"""Trace the public Databricks docs for the alias contract.

@covers tablespec-5e81f5e0 AC1 AC2
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

PUBLIC_DATABRICKS_DOCS = (
    "docs/helix/03-test/conformance-acceptance.md",
    "docs/guide/bootstrap.md",
    "docs/guide/happy-path.md",
    "README.md",
    "scripts/run_integration_tests_databricks.ipynb",
)


def _doc_text(path: Path) -> str:
    if path.suffix != ".ipynb":
        return path.read_text()

    notebook = json.loads(path.read_text())
    return "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def test_helix_docs_use_canonical_databricks_dialect_guidance() -> None:
    repo = Path(__file__).resolve().parents[2]

    for rel in PUBLIC_DATABRICKS_DOCS:
        text = _collapsed(_doc_text(repo / rel))
        assert 'dialect="databricks"' in text, rel
        assert "Databricks-facing compile UX" in text, rel
        assert "Spark-family" in text, rel
        assert (
            "normalize to `spark`" in text
            or "normalize the spelling back to `spark`" in text
        ), rel


def test_helix_docs_do_not_teach_spark_only_for_databricks() -> None:
    repo = Path(__file__).resolve().parents[2]

    for rel in PUBLIC_DATABRICKS_DOCS:
        text = _collapsed(_doc_text(repo / rel))
        assert 'dialect="spark"' not in text, rel
