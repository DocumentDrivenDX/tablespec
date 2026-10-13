"""End-to-end tests for guidebook generation and reverse lineage."""

# @covers US-046-AC1
# @covers US-046-AC2
# @covers US-046-AC3
# @covers US-046-AC4

from __future__ import annotations

import json
from pathlib import Path

from tablespec.guidebook import build_reverse_lineage_index, generate
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


def test_generate_writes_pages_index_and_search(tmp_path: Path) -> None:  # US-046-AC1
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"

    written = generate(root=root, output_dir=out)

    # Flat layout: pages at the root, plus index.html and search_index.json.
    assert (out / "orders.html").exists()
    assert (out / "customers.html").exists()
    assert (out / "index.html").exists()
    assert (out / "search_index.json").exists()
    assert set(written) >= {
        out / "orders.html",
        out / "customers.html",
        out / "index.html",
        out / "search_index.json",
    }


def test_search_index_has_table_and_column_entries(tmp_path: Path) -> None:
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"
    generate(root=root, output_dir=out)

    entries = json.loads((out / "search_index.json").read_text(encoding="utf-8"))
    tables = {e["table"] for e in entries}
    assert {"orders", "customers"} <= tables
    # A column-level entry exists for the derived column.
    assert any(e["column"] == "customer_name" for e in entries)


def test_reverse_lineage_links_source_to_consumer(tmp_path: Path) -> None:  # US-046-AC2
    root = _build_corpus(tmp_path / "umfs")

    index = build_reverse_lineage_index(root)

    # customers.name is consumed by orders.customer_name via derivation.
    name_consumers = index.lookup("", "customers", "name")
    assert any(
        c.table == "orders" and c.column == "customer_name" and c.via == "derivation"
        for c in name_consumers
    )
    # customers.id is referenced by orders.customer_id via FK.
    id_consumers = index.lookup("", "customers", "id")
    assert any(
        c.table == "orders" and c.column == "customer_id" and c.via == "fk"
        for c in id_consumers
    )


def test_rendered_page_shows_downstream_link(tmp_path: Path) -> None:  # US-046-AC2
    root = _build_corpus(tmp_path / "umfs")
    out = tmp_path / "guidebook"
    generate(root=root, output_dir=out)

    customers_html = (out / "customers.html").read_text(encoding="utf-8")
    # The customers page links downstream to the orders consumer column.
    assert "orders.html#col-customer_name" in customers_html
    # The orders page links upstream to the customers source column.
    orders_html = (out / "orders.html").read_text(encoding="utf-8")
    assert "customers.html#col-name" in orders_html


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
    assert (out / "crm" / "index.html").exists()
    assert (out / "sales" / "index.html").exists()
    # Top index lists groups.
    top = (out / "index.html").read_text(encoding="utf-8")
    assert "crm/index.html" in top
    assert "sales/index.html" in top


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
