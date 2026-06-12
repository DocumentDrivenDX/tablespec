"""Regression coverage for the deployment checklist template."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "docs/helix/05-deploy/deployment-checklist.md"


def test_deployment_checklist_uses_template_sections() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")

    assert "**Status**: Execution-ready template for the next release" in text
    assert "## release_scope" in text
    assert "## rollout_plan" in text
    assert "## rollback_triggers" in text
    assert "## go_or_no_go_decision" in text
    assert "## Release Process" not in text
    assert "## CI Pipelines" not in text


def test_deployment_checklist_records_measurable_release_gates() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")

    expected_fragments = [
        "v*.*.*",
        "uv build",
        "hugo --gc --minify",
        "scripts/build_pages_artifact.py",
        "--include-github-releases",
        "pages/index.html",
        "pages/simple/index.html",
        "pages/simple/tablespec/index.html",
        "Wait 60 seconds for propagation",
        "One retry is allowed after the 60-second propagation wait",
        "pip install --index-url https://documentdrivendx.github.io/tablespec/simple/ tablespec==$VERSION",
        "Delete the GitHub Release and the release tag",
    ]

    for fragment in expected_fragments:
        assert fragment in text, fragment
