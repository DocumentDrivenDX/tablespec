"""Guidebook domain map page (context map rendered from domain.yaml)."""

# @covers US-051-AC5

from __future__ import annotations

from pathlib import Path

from tablespec.guidebook import generate
from tablespec.models.umf import ForeignKey, Relationships
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder


def _corpus(tmp_path: Path) -> Path:
    elig = tmp_path / "eligibility"
    clm = tmp_path / "claims"
    elig.mkdir()
    clm.mkdir()
    (elig / "domain.yaml").write_text(
        "name: eligibility\nowner: enrollment-team\nexports: [member]\n"
    )
    (clm / "domain.yaml").write_text(
        "name: claims\nowner: claims-team\nexports: [medical_claims]\n"
        "suppliers:\n  eligibility:\n    pattern: conformist\n    consumes: [member]\n"
    )
    member = (
        UMFBuilder("member")
        .column("member_id", "VARCHAR", key_type="primary")
        .primary_key("member_id")
        .build()
    )
    claims = (
        UMFBuilder("medical_claims")
        .column("claim_id", "VARCHAR", key_type="primary")
        .column("member_id", "VARCHAR")
        .primary_key("claim_id")
        .build()
    )
    claims.relationships = Relationships(
        foreign_keys=[
            ForeignKey(
                column="member_id",
                references_table="member",
                references_column="member_id",
                references_domain="eligibility",
                integration="conformist",
            )
        ]
    )
    loader = UMFLoader()
    loader.save(member, elig / "member")
    loader.save(claims, clm / "medical_claims")
    return tmp_path


def test_domain_map_page_is_written_and_linked(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    out = tmp_path / "out"
    written = generate(root, out)

    assert out / "domains.html" in written
    html = (out / "domains.html").read_text(encoding="utf-8")
    assert "Domain Map" in html
    assert "enrollment-team" in html and "claims-team" in html
    # Supplier edge with its pattern chip.
    assert "conformist" in html
    # Cross-domain reference links to the target table page in its group.
    assert "eligibility/member.html" in html
    assert "claims.medical_claims.member_id" in html
    # Direction words are supplier/consumer, never upstream/downstream.
    assert "Supplier" in html and "Consumer" in html
    assert "upstream" not in html.lower()

    top = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="domains.html"' in top


def test_no_domain_map_without_domain_yaml(tmp_path: Path) -> None:
    umf = (
        UMFBuilder("orders")
        .column("id", "INTEGER", key_type="primary")
        .primary_key("id")
        .build()
    )
    UMFLoader().save(umf, tmp_path / "sales" / "orders")
    out = tmp_path / "out"
    written = generate(tmp_path, out)
    assert out / "domains.html" not in written
    assert "domains.html" not in (out / "index.html").read_text(encoding="utf-8")


def test_cross_domain_fk_resolves_as_downstream_on_target(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    out = tmp_path / "out"
    generate(root, out)
    member_page = (out / "eligibility" / "member.html").read_text(encoding="utf-8")
    # The FK from claims shows up as a downstream consumer on the exported table.
    assert "medical_claims" in member_page
