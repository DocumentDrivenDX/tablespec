"""Regression coverage for the Claude Code / Codex plugin marketplace manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_PLUGIN_MANIFEST = ROOT / ".claude-plugin/plugin.json"
MARKETPLACE_MANIFEST = ROOT / ".claude-plugin/marketplace.json"
CODEX_PLUGIN_MANIFEST = ROOT / ".codex-plugin/plugin.json"
SKILL_MD = ROOT / "skills/tablespec/SKILL.md"
SKILL_OPENAI_YAML = ROOT / "skills/tablespec/agents/openai.yaml"
SKILL_REFERENCES_DIR = ROOT / "skills/tablespec/references"
AGENTS_SKILL_LINK = ROOT / ".agents/skills/tablespec"
CLAUDE_SKILL_LINK = ROOT / ".claude/skills/tablespec"
PUBLISHED_SKILL_DIR = ROOT / "skills/tablespec"

# Matches release.yml's `v*.*.*` trigger, including pre-release tags such as
# v1.2.3-rc1 (the release workflow marks rc/alpha/beta tags as pre-releases).
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def test_skill_is_published_at_plugin_root() -> None:
    assert SKILL_MD.exists()

    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must open with a YAML frontmatter block"
    parts = text.split("---")
    assert len(parts) >= 3, "SKILL.md must have a YAML frontmatter block"
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["name"] == "tablespec"
    description = frontmatter["description"]
    assert isinstance(description, str)
    assert description

    forbidden_fragments = ["tablespec project", "DDx", "ddx"]
    for fragment in forbidden_fragments:
        assert fragment not in description, fragment

    assert not SKILL_REFERENCES_DIR.exists()


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


def test_install_targets_are_symlinks_to_published_skill() -> None:
    published_skill = PUBLISHED_SKILL_DIR.resolve()

    for link in (AGENTS_SKILL_LINK, CLAUDE_SKILL_LINK):
        assert link.is_symlink()
        assert link.resolve() == published_skill
