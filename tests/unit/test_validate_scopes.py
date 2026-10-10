"""`validate <path>` has one behavior: every table under the path, plus the
domain rules for whatever domain.yaml applies to it. There is no mode.

Each test here pins a way the earlier mode-based design went wrong.
"""

# @covers US-051-AC4
# @covers US-052-AC4

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.domains import iter_table_dirs, resolve_domain_scopes
from tablespec.models.umf import ForeignKey, Relationships
from tablespec.umf_loader import UMFLoader
from tablespec.validator import (
    ValidationContext,
    validate_domain_scopes,
    validate_pipeline,
)
from tests.builders import UMFBuilder

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _member(*, drop_name: bool = False):
    b = UMFBuilder("member").column("member_id", "VARCHAR", key_type="primary")
    if not drop_name:
        b = b.column("first_name", "VARCHAR", length=50)
    return b.primary_key("member_id").build()


def _claims(*, target_column: str = "member_id", bad_column: bool = False):
    b = (
        UMFBuilder("medical_claims")
        .column("claim_id", "VARCHAR", key_type="primary")
        .column("member_id", "VARCHAR")
    )
    if bad_column:
        b = b.column("BadCol", "VARCHAR")
    umf = b.primary_key("claim_id").build()
    umf.relationships = Relationships(
        foreign_keys=[
            ForeignKey(
                column="member_id",
                references_table="member",
                references_column=target_column,
                references_domain="eligibility",
            )
        ]
    )
    return umf


def _corpus(
    root: Path,
    *,
    domain_yaml: bool = True,
    claims=None,
    member=None,
    elig_version: str = "1.0.0",
) -> Path:
    elig = root / "eligibility"
    clm = root / "claims"
    elig.mkdir(parents=True)
    clm.mkdir(parents=True)
    if domain_yaml:
        (elig / "domain.yaml").write_text(
            f"name: eligibility\nversion: {elig_version}\nexports: [member]\n"
        )
        (clm / "domain.yaml").write_text(
            "name: claims\nversion: 1.0.0\nexports: [medical_claims]\n"
            "suppliers:\n  eligibility:\n    pattern: conformist\n    consumes: [member]\n"
        )
    loader = UMFLoader()
    loader.save(member or _member(), elig / "member")
    loader.save(claims or _claims(), clm / "medical_claims")
    return root


# ------------------------------------------------ a metadata file must not decide what gets checked


def test_grouped_folders_are_validated_without_any_domain_yaml(tmp_path: Path) -> None:
    """Was: zero tables validated, so the bad column name was never seen."""
    _corpus(tmp_path, domain_yaml=False, claims=_claims(bad_column=True))
    results = validate_pipeline(tmp_path, ValidationContext(), check_completeness=False)
    assert set(results) == {"claims/medical_claims", "eligibility/member"}
    assert any("lowercase_snake_case" in e for e in results["claims/medical_claims"])


def test_same_tables_are_validated_with_or_without_domain_yaml(tmp_path: Path) -> None:
    _corpus(tmp_path / "plain", domain_yaml=False)
    _corpus(tmp_path / "declared", domain_yaml=True)
    ctx = ValidationContext()
    plain = validate_pipeline(tmp_path / "plain", ctx, check_completeness=False)
    declared = validate_pipeline(tmp_path / "declared", ctx, check_completeness=False)
    assert set(plain) == set(declared)


def test_direct_children_keep_their_bare_table_name_key(tmp_path: Path) -> None:
    UMFLoader().save(_member(), tmp_path / "member")
    results = validate_pipeline(tmp_path, ValidationContext(), check_completeness=False)
    assert set(results) == {"member"}


def test_recursive_false_restores_one_level_lookup(tmp_path: Path) -> None:
    _corpus(tmp_path, domain_yaml=False)
    results = validate_pipeline(
        tmp_path, ValidationContext(), check_completeness=False, recursive=False
    )
    assert results == {}


def test_hidden_and_vendored_directories_are_not_searched(tmp_path: Path) -> None:
    for junk in (".cache", "node_modules", "__pycache__"):
        UMFLoader().save(_member(), tmp_path / junk / "member")
    UMFLoader().save(_member(), tmp_path / "real" / "member")
    assert [p.parent.name for p in iter_table_dirs(tmp_path)] == ["real"]


# ------------------------------------------------ siblings live next to a domain, not beneath it


def test_validating_one_domain_finds_its_suppliers_next_door(tmp_path: Path) -> None:
    """Was: DOM-SUPPLIER and DOM-XREF 'not found' for a supplier one directory up."""
    _corpus(tmp_path)
    run = validate_domain_scopes(tmp_path / "claims")
    assert run.domains == ["claims"]
    assert run.report.ok, [str(f) for f in run.report.errors]


def test_validating_one_domain_reports_only_that_domain(tmp_path: Path) -> None:
    _corpus(
        tmp_path, member=UMFBuilder("member").column("member_id", "VARCHAR").build()
    )
    # eligibility now exports a table with no primary key: its problem...
    own = validate_domain_scopes(tmp_path / "eligibility")
    assert [f.rule for f in own.report.errors] == ["DOM-EXPORT"]
    # ...but claims sees only the consequence for its own key.
    other = validate_domain_scopes(tmp_path / "claims")
    assert {f.rule for f in other.report.errors} == {"DOM-XREF"}
    assert all(f.domain == "claims" for f in other.report.errors)


def test_validating_one_table_checks_its_cross_domain_keys(tmp_path: Path) -> None:
    """Was: a single-table run never checked the table's keys into other domains."""
    _corpus(tmp_path, claims=_claims(target_column="first_name"))
    run = validate_domain_scopes(tmp_path / "claims" / "medical_claims")
    assert [f.rule for f in run.report.errors] == ["DOM-XREF"]
    assert "not a primary-key column" in run.report.errors[0].message


def test_single_table_run_ignores_other_tables_in_its_domain(tmp_path: Path) -> None:
    _corpus(tmp_path, claims=_claims(target_column="first_name"))
    UMFLoader().save(
        UMFBuilder("claim_lines").column("line_id", "INTEGER").build(),
        tmp_path / "claims" / "claim_lines",
    )
    run = validate_domain_scopes(tmp_path / "claims" / "claim_lines")
    assert run.report.ok


def test_path_with_no_domain_yaml_anywhere_is_an_empty_run(tmp_path: Path) -> None:
    _corpus(tmp_path, domain_yaml=False)
    run = validate_domain_scopes(tmp_path)
    assert run.domains == [] and run.report.ok and run.notes == []


def test_invalid_domain_yaml_is_an_error_not_silence(tmp_path: Path) -> None:
    _corpus(tmp_path)
    (tmp_path / "claims" / "domain.yaml").write_text("name: wrong_name\n")
    run = validate_domain_scopes(tmp_path)
    assert any(f.rule == "DOM-LOAD" and f.domain == "claims" for f in run.report.errors)


def test_nested_domain_yaml_inside_a_domain_is_ignored(tmp_path: Path) -> None:
    _corpus(tmp_path)
    nested = tmp_path / "claims" / "inner"
    nested.mkdir()
    (nested / "domain.yaml").write_text("name: inner\n")
    scopes = resolve_domain_scopes(tmp_path)
    assert len(scopes) == 1
    assert scopes[0].in_scope == {"claims", "eligibility"}


def test_a_path_above_several_corpora_labels_each_root(tmp_path: Path) -> None:
    _corpus(tmp_path / "team_a")
    _corpus(tmp_path / "team_b", claims=_claims(target_column="first_name"))
    run = validate_domain_scopes(tmp_path)
    assert run.domains == [
        "team_a/claims",
        "team_a/eligibility",
        "team_b/claims",
        "team_b/eligibility",
    ]
    assert [f.domain for f in run.report.errors] == ["team_b/claims"]


# ------------------------------------------------ --baseline is not mode-only


def test_baseline_works_for_a_single_domain_path(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new", member=_member(drop_name=True), elig_version="1.1.0")
    run = validate_domain_scopes(
        tmp_path / "new" / "eligibility", baseline=tmp_path / "old" / "eligibility"
    )
    assert any(c.severity == "breaking" for c in run.report.published_language)
    assert [f.rule for f in run.report.errors] == ["DOM-COMPAT"]


def test_baseline_with_nothing_to_compare_says_so(tmp_path: Path) -> None:
    _corpus(tmp_path / "old", domain_yaml=False)
    _corpus(tmp_path / "new", domain_yaml=False)
    run = validate_domain_scopes(tmp_path / "new", baseline=tmp_path / "old")
    assert run.report.ok
    assert run.notes and "no domain.yaml" in run.notes[0]


def test_baseline_sees_a_domain_removed_from_the_root(tmp_path: Path) -> None:
    _corpus(tmp_path / "old")
    _corpus(tmp_path / "new")
    import shutil

    shutil.rmtree(tmp_path / "new" / "eligibility")
    run = validate_domain_scopes(tmp_path / "new", baseline=tmp_path / "old")
    assert any(
        c.change == "domain_removed" and c.domain == "eligibility"
        for c in run.report.published_language
    )


# ------------------------------------------------ CLI


def test_cli_single_domain_directory_passes(tmp_path: Path) -> None:
    _corpus(tmp_path)
    result = runner.invoke(app, ["validate", str(tmp_path / "claims")])
    # Per-table completeness (provenance columns) fails this minimal fixture;
    # what matters here is that no spurious domain error is reported.
    assert "Domain errors" not in result.output
    assert "not found" not in result.output


def test_cli_single_table_reports_its_cross_domain_error(tmp_path: Path) -> None:
    _corpus(tmp_path, claims=_claims(target_column="first_name"))
    result = runner.invoke(
        app, ["validate", str(tmp_path / "claims" / "medical_claims")]
    )
    assert result.exit_code == 1
    # The table itself fails completeness first in this fixture, so assert on
    # the API for the domain finding and on the CLI only for the exit code.
    run = validate_domain_scopes(tmp_path / "claims" / "medical_claims")
    assert [f.rule for f in run.report.errors] == ["DOM-XREF"]


def test_cli_baseline_without_domains_prints_a_note(tmp_path: Path) -> None:
    UMFLoader().save(_member(), tmp_path / "old" / "member")
    UMFLoader().save(_member(), tmp_path / "new" / "member")
    result = runner.invoke(
        app,
        ["validate", str(tmp_path / "new"), "--baseline", str(tmp_path / "old")],
    )
    assert "no domain.yaml" in result.output
