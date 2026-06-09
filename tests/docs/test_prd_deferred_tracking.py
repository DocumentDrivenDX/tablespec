"""Regression coverage for PRD deferred-work tracking."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRD = ROOT / "docs/helix/01-frame/prd.md"


def test_prd_deferred_items_use_ddx_tracking() -> None:
    text = PRD.read_text()
    removed_path = "docs/helix/" + "parking-" + "lot.md"

    assert removed_path not in text
    assert "Deferred items are tracked in DDx beads." in text
    assert "ddx bead ready --json" in text
    assert "ddx bead status --json" in text
