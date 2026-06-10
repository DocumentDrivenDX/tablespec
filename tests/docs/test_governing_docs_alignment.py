"""Regression coverage for governing-doc alignment with shipped behavior."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_helix_marker_parses_and_roots_exist() -> None:
    marker = yaml.safe_load((ROOT / ".helix.yml").read_text(encoding="utf-8"))

    assert marker["version"] == 1
    assert marker["defaults"]["flow"] == "helix"

    flows = marker["flows"]
    assert flows == [{"id": "helix", "root": "docs/helix/"}]
    for flow in flows:
        assert (ROOT / flow["root"]).is_dir(), flow


def test_shipped_feature_specs_are_marked_implemented() -> None:
    for relative_path in [
        "docs/helix/01-frame/features/FEAT-024-native-spark-profiler.md",
        "docs/helix/01-frame/features/FEAT-026-compile-orchestrator-bootstrap.md",
        "docs/helix/01-frame/features/FEAT-028-ldp-sibling-emitter.md",
    ]:
        text = _read(relative_path)
        assert "**Status**: Implemented" in text, relative_path
        stale_status = "**Status**: " + "Specified"
        assert stale_status not in text, relative_path


def test_adr_011_describes_unsupported_native_expectations_as_fail_closed() -> None:
    text = _read(
        "docs/helix/02-design/adr/ADR-011-connect-safe-gx-native-executor-routing.md"
    )

    stale_phrases = [
        "passing " + "stub",
        "passes " + "silently",
        "unsupported-" + "passing " + "stub",
        "surfaced as a " + "passing result",
    ]
    for phrase in stale_phrases:
        assert phrase not in text

    assert "success=False" in text
    assert "fails closed" in text


def test_us_025_no_longer_claims_dbt_runner_or_cli_unshipped() -> None:
    text = _read("docs/helix/01-frame/user-stories/US-025-emit-dbt-project-from-umf.md")

    stale_unshipped = "not yet " + "shipped"
    assert stale_unshipped not in text
    assert "DbtRunner" in text
    assert "emit --backend dbt [--run]" in text


def test_implementation_plan_v2_does_not_snapshot_closed_beads() -> None:
    text = _read("docs/helix/04-build/implementation-plan-v2.md")

    for closed_bead_id in [
        "hx-" + "2c3c331f",
        "tablespec-" + "62dbc8c6",
        "tablespec-" + "340da854",
    ]:
        assert closed_bead_id not in text

    assert "does not snapshot active beads" in text
    assert "ddx bead ready --json" in text
    assert "ddx bead status --json" in text
