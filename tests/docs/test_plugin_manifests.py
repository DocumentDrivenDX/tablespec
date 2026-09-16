"""Regression coverage for the Claude Code / Codex plugin marketplace manifests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_PLUGIN_MANIFEST = ROOT / ".claude-plugin/plugin.json"
MARKETPLACE_MANIFEST = ROOT / ".claude-plugin/marketplace.json"
CODEX_PLUGIN_MANIFEST = ROOT / ".codex-plugin/plugin.json"
SKILLS_DIR = ROOT / "skills"
SKILL_OPENAI_YAML = ROOT / "skills/tablespec/agents/openai.yaml"

# Every published skill must also be symlinked into the install targets
# (.agents/skills/<name>, .claude/skills/<name>) and negated in .gitignore.
EXPECTED_SKILLS = {
    "tablespec",
    "tablespec-umf-authoring",
    "tablespec-pipeline",
    "tablespec-validation",
    "tablespec-sql-plans",
    "tablespec-profiling-app",
}

# Matches release.yml's `v*.*.*` trigger, including pre-release tags such as
# v1.2.3-rc1 (the release workflow marks rc/alpha/beta tags as pre-releases).
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _skill_dirs() -> list[Path]:
    return sorted(path.parent for path in SKILLS_DIR.glob("*/SKILL.md"))


def _frontmatter(skill_dir: Path) -> dict:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must open with a YAML frontmatter block"
    parts = text.split("---")
    assert len(parts) >= 3, "SKILL.md must have a YAML frontmatter block"
    return yaml.safe_load(parts[1])


def test_manifests_parse_and_have_required_fields() -> None:
    claude_manifest = _load_json(CLAUDE_PLUGIN_MANIFEST)
    codex_manifest = _load_json(CODEX_PLUGIN_MANIFEST)
    marketplace_manifest = _load_json(MARKETPLACE_MANIFEST)

    for manifest in (claude_manifest, codex_manifest):
        assert manifest["name"] == "tablespec"
        assert manifest["version"]
        assert manifest["description"]
        assert manifest["skills"] == "./skills/"
        assert manifest["license"] == "Apache-2.0"
        assert "hooks" not in manifest

    assert codex_manifest["description"] == claude_manifest["description"]
    assert marketplace_manifest["name"] == "tablespec"


def test_manifest_versions_agree() -> None:
    claude_manifest = _load_json(CLAUDE_PLUGIN_MANIFEST)
    codex_manifest = _load_json(CODEX_PLUGIN_MANIFEST)
    marketplace_manifest = _load_json(MARKETPLACE_MANIFEST)

    marketplace_entry = next(
        plugin
        for plugin in marketplace_manifest["plugins"]
        if plugin["name"] == "tablespec"
    )

    versions = {
        claude_manifest["version"],
        codex_manifest["version"],
        marketplace_entry["version"],
    }

    assert len(versions) == 1
    (version,) = versions
    assert VERSION_PATTERN.match(version)


def test_marketplace_catalog_points_at_this_repo() -> None:
    claude_manifest = _load_json(CLAUDE_PLUGIN_MANIFEST)
    marketplace_manifest = _load_json(MARKETPLACE_MANIFEST)

    assert marketplace_manifest["name"] == "tablespec"
    assert marketplace_manifest["owner"]["name"] == "DocumentDrivenDX"
    assert len(marketplace_manifest["plugins"]) == 1

    (plugin_entry,) = marketplace_manifest["plugins"]
    assert plugin_entry["name"] == "tablespec"
    assert plugin_entry["source"] == "./"
    assert plugin_entry["description"] == claude_manifest["description"]


def test_expected_skill_set() -> None:
    assert {path.name for path in _skill_dirs()} == EXPECTED_SKILLS


@pytest.mark.parametrize("skill_dir", _skill_dirs(), ids=lambda p: p.name)
def test_skill_frontmatter(skill_dir: Path) -> None:
    frontmatter = _frontmatter(skill_dir)

    assert frontmatter["name"] == skill_dir.name
    description = frontmatter["description"]
    assert isinstance(description, str)
    assert description

    forbidden_fragments = ["tablespec project", "DDx", "ddx"]
    for fragment in forbidden_fragments:
        assert fragment not in description, fragment

    # The Codex interface block is singular and repo-wide; only the router
    # skill carries Codex interface metadata.
    if skill_dir.name != "tablespec":
        assert not (skill_dir / "agents" / "openai.yaml").exists()


@pytest.mark.parametrize("skill_dir", _skill_dirs(), ids=lambda p: p.name)
def test_skill_has_no_references_dir(skill_dir: Path) -> None:
    assert not (skill_dir / "references").exists()


@pytest.mark.parametrize("skill_dir", _skill_dirs(), ids=lambda p: p.name)
def test_install_targets_are_symlinks_to_published_skill(skill_dir: Path) -> None:
    published_skill = skill_dir.resolve()

    for link in (
        ROOT / ".agents/skills" / skill_dir.name,
        ROOT / ".claude/skills" / skill_dir.name,
    ):
        assert link.is_symlink()
        assert link.resolve() == published_skill
        # Relative link text keeps the plugin relocatable across clones.
        assert os.readlink(link) == f"../../skills/{skill_dir.name}"


def test_codex_skill_metadata_matches_codex_manifest() -> None:
    codex_manifest = _load_json(CODEX_PLUGIN_MANIFEST)
    interface = yaml.safe_load(SKILL_OPENAI_YAML.read_text(encoding="utf-8"))[
        "interface"
    ]

    assert interface["display_name"] == codex_manifest["interface"]["displayName"]
    assert (
        interface["short_description"]
        == codex_manifest["interface"]["shortDescription"]
    )
    assert interface["default_prompt"]
    assert "ddx" not in interface["default_prompt"].lower()
