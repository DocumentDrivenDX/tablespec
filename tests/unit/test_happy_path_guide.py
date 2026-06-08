"""Happy-path docs coverage.

@covers tablespec-390cbf1f AC1 AC2 AC3 AC4
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_happy_path_guide_is_ordered_and_indexed() -> None:
    repo = Path(__file__).resolve().parents[2]
    guide = repo / "docs" / "guide" / "happy-path.md"
    assert guide.exists()

    content = guide.read_text()
    ordered_markers = [
        "## 1. Generate UMF from existing Spark or Databricks tables",
        "## 2. Generate sample data from the UMF or spec inputs",
        "## 3. Validate real source data and generated sample data",
        "## 4. Generate table-spec and validation Excel workbooks",
        "## 5. Define a derived table from source UMFs",
        "## 6. Generate Spark, LDP, and dbt pipeline artifacts",
        "## 7. Run the generated pipelines",
    ]

    pos = -1
    for marker in ordered_markers:
        new_pos = content.find(marker)
        assert new_pos != -1, marker
        assert new_pos > pos, marker
        pos = new_pos

    required_strings = [
        "bootstrap_from_tables",
        "umfs_from_tables",
        "umfs_from_specs",
        "SampleDataGenerator",
        "TableValidator",
        "UMFToExcelConverter",
        "ExcelToUMFConverter",
        "UMFColumnDerivation",
        "DerivationCandidate",
        "compile_umfs",
        "generate_sql_plan",
        "generate_dbt_project",
        "generate_dbt_dag_project",
        "generate_ldp_project",
        "run_backbone",
        "tablespec-ed74497c",
        "tablespec-0b146671",
        "tablespec-171e409c",
        "tablespec-0fb0d1c2",
        "pytest.main",
        "uv run pytest",
    ]
    for needle in required_strings:
        assert needle in content, needle

    docs_index = (repo / "docs" / "index.md").read_text()
    assert "guide/happy-path.md" in docs_index

    mkdocs = (repo / "mkdocs.yml").read_text()
    assert "guide/happy-path.md" in mkdocs
