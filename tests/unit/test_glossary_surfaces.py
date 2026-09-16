"""Glossary terms surface in the guidebook and the documentation prompt."""

# @covers US-052-AC5

from __future__ import annotations

from pathlib import Path

from tablespec.guidebook import generate
from tablespec.guidebook.renderer import render_table_page
from tablespec.guidebook.reverse_lineage import ReverseLineageIndex
from tablespec.models.domain import Glossary
from tablespec.prompts.documentation import generate_documentation_prompt
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder

GLOSSARY = Glossary(
    terms={
        "member": {
            "definition": "A person enrolled for a coverage period",
            "aliases": ["mbr"],
        },
        "claim": {"definition": "A billed encounter"},
    }
)


def _claims_umf():
    umf = (
        UMFBuilder("medical_claims")
        .column("claim_id", "VARCHAR", key_type="primary")
        .column("mbr_id", "VARCHAR")
        .primary_key("claim_id")
        .build()
    )
    umf.term = "claim"
    umf.columns[1].term = "mbr"  # alias of member
    return umf


# ---------------------------------------------------------------- guidebook


def test_renderer_shows_term_and_definition_with_glossary() -> None:
    html = render_table_page(
        _claims_umf(), ReverseLineageIndex(), group="claims", glossary=GLOSSARY
    )
    assert "term: mbr" in html
    assert 'title="A person enrolled for a coverage period"' in html
    assert "A person enrolled for a coverage period" in html  # inline definition
    assert "term: claim" in html
    assert 'title="A billed encounter"' in html


def test_renderer_without_glossary_shows_bare_term() -> None:
    html = render_table_page(_claims_umf(), ReverseLineageIndex(), group="claims")
    assert "term: mbr" in html
    assert '<p class="term-definition">' not in html
    assert "title=" not in html.split("term: mbr")[0][-80:]


def test_generate_passes_domain_glossary_to_table_pages(tmp_path: Path) -> None:
    clm = tmp_path / "claims"
    clm.mkdir()
    (clm / "domain.yaml").write_text(
        "name: claims\nversion: 1.0.0\nexports: [medical_claims]\nglossary: glossary.yaml\n"
    )
    (clm / "glossary.yaml").write_text(
        "member:\n  definition: A person enrolled for a coverage period\n"
        "  aliases: [mbr]\nclaim:\n  definition: A billed encounter\n"
    )
    UMFLoader().save(_claims_umf(), clm / "medical_claims")
    out = tmp_path / "out"
    generate(tmp_path, out)
    page = (out / "claims" / "medical_claims.html").read_text(encoding="utf-8")
    assert "A person enrolled for a coverage period" in page


# ---------------------------------------------------------------- prompt


def test_prompt_lists_only_referenced_terms_sorted() -> None:
    umf_data = _claims_umf().model_dump(exclude_none=True)
    prompt = generate_documentation_prompt(umf_data, glossary=GLOSSARY)
    assert "## Domain Glossary" in prompt
    claim_at = prompt.index("**claim**: A billed encounter")
    member_at = prompt.index("**member**: A person enrolled for a coverage period")
    assert claim_at < member_at  # sorted by canonical term
    assert "- **Term**: mbr" in prompt
    assert prompt.count("**member**") == 1  # alias resolved to the canonical key


def test_prompt_accepts_plain_mapping_and_omits_section_when_nothing_cited() -> None:
    umf_data = _claims_umf().model_dump(exclude_none=True)
    prompt = generate_documentation_prompt(
        umf_data, glossary={"claim": "A billed encounter"}
    )
    assert "**claim**: A billed encounter" in prompt
    assert "**member**" not in prompt  # alias not resolvable through a plain mapping

    uncited = UMFBuilder("t").column("id", "INTEGER").build().model_dump()
    assert "Domain Glossary" not in generate_documentation_prompt(
        uncited, glossary=GLOSSARY
    )


def test_prompt_unchanged_without_glossary() -> None:
    umf_data = _claims_umf().model_dump(exclude_none=True)
    prompt = generate_documentation_prompt(umf_data)
    assert "Domain Glossary" not in prompt
    assert "## Analysis Request" in prompt
