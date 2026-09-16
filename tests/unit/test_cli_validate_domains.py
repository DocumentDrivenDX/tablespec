"""`tablespec validate <root>` switches to domain mode when domain.yaml dirs exist."""

# @covers US-051-AC4

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.completeness_validator import PROVENANCE_COLUMNS
from tablespec.models.umf import ForeignKey, Relationships
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _with_provenance(builder: UMFBuilder) -> UMFBuilder:
    """Per-table completeness checks require the provenance columns."""
    for spec in PROVENANCE_COLUMNS.values():
        builder = builder.column(spec["name"], spec["data_type"])
    return builder


def _corpus(tmp_path: Path, *, export_member: bool = True) -> Path:
    elig = tmp_path / "eligibility"
    clm = tmp_path / "claims"
    elig.mkdir()
    clm.mkdir()
    exports = "[member]" if export_member else "[]"
    (elig / "domain.yaml").write_text(f"name: eligibility\nexports: {exports}\n")
    (clm / "domain.yaml").write_text(
        "name: claims\nexports: [medical_claims]\n"
        "suppliers:\n  eligibility:\n    pattern: customer_supplier\n    consumes: [member]\n"
    )
    member = (
        _with_provenance(
            UMFBuilder("member").column("member_id", "VARCHAR", key_type="primary")
        )
        .primary_key("member_id")
        .build()
    )
    claims = (
        _with_provenance(
            UMFBuilder("medical_claims")
            .column("claim_id", "VARCHAR", key_type="primary")
            .column("member_id", "VARCHAR")
        )
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
            )
        ]
    )
    loader = UMFLoader()
    loader.save(member, elig / "member")
    loader.save(claims, clm / "medical_claims")
    return tmp_path


def test_validate_domain_root_passes(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    result = runner.invoke(app, ["validate", str(root)])
    assert result.exit_code == 0, result.output
    assert "2 domains" in result.output


def test_validate_domain_root_reports_cross_domain_error(tmp_path: Path) -> None:
    root = _corpus(tmp_path, export_member=False)
    result = runner.invoke(app, ["validate", str(root)])
    assert result.exit_code == 1
    assert "DOM-XREF" in result.output or "DOM-SUPPLIER" in result.output
    assert "Domain errors" in result.output
