"""API documentation inventory coverage.

@covers US-028-AC1
@covers US-028-AC2
"""

from __future__ import annotations

import re
import tomllib
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


def test_claude_md_matches_package_tree_and_optional_extras() -> None:
    repo = Path(__file__).resolve().parents[2]
    claude = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))

    def section(name: str) -> str:
        pattern = rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)"
        match = re.search(pattern, claude, flags=re.M | re.S)
        assert match is not None, f"missing CLAUDE.md section: {name}"
        return match.group(1)

    structure = section("Project Structure")
    packages = sorted(
        path.name
        for path in (repo / "src" / "tablespec").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )
    for package in packages:
        assert f"`{package}/`" in structure, package

    optional = section("Optional Dependencies")
    extras = sorted(pyproject["project"]["optional-dependencies"].keys())
    for extra in extras:
        assert f"[{extra}]" in optional, extra
