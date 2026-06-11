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


def test_shipped_feature_specs_are_marked_approved() -> None:
    # Spec docs use the template enum (Approved); delivery stage (Built) is
    # tracked in docs/helix/01-frame/feature-registry.md (decided 2026-06-10).
    for relative_path in [
        "docs/helix/01-frame/features/FEAT-024-native-spark-profiler.md",
        "docs/helix/01-frame/features/FEAT-026-compile-orchestrator-bootstrap.md",
        "docs/helix/01-frame/features/FEAT-028-ldp-sibling-emitter.md",
    ]:
        text = _read(relative_path)
        assert "**Status**: Approved" in text, relative_path
        for stale in ("Specified", "Implemented"):
            stale_status = "**Status**: " + stale
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


def test_source_semantic_bronze_is_governed_without_new_fr_family() -> None:
    principle_text = _read("docs/helix/01-frame/principles.md")
    prd_text = _read("docs/helix/01-frame/prd.md")
    vision_text = _read("docs/helix/00-discover/product-vision.md")

    source_semantic = "source-" + "semantic"
    assert "Preserve source semantics, not source accidents" in principle_text
    assert source_semantic in prd_text
    assert "FR-21" not in prd_text
    assert "raw storage" in vision_text.lower()
    assert "silver" in vision_text


def test_product_microsite_governance_preserves_pages_package_index() -> None:
    feat_text = _read("docs/helix/01-frame/features/FEAT-030-product-microsite.md")
    story_text = _read(
        "docs/helix/01-frame/user-stories/US-038-publish-product-microsite.md"
    )
    adr_text = _read(
        "docs/helix/02-design/adr/ADR-014-product-microsite-pages-architecture.md"
    )
    registry_text = _read("docs/helix/01-frame/feature-registry.md")

    assert "Hugo + Hextra" in feat_text
    assert "FEAT-015 continues to own API reference generation" in adr_text
    assert "/simple/tablespec/" in feat_text
    assert "/simple/tablespec/index.html" in story_text
    assert "FEAT-030" in registry_text
    assert "ADR-014" in registry_text


def test_microsite_concerns_reconcile_browser_testing_scope() -> None:
    concerns_text = _read("docs/helix/01-frame/concerns.md")

    assert "hugo-hextra" in concerns_text
    assert "product-microsite-ia" in concerns_text
    assert "Playwright for microsite" in concerns_text
    assert "conformance harness for library runtime" in concerns_text
