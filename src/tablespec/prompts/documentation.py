"""Documentation prompt generator - Generates table documentation prompts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tablespec.models.domain import Glossary


def _referenced_terms(
    umf_data: dict[str, Any], glossary: Glossary | Mapping[str, str]
) -> list[tuple[str, str]]:
    """Return ``(term, definition)`` for every term the table or its columns cite.

    Only referenced terms are included so the prompt size is bounded by the
    table, not the glossary. Terms are resolved through the glossary (aliases
    included when a ``Glossary`` model is given), de-duplicated by canonical
    spelling, and sorted for deterministic output. Unresolved terms are
    omitted; the validator (``DOM-TERM``) is where they are reported.
    """
    cited: list[str] = []
    if umf_data.get("term"):
        cited.append(str(umf_data["term"]))
    for col in umf_data.get("columns", []):
        if col.get("term"):
            cited.append(str(col["term"]))

    resolved: dict[str, str] = {}
    for term in cited:
        if isinstance(glossary, Mapping):
            match = next(
                (k for k in glossary if k.lower() == term.strip().lower()), None
            )
            if match is not None:
                resolved[match] = str(glossary[match])
            continue
        definition = glossary.definition_of(term)
        if definition is None:
            continue
        canonical = next(
            (k for k in glossary.terms if glossary.definition_of(k) == definition),
            term,
        )
        resolved[canonical] = definition
    return sorted(resolved.items(), key=lambda kv: kv[0].lower())


def generate_documentation_prompt(
    umf_data: dict[str, Any],
    *,
    glossary: Glossary | Mapping[str, str] | None = None,
) -> str:
    """Generate documentation prompt for a specific table.

    Args:
        umf_data: The UMF as a dict (``UMF.model_dump()``).
        glossary: Optional domain glossary (a :class:`~tablespec.models.domain.Glossary`
            or a plain ``{term: definition}`` mapping). When given, a
            "Domain Glossary" section lists the terms the table and its
            columns cite so generated prose uses the domain's own language.

    """
    table_name = umf_data["table_name"]

    prompt = f"""# Documentation Generation Prompt for {table_name}

Please analyze the following healthcare data table specification and generate comprehensive documentation.

## Table Information
- **Name**: {table_name}
- **Source**: {umf_data.get("source_file", "Centene healthcare data specifications")}
- **Description**: {umf_data.get("description", f"Data table containing {len(umf_data['columns'])} fields")}
"""
    if umf_data.get("term"):
        prompt += f"- **Term**: {umf_data['term']}\n"

    terms = _referenced_terms(umf_data, glossary) if glossary is not None else []
    if terms:
        prompt += "\n## Domain Glossary\n\nUse these terms exactly as defined:\n\n"
        for term, definition in terms:
            prompt += f"- **{term}**: {definition}\n"

    prompt += "\n## Column Specifications\n\n"

    for col in umf_data["columns"]:
        prompt += f"### {col['name']}\n"
        prompt += f"- **Type**: {col.get('data_type', 'VARCHAR')}\n"
        prompt += (
            f"- **Description**: {col.get('description', 'No description provided')}\n"
        )
        if col.get("term"):
            prompt += f"- **Term**: {col['term']}\n"

        if col.get("sample_values"):
            sample_str = ", ".join(str(v) for v in col["sample_values"][:3])
            prompt += f"- **Sample Values**: {sample_str}\n"

        nullable_str = "True" if col.get("nullable", True) else "False"
        prompt += f"- **Nullable**: {nullable_str}\n"

        if col.get("max_length"):
            prompt += f"- **Max Length**: {col['max_length']}\n"

        prompt += "\n"

    prompt += """

## Analysis Request

Based on this specification, please provide:

1. **Business Purpose**: What is the primary business purpose of this table?

2. **Data Flow**: How does this table fit into the healthcare data workflow?

3. **Key Relationships**: What other tables would this likely relate to?

4. **Data Quality Concerns**: What data quality issues should we watch for?

5. **Compliance Considerations**: What healthcare compliance aspects are relevant?

6. **Usage Patterns**: How would this table typically be queried or used?

Please provide your analysis in a structured format suitable for technical documentation.
"""

    return prompt


# Deprecated alias - use the public name above instead
_generate_documentation_prompt = generate_documentation_prompt
