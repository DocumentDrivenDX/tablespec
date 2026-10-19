"""Published-language versioning: version ranges, pins, baseline diff, DOM-COMPAT."""

# @covers US-052-AC1
# @covers US-052-AC2
# @covers US-052-AC3
# @covers US-052-AC4

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest
from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.completeness_validator import PROVENANCE_COLUMNS
from tablespec.domain_validator import (
    published_language_changes,
    validate_domains,
    validate_published_language,
    validate_suppliers,
    validate_version_declared,
)
from tablespec.domains import discover_domains
from tablespec.models.domain import (
    DomainMetadata,
    SupplierRelationship,
    is_major_bump,
    parse_semver,
    validate_version_range,
    version_satisfies,
)
from tablespec.models.umf import ForeignKey, Relationships
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


# ---------------------------------------------------------------- pure helpers


class TestVersionHelpers:
    def test_parse_semver(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)
        with pytest.raises(ValueError):
            parse_semver("1.2")
        with pytest.raises(ValueError):
            parse_semver("1.2.3-beta")

    @pytest.mark.parametrize(
        ("version", "constraint", "ok"),
        [
            ("1.4.0", ">=1.0.0,<2.0.0", True),
            ("2.0.0", ">=1.0.0,<2.0.0", False),
            ("0.9.9", ">=1.0.0", False),
            ("1.0.0", "==1.0.0", True),
            ("1.0.1", "!=1.0.0", True),
            ("1.0.0", ">1.0.0", False),
            ("1.0.0", "<=1.0.0", True),
        ],
    )
    def test_version_satisfies(self, version: str, constraint: str, ok: bool) -> None:
        assert version_satisfies(version, constraint) is ok

    def test_invalid_range_rejected(self) -> None:
        for bad in ["", "~=1.0", ">=1.0", "1.0.0", ">= 1.0.0 || <2.0.0"]:
            with pytest.raises(ValueError):
                validate_version_range(bad)

    def test_is_major_bump(self) -> None:
        assert is_major_bump("1.9.9", "2.0.0")
        assert not is_major_bump("1.0.0", "1.1.0")
        assert not is_major_bump("2.0.0", "1.0.0")


class TestModelVersionFields:
    def test_domain_version_must_be_semver_core(self) -> None:
        assert DomainMetadata(name="claims", version="1.0.0").version == "1.0.0"
        for bad in ["1.0", "v1.0.0", "1.0.0-rc1"]:
            with pytest.raises(ValidationError):
                DomainMetadata(name="claims", version=bad)

    def test_supplier_version_range_validated(self) -> None:
        rel = SupplierRelationship(pattern="conformist", version=">=1.0.0, <2.0.0")
        assert rel.version == ">=1.0.0,<2.0.0"
        with pytest.raises(ValidationError):
            SupplierRelationship(pattern="conformist", version="latest")


# ---------------------------------------------------------------- fixtures


def _with_provenance(builder: UMFBuilder) -> UMFBuilder:
    for spec in PROVENANCE_COLUMNS.values():
        builder = builder.column(spec["name"], spec["data_type"])
    return builder


def _member(*, extra_column: bool = False, drop_name: bool = False):
    b = UMFBuilder("member").column("member_id", "VARCHAR", key_type="primary")
    if not drop_name:
        b = b.column("first_name", "VARCHAR", length=50)
    if extra_column:
        b = b.column("last_name", "VARCHAR", length=50)
    return _with_provenance(b).primary_key("member_id").build()


def _claims():
    umf = (
        _with_provenance(
            UMFBuilder("medical_claims")
            .column("claim_id", "VARCHAR", key_type="primary")
            .column("member_id", "VARCHAR")
        )
        .primary_key("claim_id")
        .build()
    )
    umf.relationships = Relationships(
        foreign_keys=[
            ForeignKey(
                column="member_id",
                references_table="member",
                references_column="member_id",
                references_domain="eligibility",
            )
        ]
    )
    return umf


def _corpus(
    root: Path,
    *,
    elig_version: str | None = "1.0.0",
    elig_exports: str = "[member]",
    claims_pin: str | None = ">=1.0.0,<2.0.0",
    pattern: str = "customer_supplier",
    consumes: str = "[member]",
    member=None,
) -> Path:
    elig = root / "eligibility"
    clm = root / "claims"
    elig.mkdir(parents=True)
    clm.mkdir(parents=True)
    version_line = f"version: {elig_version}\n" if elig_version else ""
    (elig / "domain.yaml").write_text(
        f"name: eligibility\n{version_line}exports: {elig_exports}\n"
    )
    pin_line = f"    version: '{claims_pin}'\n" if claims_pin else ""
    (clm / "domain.yaml").write_text(
        "name: claims\nversion: 1.0.0\nexports: [medical_claims]\n"
        f"suppliers:\n  eligibility:\n    pattern: {pattern}\n"
        f"    consumes: {consumes}\n{pin_line}"
    )
    loader = UMFLoader()
    loader.save(member or _member(), elig / "member")
    loader.save(_claims(), clm / "medical_claims")
    return root


# ---------------------------------------------------------------- DOM-PIN / DOM-WAYS / DOM-VERSION


def test_pin_satisfied(tmp_path: Path) -> None:
    _corpus(tmp_path)
    report = validate_domains(discover_domains(tmp_path))
    assert report.ok, [str(f) for f in report.errors]


def test_pin_not_satisfied(tmp_path: Path) -> None:
    _corpus(tmp_path, elig_version="2.0.0")
    domains = discover_domains(tmp_path)
    findings = validate_suppliers(domains["claims"], domains)
    assert [f.rule for f in findings] == ["DOM-PIN"]
    assert "2.0.0 does not satisfy" in findings[0].message


def test_pin_against_unversioned_supplier(tmp_path: Path) -> None:
    _corpus(tmp_path, elig_version=None)
    domains = discover_domains(tmp_path)
    findings = validate_suppliers(domains["claims"], domains)
    assert [f.rule for f in findings] == ["DOM-PIN"]
    assert "declares no version" in findings[0].message


def test_separate_ways_with_consumes_is_an_error(tmp_path: Path) -> None:
    _corpus(tmp_path, pattern="separate_ways", claims_pin=None)
    domains = discover_domains(tmp_path)
    report = validate_domains(domains)
    rules = [f.rule for f in report.errors]
    # Once for the consumes list, once for the FK into the separate_ways supplier.
    assert rules.count("DOM-WAYS") == 2


def test_separate_ways_without_consumes_is_fine(tmp_path: Path) -> None:
    _corpus(tmp_path, pattern="separate_ways", claims_pin=None, consumes="[]")
    # Remove the FK so nothing crosses the edge.
    loader = UMFLoader()
    claims = loader.load(tmp_path / "claims" / "medical_claims")
    claims.relationships = None
    loader.save(claims, tmp_path / "claims" / "medical_claims")
    domains = discover_domains(tmp_path)
    assert [f.rule for f in validate_suppliers(domains["claims"], domains)] == []


def test_unversioned_exporting_domain_warns(tmp_path: Path) -> None:
    _corpus(tmp_path, elig_version=None, claims_pin=None)
    domains = discover_domains(tmp_path)
    findings = validate_version_declared(domains["eligibility"])
    assert [f.rule for f in findings] == ["DOM-VERSION"]
    report = validate_domains(domains)
    assert report.ok  # warning only
    assert any(f.rule == "DOM-VERSION" for f in report.warnings)


# ---------------------------------------------------------------- published language diff


def test_no_change_no_findings(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new")
    changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), discover_domains(tmp_path / "new")
    )
    assert changes == [] and findings == []


def test_added_nullable_column_is_info_and_needs_no_bump(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", member=_member(extra_column=True))
    changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), discover_domains(tmp_path / "new")
    )
    assert findings == []
    assert any(c.change.startswith("added") and c.severity == "info" for c in changes)


def test_removed_column_without_major_bump_is_dom_compat(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", member=_member(drop_name=True), elig_version="1.1.0")
    changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), discover_domains(tmp_path / "new")
    )
    assert any(c.severity == "breaking" for c in changes)
    assert [f.rule for f in findings] == ["DOM-COMPAT"]
    assert "1.0.0 -> 1.1.0" in findings[0].message


def test_removed_column_with_major_bump_is_accepted(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(
        tmp_path / "new",
        member=_member(drop_name=True),
        elig_version="2.0.0",
        claims_pin=">=2.0.0,<3.0.0",
    )
    _changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), discover_domains(tmp_path / "new")
    )
    assert findings == []


def test_removed_export_is_breaking(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", elig_exports="[]", claims_pin=None)
    changes = published_language_changes(
        discover_domains(tmp_path / "old")["eligibility"],
        discover_domains(tmp_path / "new")["eligibility"],
        "eligibility",
    )
    assert [c.change for c in changes] == ["export_removed"]
    assert changes[0].severity == "breaking"


def test_breaking_change_with_missing_version_is_dom_compat(tmp_path: Path) -> None:
    _corpus(tmp_path / "old", elig_version=None, claims_pin=None)
    _corpus(
        tmp_path / "new",
        elig_version=None,
        claims_pin=None,
        member=_member(drop_name=True),
    )
    _changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), discover_domains(tmp_path / "new")
    )
    assert [f.rule for f in findings] == ["DOM-COMPAT"]
    assert "unset -> unset" in findings[0].message


def test_removed_domain_with_exports_is_breaking(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    (tmp_path / "new").mkdir()
    changes, findings = validate_published_language(
        discover_domains(tmp_path / "old"), {}
    )
    assert [c.change for c in changes] == ["domain_removed", "domain_removed"]
    assert findings == []  # nothing to version on the new side


# ---------------------------------------------------------------- CLI --baseline


def test_cli_baseline_reports_and_fails_on_dom_compat(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", member=_member(drop_name=True), elig_version="1.1.0")
    result = runner.invoke(
        app, ["validate", str(tmp_path / "new"), "--baseline", str(tmp_path / "old")]
    )
    assert result.exit_code == 1, result.output
    assert "Published-language changes" in result.output
    assert "DOM-COMPAT" in result.output


def test_cli_baseline_clean(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", member=_member(extra_column=True))
    result = runner.invoke(
        app, ["validate", str(tmp_path / "new"), "--baseline", str(tmp_path / "old")]
    )
    assert result.exit_code == 0, result.output
    assert "Published-language changes" in result.output
    assert "2 domains" in result.output
