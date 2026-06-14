"""Tests for flat UMF discovery used by the guidebook generator."""

from __future__ import annotations

from pathlib import Path

from tablespec.guidebook.discovery import discover_umfs
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder


def _save_split(tmp_path: Path, rel_dir: str, table_name: str) -> Path:
    """Save a minimal valid UMF in split format under ``tmp_path/rel_dir``."""
    umf = (
        UMFBuilder(table_name)
        .column("id", "INTEGER", key_type="primary")
        .column("name", "VARCHAR", length=50)
        .primary_key("id")
        .build()
    )
    dest = tmp_path / rel_dir
    UMFLoader().save(umf, dest)
    return dest


def test_flat_discovery_no_groups(tmp_path: Path) -> None:
    _save_split(tmp_path, "orders", "orders")
    _save_split(tmp_path, "customers", "customers")

    found = discover_umfs(tmp_path)

    assert {d.table for d in found} == {"orders", "customers"}
    assert all(d.group == "" for d in found)
    # Sorted by (group, table).
    assert [d.table for d in found] == ["customers", "orders"]


def test_nested_discovery_assigns_group_from_subfolder(tmp_path: Path) -> None:
    _save_split(tmp_path, "sales/orders", "orders")
    _save_split(tmp_path, "crm/customers", "customers")

    found = discover_umfs(tmp_path)

    by_table = {d.table: d for d in found}
    assert by_table["orders"].group == "sales"
    assert by_table["customers"].group == "crm"


def test_json_artifact_is_discovered(tmp_path: Path) -> None:
    umf = UMFBuilder("widgets").column("id", "INTEGER").build()
    UMFLoader().save_json(umf, tmp_path / "widgets.umf.json")

    found = discover_umfs(tmp_path)

    assert len(found) == 1
    assert found[0].table == "widgets"
    assert found[0].group == ""


def test_duplicate_group_table_keeps_first(tmp_path: Path, caplog) -> None:
    # Two UMFs at the root that both declare table_name "orders".
    _save_split(tmp_path, "orders", "orders")
    # A JSON artifact at root with the same table name -> collides on (group="", table="orders").
    umf = UMFBuilder("orders").column("id", "INTEGER").build()
    UMFLoader().save_json(umf, tmp_path / "orders.umf.json")

    found = discover_umfs(tmp_path)

    assert sum(d.table == "orders" and d.group == "" for d in found) == 1


def test_malformed_umf_is_skipped(tmp_path: Path) -> None:
    _save_split(tmp_path, "good", "good")
    # A directory with a table.yaml that won't validate.
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "table.yaml").write_text("not: [a, valid, umf", encoding="utf-8")

    found = discover_umfs(tmp_path)

    assert [d.table for d in found] == ["good"]
