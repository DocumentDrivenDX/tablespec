"""Local/CI toolchain parity guards.

The pre-commit CI gate runs ruff-format over (nearly) the whole repo with the
hook version pinned in ``.pre-commit-config.yaml``, while day-to-day local
verification historically ran only ``ruff check`` on a narrower file set — so
unformatted code (or a hook-pin/venv version skew) sailed through a green
local run and then failed CI. These tests make that class of drift fail the
plain test suite itself, which both ``make check`` and the Coverage workflow
always run.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]


def _precommit_config() -> dict:
    return yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())


def test_precommit_ruff_rev_matches_installed_ruff() -> None:
    """The ruff the venv runs is the ruff the pre-commit CI gate runs.

    ``make format``/``make format-check`` use the venv's ruff; CI's pre-commit
    action uses the hook rev. If one is bumped without the other, formatting
    that is clean locally can be rejected in CI (or vice versa).
    """
    hook_revs = {
        repo["repo"]: repo["rev"]
        for repo in _precommit_config()["repos"]
        if "ruff-pre-commit" in repo["repo"]
    }
    assert hook_revs, "ruff-pre-commit hook missing from .pre-commit-config.yaml"
    (rev,) = hook_revs.values()
    installed = version("ruff")
    assert rev.lstrip("v") == installed, (
        f"pre-commit pins ruff {rev} but the venv has ruff {installed} — "
        "bump .pre-commit-config.yaml and the pyproject dev pin together "
        "(then `uv sync`) so local formatting matches the CI gate"
    )


def test_repo_is_ruff_format_clean() -> None:
    """``ruff format --check`` passes repo-wide (the pre-commit CI gate).

    Scope comes from ``[tool.ruff]`` excludes in pyproject.toml, which are
    kept in sync with the pre-commit hook excludes. Failing here means a push
    would fail the pre-commit workflow: run ``make format``.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "unformatted files (would fail the pre-commit CI gate — "
        f"run `make format`):\n{result.stdout}{result.stderr}"
    )
