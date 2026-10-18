"""End-to-end tests for guidebook generation."""

# @covers US-046-AC1
# @covers US-046-AC2
# @covers US-046-AC4
# @covers US-046-AC5

from __future__ import annotations

import json
from pathlib import Path
import re

from tablespec.guidebook import generate, render_standalone_table
from tablespec.models.umf import DerivationCandidate, UMFColumnDerivation
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder


def _save(tmp_path: Path, rel_dir: str, umf) -> Path:
    dest = tmp_path / rel_dir
    UMFLoader().save(umf, dest)
    return dest


def _build_corpus(tmp_path: Path) -> Path:
    """Two flat UMFs: ``customers`` (source) and ``orders`` (derives + FKs).

    orders.customer_name is derived from customers.name; orders.customer_id is
    a foreign key into customers.id. This exercises both lineage edge kinds.
    """
    customers = (
        UMFBuilder("customers")
        .column("id", "INTEGER", key_type="primary", description="Customer key")
        .column("name", "VARCHAR", length=80, description="Customer display name")
        .primary_key("id")
        .description("Customer master")
        .table_type("ingested")
        .build()
    )
    orders = (
        UMFBuilder("orders")
        .column("id", "INTEGER", key_type="primary")
        .column("customer_id", "INTEGER")
        .column(
            "customer_name",
            "VARCHAR",
            length=80,
            description="Denormalized customer name",
            derivation=UMFColumnDerivation(
                candidates=[
                    DerivationCandidate(
                        table="customers",
                        column="name",
                        priority=1,
                        reason="Carried from the customer master.",
                    )
                ],
            ),
        )
        .primary_key("id")
        .foreign_key("customer_id", references="customers.id")
        .description("Order facts")
        .table_type("generated")
        .build()
    )
    _save(tmp_path, "customers", customers)
    _save(tmp_path, "orders", orders)
    return tmp_path


def _payload(path: Path) -> dict:
    match = re.search(
        r'<script type="application/json" id="page-data">(.*?)</script>',
        path.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _column(page: dict, name: str) -> dict:
    return next(c for c in page["doc"]["columns"] if c["name"] == name)


def test_generate_writes_pages_index_and_assets(tmp_path: Path) -> None:  # US-046-AC1
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"

    written = generate(root=root, output_dir=out)

    # Flat layout: pages at the root, plus index.html and the shared assets.
    assert set(written) == {
        out / "orders.html",
        out / "customers.html",
        out / "index.html",
        out / "assets" / "site.css",
        out / "assets" / "site.js",
        out / "assets" / "catalog.js",
    }
    index = _payload(out / "index.html")
    assert index["kind"] == "group"
    assert {t["name"] for t in index["doc"]["tables"]} == {"customers", "orders"}


def test_catalog_has_table_and_column_entries(tmp_path: Path) -> None:  # US-046-AC1
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"
    generate(root=root, output_dir=out)

    text = (out / "assets" / "catalog.js").read_text(encoding="utf-8")
    catalog = json.loads(
        text.removeprefix("window.CATALOG = ").rstrip().removesuffix(";")
    )
    [group] = catalog["groups"]
    tables = {t["name"]: t for t in group["tables"]}
    assert set(tables) == {"customers", "orders"}
    assert ["customer_name", "VARCHAR", "Denormalized customer name"] in tables[
        "orders"
    ]["cols"]


def test_used_by_lists_derivation_and_fk_consumers(
    tmp_path: Path,
) -> None:  # US-046-AC2
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"
    generate(root=root, output_dir=out)

    customers = _payload(out / "customers.html")
    # customers.name is consumed by orders.customer_name via derivation.
    assert _column(customers, "name")["used_by"] == [
        {"column_id": "orders.customer_name", "via": "derivation"}
    ]
    # customers.id is referenced by orders.customer_id via FK (downstream only).
    assert _column(customers, "id")["used_by"] == [
        {"column_id": "orders.customer_id", "via": "fk"}
    ]
    assert customers["doc"]["downstream_tables"] == ["orders"]
    # FK is downstream-only: the orders side lists it as a join, not a source.
    orders = _payload(out / "orders.html")
    assert orders["doc"]["foreign_keys"][0]["references_table_id"] == "customers"
    assert orders["doc"]["upstream_tables"] == ["customers"]


def test_lineage_traces_to_source_table(tmp_path: Path) -> None:  # US-046-AC5
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"
    generate(root=root, output_dir=out)

    lineage = _payload(out / "orders.html")["doc"]["lineage"]
    [leaf] = lineage["leaf_summaries"]["orders.customer_name"]
    assert leaf["column_id"] == "customers.name"
    assert leaf["source_system"] == "customers"
    assert lineage["warnings"] == []


def test_grouped_layout_nests_output(tmp_path: Path) -> None:
    root = tmp_path / "umfs"
    customers = UMFBuilder("customers").column("id", "INTEGER").build()
    orders = UMFBuilder("orders").column("id", "INTEGER").build()
    _save(root, "crm/customers", customers)
    _save(root, "sales/orders", orders)
    out = tmp_path / "guidebook"

    generate(root=root, output_dir=out)

    assert (out / "crm" / "customers.html").exists()
    assert (out / "sales" / "orders.html").exists()
    assert _payload(out / "crm" / "index.html")["root"] == "../"
    assert _payload(out / "crm" / "customers.html")["doc"]["id"] == "crm.customers"
    # Home page lists groups.
    home = _payload(out / "index.html")
    assert home["kind"] == "home"
    assert [g["name"] for g in home["doc"]["groups"]] == ["crm", "sales"]


def test_single_group_mode_leaves_indexes_alone(tmp_path: Path) -> None:
    root = tmp_path / "umfs"
    _save(
        root, "crm/customers", UMFBuilder("customers").column("id", "INTEGER").build()
    )
    _save(root, "sales/orders", UMFBuilder("orders").column("id", "INTEGER").build())
    out = tmp_path / "guidebook"

    written = generate(root=root, output_dir=out, group="crm")

    assert out / "crm" / "customers.html" in written
    assert not (out / "index.html").exists()
    assert not (out / "sales" / "orders.html").exists()


def test_malformed_umf_does_not_abort_run(tmp_path: Path) -> None:  # US-046-AC4
    root = _build_corpus(tmp_path / "umfs")
    bad = root / "broken"
    bad.mkdir()
    (bad / "table.yaml").write_text("totally: [not valid", encoding="utf-8")
    out = tmp_path / "guidebook"

    written = generate(root=root, output_dir=out)

    # Good pages still rendered despite the malformed sibling.
    assert (out / "orders.html").exists()
    assert (out / "customers.html").exists()
    assert written


def test_empty_root_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "umfs").mkdir()
    assert generate(root=tmp_path / "umfs", output_dir=tmp_path / "guidebook") == []


def test_self_contained_pages_inline_assets(tmp_path: Path) -> None:
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"

    written = generate(
        root=root, output_dir=out, self_contained=True, provenance_sha="abc123"
    )

    assert not (out / "assets").exists()
    assert out / "orders.html" in written
    html = (out / "orders.html").read_text(encoding="utf-8")
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    page = _payload(out / "orders.html")
    assert page["standalone"] is True
    assert page["provenance_sha"] == "abc123"


def test_render_standalone_table(tmp_path: Path) -> None:
    root = _build_corpus(tmp_path / "umfs")
    html = render_standalone_table(root, "orders")
    assert "<script src=" not in html
    assert '"id":"orders"' in html
