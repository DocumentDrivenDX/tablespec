"""API documentation inventory coverage.

@covers US-028-AC1
@covers US-028-AC2
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_api_docs_pages_exist_and_reference_package_modules() -> None:
    repo = Path(__file__).resolve().parents[2]
    expected_pages = {
        "models.md": "tablespec.models",
        "generators.md": "tablespec.schemas.generators",
        "type_mappings.md": "tablespec.type_mappings",
        "gx.md": "tablespec.gx_baseline",
        "cli.md": "tablespec.cli",
    }

    for page, module in expected_pages.items():
        content = (repo / "docs" / "api" / page).read_text()
        assert module in content
