"""Cross-domain validation: exports, suppliers, cross-domain keys, glossary."""

# @covers US-051-AC1
# @covers US-051-AC2
# @covers US-051-AC3
# @covers US-051-AC4

from __future__ import annotations

from pathlib import Path

from tablespec.domain_validator import (
    DomainValidationReport,
    detect_term_drift,
    validate_cross_domain_keys,
    validate_domains,
    validate_exports,
    validate_suppliers,
    validate_terms,
)
from tablespec.domains import discover_domains, find_domain_dirs, load_domain_dir
from tablespec.models.umf import ForeignKey, Relationships
from tablespec.umf_loader import UMFLoader
from tablespec.validator import ValidationContext, is_domain_root, validate_domain_root
from tests.builders import UMFBuilder

ELIGIBILITY_DOMAIN = """\
name: eligibility
owner: enrollment-team
exports: [member]
glossary: glossary.yaml
"""

CLAIMS_DOMAIN = """\
name: claims
owner: claims-team
exports: [medical_claims]
glossary: glossary.yaml
suppliers:
  eligibility:
    pattern: customer_supplier
    consumes: [member]
"""


def _member_umf():
    return (
        UMFBuilder("member")
        .column("member_id", "VARCHAR", key_type="primary")
        .column("first_name", "VARCHAR", length=50)
        .primary_key("member_id")
        .build()
    )


def _claims_umf(*, fk_kwargs: dict | None = None):
    umf = (
        UMFBuilder("medical_claims")
        .column("claim_id", "VARCHAR", key_type="primary")
        .column("member_id", "VARCHAR")
        .primary_key("claim_id")
        .build()
    )
    kwargs = {
        "column": "member_id",
        "references_table": "member",
        "references_column": "member_id",
        "references_domain": "eligibility",
        "integration": "customer_supplier",
    }
    if fk_kwargs:
        kwargs.update(fk_kwargs)
    umf.relationships = Relationships(foreign_keys=[ForeignKey(**kwargs)])
    return umf


def _write_corpus(
    root: Path,
    *,
    eligibility_yaml: str = ELIGIBILITY_DOMAIN,
    claims_yaml: str = CLAIMS_DOMAIN,
    member=None,
    claims=None,
    eligibility_glossary: str = "member:\n  definition: An enrolled person\n",
    claims_glossary: str = "member:\n  definition: An enrolled person\nclaim:\n  definition: A billed encounter\n",
) -> Path:
    elig = root / "eligibility"
    clm = root / "claims"
    elig.mkdir(parents=True)
    clm.mkdir(parents=True)
    (elig / "domain.yaml").write_text(eligibility_yaml)
    (clm / "domain.yaml").write_text(claims_yaml)
    (elig / "glossary.yaml").write_text(eligibility_glossary)
    (clm / "glossary.yaml").write_text(claims_glossary)
    loader = UMFLoader()
    loader.save(member or _member_umf(), elig / "member")
    loader.save(claims or _claims_umf(), clm / "medical_claims")
    return root


def _report(root: Path) -> DomainValidationReport:
    return validate_domains(discover_domains(root))


# ---------------------------------------------------------------- discovery


def test_find_domain_dirs_direct_children_only(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    (tmp_path / "eligibility" / "nested").mkdir()
    (tmp_path / "eligibility" / "nested" / "domain.yaml").write_text("name: nested\n")
    assert [d.name for d in find_domain_dirs(tmp_path)] == ["claims", "eligibility"]


def test_find_domain_dirs_includes_root_itself(tmp_path: Path) -> None:
    d = tmp_path / "claims"
    d.mkdir()
    (d / "domain.yaml").write_text("name: claims\n")
    assert find_domain_dirs(d) == [d.resolve()]


def test_load_domain_dir_loads_tables_and_glossary(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    loaded = load_domain_dir(tmp_path / "claims")
    assert loaded.name == "claims"
    assert set(loaded.tables) == {"medical_claims"}
    assert loaded.glossary is not None and loaded.glossary.has("claim")
    assert loaded.load_errors == []


def test_discover_domains_skips_invalid_domain_yaml(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    (tmp_path / "claims" / "domain.yaml").write_text("name: wrong_name\n")
    domains = discover_domains(tmp_path)
    assert set(domains) == {"eligibility"}


def test_bad_table_is_recorded_not_fatal(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    bad = tmp_path / "claims" / "broken"
    bad.mkdir()
    (bad / "table.yaml").write_text("table_name: [not, valid]\n")
    loaded = load_domain_dir(tmp_path / "claims")
    assert set(loaded.tables) == {"medical_claims"}
    assert loaded.load_errors and "broken" in loaded.load_errors[0]
    report = validate_domains({"claims": loaded})
    assert any(f.rule == "DOM-LOAD" for f in report.errors)


# ---------------------------------------------------------------- happy path


def test_valid_corpus_has_no_errors(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    report = _report(tmp_path)
    assert report.ok, [str(f) for f in report.errors]
    assert report.warnings == []


# ---------------------------------------------------------------- DOM-EXPORT


def test_export_must_name_a_table(tmp_path: Path) -> None:
    _write_corpus(tmp_path, eligibility_yaml="name: eligibility\nexports: [ghost]\n")
    findings = validate_exports(load_domain_dir(tmp_path / "eligibility"))
    assert [f.rule for f in findings] == ["DOM-EXPORT"]
    assert "not a table" in findings[0].message


def test_export_must_declare_primary_key(tmp_path: Path) -> None:
    no_pk = UMFBuilder("member").column("member_id", "VARCHAR").build()
    _write_corpus(tmp_path, member=no_pk)
    findings = validate_exports(load_domain_dir(tmp_path / "eligibility"))
    assert findings and "primary_key" in findings[0].message


# ---------------------------------------------------------------- DOM-SUPPLIER


def test_supplier_must_exist(tmp_path: Path) -> None:
    yaml_text = CLAIMS_DOMAIN.replace("eligibility:", "provider:")
    _write_corpus(tmp_path, claims_yaml=yaml_text)
    domains = discover_domains(tmp_path)
    findings = validate_suppliers(domains["claims"], domains)
    assert findings and "not found" in findings[0].message


def test_consumed_table_must_be_exported_by_supplier(tmp_path: Path) -> None:
    _write_corpus(tmp_path, eligibility_yaml="name: eligibility\nexports: []\n")
    domains = discover_domains(tmp_path)
    findings = validate_suppliers(domains["claims"], domains)
    assert findings and "not in domain 'eligibility' exports" in findings[0].message


def test_domain_cannot_supply_itself(tmp_path: Path) -> None:
    yaml_text = "name: claims\nsuppliers:\n  claims:\n    pattern: partnership\n"
    _write_corpus(tmp_path, claims_yaml=yaml_text)
    domains = discover_domains(tmp_path)
    findings = validate_suppliers(domains["claims"], domains)
    assert findings and "itself" in findings[0].message


# ---------------------------------------------------------------- DOM-XREF


def test_cross_domain_fk_must_target_primary_key(tmp_path: Path) -> None:
    claims = _claims_umf(fk_kwargs={"references_column": "first_name"})
    _write_corpus(tmp_path, claims=claims)
    domains = discover_domains(tmp_path)
    findings = validate_cross_domain_keys(domains["claims"], domains)
    assert findings and "not a primary-key column" in findings[0].message


def test_cross_domain_fk_must_target_exported_table(tmp_path: Path) -> None:
    _write_corpus(tmp_path, eligibility_yaml="name: eligibility\nexports: []\n")
    domains = discover_domains(tmp_path)
    findings = validate_cross_domain_keys(domains["claims"], domains)
    assert any("not in 'eligibility' exports" in f.message for f in findings)


def test_cross_domain_fk_requires_declared_supplier(tmp_path: Path) -> None:
    _write_corpus(tmp_path, claims_yaml="name: claims\nexports: [medical_claims]\n")
    domains = discover_domains(tmp_path)
    findings = validate_cross_domain_keys(domains["claims"], domains)
    assert any("not declared" in f.message for f in findings)


def test_cross_domain_fk_to_unknown_domain(tmp_path: Path) -> None:
    claims = _claims_umf(fk_kwargs={"references_domain": "provider"})
    _write_corpus(tmp_path, claims=claims)
    domains = discover_domains(tmp_path)
    findings = validate_cross_domain_keys(domains["claims"], domains)
    assert findings and "was not found" in findings[0].message


def test_qualified_references_table_counts_as_cross_domain(tmp_path: Path) -> None:
    claims = _claims_umf(
        fk_kwargs={
            "references_table": "eligibility.member",
            "references_domain": None,
            "integration": None,
        }
    )
    _write_corpus(tmp_path, claims=claims)
    assert _report(tmp_path).ok


def test_local_fk_is_not_a_cross_domain_finding(tmp_path: Path) -> None:
    claims = _claims_umf(
        fk_kwargs={
            "references_table": "medical_claims",
            "references_column": "claim_id",
            "references_domain": None,
            "integration": None,
        }
    )
    _write_corpus(tmp_path, claims=claims)
    domains = discover_domains(tmp_path)
    assert validate_cross_domain_keys(domains["claims"], domains) == []


# ---------------------------------------------------------------- DOM-TERM / DOM-DRIFT


def test_term_must_exist_in_glossary(tmp_path: Path) -> None:
    claims = _claims_umf()
    claims.term = "Encounter"
    claims.columns[1].term = "Member"  # present via glossary
    _write_corpus(tmp_path, claims=claims)
    findings = validate_terms(load_domain_dir(tmp_path / "claims"))
    assert [f.entity for f in findings] == ["medical_claims"]
    assert "Encounter" in findings[0].message


def test_terms_skipped_when_no_glossary(tmp_path: Path) -> None:
    claims = _claims_umf()
    claims.term = "Anything"
    _write_corpus(
        tmp_path,
        claims=claims,
        claims_yaml="name: claims\nexports: [medical_claims]\nsuppliers:\n  eligibility:\n    pattern: conformist\n    consumes: [member]\n",
    )
    assert validate_terms(load_domain_dir(tmp_path / "claims")) == []


def test_term_drift_is_a_warning_not_an_error(tmp_path: Path) -> None:
    _write_corpus(
        tmp_path,
        claims_glossary="member:\n  definition: A person on a claim\n",
    )
    report = _report(tmp_path)
    assert report.ok
    assert [f.rule for f in report.warnings] == ["DOM-DRIFT"]
    assert "eligibility" in report.warnings[0].message


def test_identical_definitions_do_not_drift(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    assert detect_term_drift(discover_domains(tmp_path)) == []


# ---------------------------------------------------------------- validator entry point


def test_is_domain_root_and_validate_domain_root(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    assert is_domain_root(tmp_path)
    assert not is_domain_root(tmp_path / "eligibility" / "member")
    table_results, report = validate_domain_root(tmp_path, ValidationContext())
    assert set(table_results) == {"claims", "eligibility"}
    assert "medical_claims" in table_results["claims"]
    assert report.ok


def test_report_by_domain_groups_findings(tmp_path: Path) -> None:
    _write_corpus(tmp_path, eligibility_yaml="name: eligibility\nexports: [ghost]\n")
    report = _report(tmp_path)
    grouped = report.by_domain()
    assert "eligibility" in grouped
    assert all(f.domain == "eligibility" for f in grouped["eligibility"])
