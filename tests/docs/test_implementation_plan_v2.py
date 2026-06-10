"""Regression coverage for the replaced implementation-plan-v2 artifact."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/helix/04-build/implementation-plan-v2.md"


def test_implementation_plan_v2_is_replacement_note() -> None:
    text = PLAN.read_text()

    assert "**Status**: Replaced by current specs and DDx beads" in text
    assert "## Shipped Evidence" in text
    assert "## Remaining Work" in text
    assert "Status**: Proposed" not in text
    assert "Phase 1a: Unified Expectation Model" not in text
    assert "profiling-to-expectations conversion (the TODO stub" not in text


def test_implementation_plan_v2_links_to_active_tracking() -> None:
    text = PLAN.read_text()

    assert "ddx bead ready --json" in text
    assert "ddx bead status --json" in text
    assert "ddx bead show <id> --json" in text
    assert "snapshot active beads" in text

    for closed_bead_id in [
        "hx-" + "2c3c331f",
        "tablespec-" + "62dbc8c6",
        "tablespec-" + "340da854",
    ]:
        assert closed_bead_id not in text

    for relative_path in [
        "docs/helix/01-frame/prd.md",
        "docs/helix/02-design/architecture.md",
        "docs/helix/03-test/test-plan.md",
        "docs/helix/04-build/implementation-plan.md",
        "docs/helix/01-frame/features/FEAT-016-testing-infrastructure.md",
        "docs/helix/01-frame/features/FEAT-017-validation-pipeline.md",
        "docs/helix/01-frame/features/FEAT-024-native-spark-profiler.md",
        "docs/helix/01-frame/features/FEAT-026-compile-orchestrator-bootstrap.md",
        "docs/helix/02-design/adr/ADR-012-compile-orchestrator-runtime-consumes-committed-artifacts.md",
        "docs/helix/02-design/adr/ADR-013-target-agnostic-core-seam-sibling-emitters.md",
    ]:
        assert (ROOT / relative_path).exists(), relative_path
