"""Regression coverage for governing-doc alignment with shipped behavior."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
FEATURE_DIR = ROOT / "docs/helix/01-frame/features"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _legacy_feature_paths() -> list[Path]:
    return [
        path
        for path in sorted(FEATURE_DIR.glob("FEAT-*.md"))
        if 1 <= int(path.name.removeprefix("FEAT-")[:3]) <= 23
    ]


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


def test_legacy_feature_specs_follow_current_template_sections() -> None:
    required_sections = [
        "Overview",
        "Ideal Future State",
        "Problem Statement",
        "Functional Areas",
        "Requirements",
        "User Stories",
        "Edge Cases and Error Handling",
        "Success Metrics",
        "Constraints and Assumptions",
        "Dependencies",
        "Out of Scope",
        "Review Checklist",
    ]

    for path in _legacy_feature_paths():
        text = path.read_text(encoding="utf-8")
        feature_id = path.name[:8]

        assert text.startswith("---\n"), path
        assert f"# Feature Specification: {feature_id} " in text, path
        assert "### Existing Scope Evidence" in text, path
        assert "source-preserving" in text, path
        for section in required_sections:
            assert f"\n## {section}\n" in text, f"{path}: missing {section}"


def test_legacy_adrs_follow_current_template_sections() -> None:
    required_sections = [
        "Alternatives",
        "Risks",
        "Validation",
        "Supersession",
        "Concern Impact",
        "References",
        "Review Checklist",
    ]

    for relative_path in [
        "docs/helix/02-design/adr/ADR-001-date-as-yyyymmdd-string.md",
        "docs/helix/02-design/adr/ADR-002-gx-16-format-only.md",
        "docs/helix/02-design/adr/ADR-003-optional-pyspark-dependency.md",
        "docs/helix/02-design/adr/ADR-004-datetime-timestamp-unification.md",
        "docs/helix/02-design/adr/ADR-005-unified-expectation-model.md",
        "docs/helix/02-design/adr/ADR-006-gx-duckdb-test-backend.md",
        "docs/helix/02-design/adr/ADR-007-raw-to-ingest-sql-artifact.md",
        "docs/helix/02-design/adr/ADR-008-dbt-adoption-architecture.md",
    ]:
        text = _read(relative_path)

        assert "| Date | Status | Deciders | Related | Confidence |" in text, relative_path
        for section in required_sections:
            assert f"\n## {section}\n" in text, f"{relative_path}: missing {section}"


def test_legacy_feature_registry_rows_reflect_template_backfill() -> None:
    registry = _read("docs/helix/01-frame/feature-registry.md")

    # The registry header's "Last Updated" tracks the newest edit to the file,
    # so it moves whenever any feature is added. Only the backfilled legacy rows
    # carry the 2026-06-11 template-backfill date, and only those are pinned here.
    for path in _legacy_feature_paths():
        feature_id = path.name[:8]
        row = next(
            line
            for line in registry.splitlines()
            if line.startswith(f"| {feature_id} |")
        )
        # The backfill gave every legacy row a Date column; the value moves when
        # a feature is later revised, so assert the shape rather than the date.
        assert re.search(r"\| \d{4}-\d{2}-\d{2} \|$", row), row


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


def test_backfilled_user_stories_follow_the_story_template() -> None:
    required_sections = [
        "Context",
        "Walkthrough",
        "Acceptance Criteria",
        "Edge Cases",
        "Test Scenarios",
        "Dependencies",
        "Out of Scope",
        "Review Checklist",
    ]
    placeholder_scenarios = re.compile(r"\| (Case \d+|Happy path|Edge case) \|")

    for path in sorted((ROOT / "docs/helix/01-frame/user-stories").glob("US-*.md")):
        story_id = int(path.stem.split("-", 2)[1])
        if not (1 <= story_id <= 20 or 27 <= story_id <= 36):
            continue

        text = path.read_text(encoding="utf-8")
        for section in required_sections:
            assert f"\n## {section}\n" in text, f"{path}: missing {section}"

        ac_pattern = re.compile(
            rf"\*\*US-{story_id:03d}-AC\d+\*\* — Given .+ when .+ then .+",
            re.IGNORECASE,
        )
        assert ac_pattern.search(text), f"{path}: missing Given/When/Then AC"
        assert "| Scenario | AC ID | Input / State | Action | Expected Result |" in text, path
        assert not placeholder_scenarios.search(text), (
            f"{path}: scenario table still has placeholder labels"
        )


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
    # The bronze-contract evolution lives inside existing FR families — no
    # dedicated bronze FR family or subsystem. (FR-21 is Source Acquisition,
    # a separate operator-directed family — ADR-015/FEAT-031 — and is
    # intentionally NOT forbidden here.)
    assert "Subsystem: Bronze" not in prd_text
    assert "bronze FR" not in prd_text
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


def test_ldp_sibling_emitter_solution_design_has_required_sections() -> None:
    text = _read("docs/helix/02-design/ldp-sibling-emitter.md")

    assert "# Solution Design" in text
    assert "**Feature**: FEAT-028 - LDP Sibling Emitter" in text
    assert "ADR-013" in text

    for section in [
        "Scope",
        "Requirements Mapping",
        "Solution Approaches",
        "Domain Model",
        "System Decomposition",
        "Technology Rationale",
        "Traceability",
    ]:
        assert f"## {section}" in text, section


def test_microsite_concerns_reconcile_browser_testing_scope() -> None:
    concerns_text = _read("docs/helix/01-frame/concerns.md")

    assert "hugo-hextra" in concerns_text
    assert "product-microsite-ia" in concerns_text
    assert "Playwright for microsite" in concerns_text
    assert "conformance harness for library runtime" in concerns_text
