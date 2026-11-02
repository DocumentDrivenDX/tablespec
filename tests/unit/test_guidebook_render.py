"""Tests for guidebook HTML shells (tablespec.guidebook.render)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from tablespec.guidebook.models import ColumnDoc, GroupDoc, HomeDoc, TableDoc
from tablespec.guidebook.render import (
    ASSET_NAMES,
    catalog_script,
    group_depth,
    render_group_page,
    render_home_page,
    render_table_page,
    write_assets,
)
from tablespec.lineage import LineageGraph


def _table_doc(group: str = "") -> TableDoc:
    return TableDoc(
        id=f"{group}.t" if group else "t",
        group=group,
        table="t",
        description="</script><b>x</b>",
        columns=[ColumnDoc(name="a", data_type="VARCHAR")],
        lineage=LineageGraph(),
    )


def _payload(page: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="page-data">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_table_page_round_trips_and_escapes_script_close():
    page = render_table_page(_table_doc(), title="Cat")
    assert _payload(page)["doc"]["description"] == "</script><b>x</b>"
    assert "</script><b>" not in page


def test_asset_paths_follow_group_depth():
    assert group_depth("") == 0
    assert group_depth("a/b") == 2
    home = render_home_page(HomeDoc(title="Cat"))
    assert 'href="assets/site.css"' in home
    group = render_group_page(GroupDoc(name="crm"), title="Cat")
    assert 'src="../assets/catalog.js"' in group
    nested = render_table_page(_table_doc("a/b"), title="Cat")
    assert 'src="../../assets/site.js"' in nested
    assert _payload(nested)["root"] == "../../"


def test_pages_make_no_network_requests():
    for page in (
        render_home_page(HomeDoc(title="Cat")),
        render_table_page(_table_doc(), title="Cat"),
        render_table_page(_table_doc(), title="Cat", self_contained=True),
    ):
        assert 'src="http' not in page
        assert 'href="http' not in page


def test_self_contained_page_is_single_file():
    page = render_table_page(_table_doc(), title="Cat", self_contained=True)
    assert "<script src=" not in page
    assert "<link " not in page
    assert _payload(page)["standalone"] is True


def test_write_assets_and_catalog(tmp_path: Path):
    written = write_assets(tmp_path)
    assert [p.name for p in written] == list(ASSET_NAMES)
    assert all(p.stat().st_size > 0 for p in written)
    assert catalog_script({"groups": []}) == 'window.CATALOG = {"groups":[]};\n'
