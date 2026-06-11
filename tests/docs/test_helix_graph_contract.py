from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "workflows" / "graph.yml"


def _load_graph() -> dict:
    return yaml.safe_load(GRAPH_PATH.read_text(encoding="utf-8"))


def test_helix_marker_has_project_local_graph() -> None:
    marker = yaml.safe_load((ROOT / ".helix.yml").read_text(encoding="utf-8"))
    graph = _load_graph()

    assert GRAPH_PATH.is_file()
    assert marker["flows"] == [{"id": "helix", "root": "docs/helix/"}]
    assert graph["version"] == 1
    assert graph["methodology"]["id"] == "helix"
    assert graph["methodology"]["root"] == "docs/helix/"


def test_helix_graph_node_and_edge_contract() -> None:
    graph = _load_graph()
    activity_ids = {activity["id"] for activity in graph["activities"]}
    node_ids = [node["id"] for node in graph["nodes"]]
    node_id_set = set(node_ids)

    assert len(node_ids) == len(node_id_set)
    assert activity_ids == {
        "00-discover",
        "01-frame",
        "02-design",
        "03-test",
        "04-build",
        "05-deploy",
        "06-iterate",
    }

    for activity_id in activity_ids:
        assert (ROOT / "docs" / "helix" / activity_id).is_dir(), activity_id

    for node in graph["nodes"]:
        assert set(node) == {"id", "type", "activity", "cardinality"}
        assert node["activity"] in activity_ids
        assert node["cardinality"] in {"one", "many"}
        assert node["type"].startswith(("library:", "local:"))

    for edge in graph["edges"]:
        assert set(edge) == {"from", "to", "kind", "required"}
        assert edge["from"] in node_id_set
        assert edge["to"] in node_id_set
        assert edge["kind"] in {"informs", "decomposes", "validates", "supersedes"}
        assert isinstance(edge["required"], bool)


def test_helix_graph_contains_tablespec_authoring_surface() -> None:
    graph = _load_graph()
    node_ids = {node["id"] for node in graph["nodes"]}

    assert {
        "product-vision",
        "prd",
        "principles",
        "concerns",
        "feature-registry",
        "feature-specification",
        "user-stories",
        "adr",
        "architecture",
        "solution-design",
        "data-quality-expectations",
        "test-plan",
        "implementation-plan",
        "deployment-checklist",
        "release-notes",
    } <= node_ids

    required_edges = {
        ("product-vision", "prd"),
        ("prd", "feature-specification"),
        ("feature-specification", "user-stories"),
        ("feature-specification", "adr"),
        ("test-plan", "implementation-plan"),
    }
    graph_edges = {(edge["from"], edge["to"]) for edge in graph["edges"]}
    assert required_edges <= graph_edges
