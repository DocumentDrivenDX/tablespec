"""Domain metadata models, glossary loading, and the FK domain fields."""

# @covers US-051-AC1
# @covers US-051-AC2

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from tablespec.models.domain import (
    DomainLoadError,
    DomainMetadata,
    Glossary,
    IntegrationPattern,
    load_domain,
    load_glossary,
)
from tablespec.models.umf import UMF, ForeignKey, UMFColumn
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder


class TestDomainMetadata:
    def test_minimal(self) -> None:
        meta = DomainMetadata(name="claims")
        assert meta.exports == []
        assert meta.suppliers == {}
        assert meta.glossary is None

    def test_full(self) -> None:
        meta = DomainMetadata(
            name="claims",
            owner="claims-data",
            exports=["medical_claims"],
            glossary="glossary.yaml",
            suppliers={
                "eligibility": {"pattern": "customer_supplier", "consumes": ["member"]}
            },
        )
        assert (
            meta.suppliers["eligibility"].pattern
            is IntegrationPattern.CUSTOMER_SUPPLIER
        )
        assert meta.exports_table("MEDICAL_CLAIMS")
        assert not meta.exports_table("claim_lines")

    @pytest.mark.parametrize("bad", ["Claims", "claims-v2", "1claims", "a.b"])
    def test_name_must_be_qualifier_safe(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            DomainMetadata(name=bad)

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DomainMetadata(name="claims", export=["x"])  # typo of exports

    def test_unknown_pattern_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DomainMetadata(name="claims", suppliers={"x": {"pattern": "friendly"}})


class TestLoadDomain:
    def test_load_ok(self, tmp_path: Path) -> None:
        d = tmp_path / "claims"
        d.mkdir()
        (d / "domain.yaml").write_text("name: claims\nowner: team\nexports: [a]\n")
        meta = load_domain(d)
        assert meta.name == "claims"
        assert meta.owner == "team"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(DomainLoadError, match="No domain.yaml"):
            load_domain(tmp_path)

    def test_name_must_match_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "claims"
        d.mkdir()
        (d / "domain.yaml").write_text("name: billing\n")
        with pytest.raises(DomainLoadError, match="must match its directory"):
            load_domain(d)

    def test_invalid_shape_reports_path(self, tmp_path: Path) -> None:
        d = tmp_path / "claims"
        d.mkdir()
        (d / "domain.yaml").write_text("- not\n- a mapping\n")
        with pytest.raises(DomainLoadError, match="top level must be a mapping"):
            load_domain(d)


class TestGlossary:
    def test_has_and_alias_lookup(self) -> None:
        g = Glossary(
            terms={"Member": {"definition": "An enrolled person", "aliases": ["mbr"]}}
        )
        assert g.has("member")
        assert g.has("MBR")
        assert not g.has("provider")
        assert g.definition_of("mbr") == "An enrolled person"
        assert g.definition_of("provider") is None

    def test_load_bare_mapping_and_terms_wrapper(self, tmp_path: Path) -> None:
        d = tmp_path / "claims"
        d.mkdir()
        (d / "bare.yaml").write_text("member:\n  definition: enrolled person\n")
        (d / "wrapped.yaml").write_text(
            "terms:\n  member:\n    definition: enrolled person\n"
        )
        for fname in ("bare.yaml", "wrapped.yaml"):
            meta = DomainMetadata(name="claims", glossary=fname)
            g = load_glossary(d, meta)
            assert g is not None and g.has("member")

    def test_no_glossary_declared(self, tmp_path: Path) -> None:
        assert load_glossary(tmp_path, DomainMetadata(name="claims")) is None

    def test_missing_glossary_file(self, tmp_path: Path) -> None:
        d = tmp_path / "claims"
        d.mkdir()
        with pytest.raises(DomainLoadError, match="Glossary not found"):
            load_glossary(d, DomainMetadata(name="claims", glossary="nope.yaml"))


class TestForeignKeyDomainFields:
    def _fk(self, **kw) -> ForeignKey:
        return ForeignKey(
            column="member_id", references_table="member", references_column="id", **kw
        )

    def test_references_domain_populates_legacy_and_cross_pipeline(self) -> None:
        fk = self._fk(references_domain="eligibility")
        assert fk.references_pipeline == "eligibility"
        assert fk.cross_pipeline is True
        assert fk.target_domain == "eligibility"
        assert fk.target_table == "member"

    def test_legacy_references_pipeline_populates_domain(self) -> None:
        fk = self._fk(references_pipeline="eligibility")
        assert fk.references_domain == "eligibility"
        assert fk.cross_pipeline is True

    def test_disagreement_is_an_error(self) -> None:
        with pytest.raises(ValidationError, match="disagree"):
            self._fk(references_domain="a", references_pipeline="b")

    def test_qualified_references_table_yields_target_domain(self) -> None:
        fk = ForeignKey(
            column="member_id",
            references_table="eligibility.member",
            references_column="id",
        )
        assert fk.target_domain == "eligibility"
        assert fk.target_table == "member"
        assert fk.references_domain is None  # only the explicit field is normalized

    def test_local_reference_has_no_target_domain(self) -> None:
        fk = self._fk()
        assert fk.target_domain is None
        assert fk.cross_pipeline is False

    def test_integration_pattern_enum(self) -> None:
        fk = self._fk(references_domain="eligibility", integration="conformist")
        assert fk.integration is IntegrationPattern.CONFORMIST
        with pytest.raises(ValidationError):
            self._fk(integration="friendly")

    def test_unknown_keys_are_rejected_not_dropped(self) -> None:
        with pytest.raises(ValidationError):
            self._fk(relationship_kind="conformist")


class TestTermFields:
    def test_term_round_trips_through_split_format(self, tmp_path: Path) -> None:
        umf = (
            UMFBuilder("medical_claims")
            .column("claim_id", "VARCHAR", key_type="primary")
            .primary_key("claim_id")
            .build()
        )
        umf.term = "Claim"
        umf.columns[0].term = "Claim Identifier"
        loader = UMFLoader()
        loader.save(umf, tmp_path / "medical_claims")
        back = loader.load(tmp_path / "medical_claims")
        assert back.term == "Claim"
        assert back.columns[0].term == "Claim Identifier"

    def test_term_is_independent_of_canonical_name(self) -> None:
        col = UMFColumn(
            name="mbr_id", canonical_name="MBR ID", term="Member", data_type="VARCHAR"
        )
        assert col.canonical_name == "MBR ID"
        assert col.term == "Member"
        umf = UMF(
            version="1.0",
            table_name="t",
            canonical_name="T",
            term="Thing",
            columns=[col],
        )
        assert umf.term == "Thing"
