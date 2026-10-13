"""Column-level validation prompt generator - Generates focused per-column validation prompts."""

import logging
from typing import Any

from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.prompts.expectation_guide import (
    format_quick_reference,
    get_pending_decision_tree,
)

logger = logging.getLogger(__name__)


def should_generate_column_prompt(col: dict[str, Any]) -> bool:
    """Check if column needs a dedicated validation prompt.

    Only generate prompts for columns with COMPLEX rules that require LLM reasoning:
    - Format constraints (complex patterns beyond simple length)
    - Enumerated values (value sets)
    - Complex descriptions with validation logic

    Do NOT generate for simple cases (basic nullability, type, length) as these are
    handled by baseline expectations.

    Args:
    ----
        col: Column dict from UMF data

    Returns:
    -------
        True if column should get dedicated validation prompt

    """
    # Skip filename-sourced columns - they're parsed from filenames, not validated from data
    if col.get("source") == "filename":
        return False

    # Generate if has format constraint (complex patterns)
    if col.get("format"):
        return True

    # Generate if has enumerated sample values (likely value set)
    sample_values = col.get("sample_values", [])
    if sample_values and len(sample_values) <= 10:
        return True

    # Generate if description contains complex validation indicators
    description = col.get("description", "").lower()
    complex_validation_indicators = [
        "format",
        "pattern",
        "must be",
        "should be",
        "valid values",
        "allowed values",
        "options:",
        "range",
        "between",
        "digit",  # Specific digit patterns
        "checksum",
        "algorithm",
        "conditional",
        "if",
        "when",
    ]
    return bool(
        any(indicator in description for indicator in complex_validation_indicators)
    )


def _get_relevant_columns_for_context(
    umf_data: dict[str, Any], target_col: dict[str, Any], max_columns: int = 5
) -> list[dict[str, Any]]:
    """Get columns most relevant to the target column for context.

    Prioritizes:
    1. Primary/foreign key columns
    2. Columns mentioned in target's description
    3. Columns with similar names (prefixes/suffixes)
    4. Date/time columns (often used in conditional logic)

    Args:
    ----
        umf_data: Full UMF table data
        target_col: The column being validated
        max_columns: Maximum number of context columns to return

    Returns:
    -------
        List of relevant column dictionaries

    """
    relevant = []
    seen_names: set[str] = set()
    target_name = target_col["name"].lower()
    target_desc = target_col.get("description", "").lower()

    # Priority 1: Primary keys
    if "primary_keys" in umf_data:
        for pk in umf_data["primary_keys"]:
            for col in umf_data.get("columns", []):
                if col["name"] == pk and col["name"] != target_col["name"]:
                    if col["name"] not in seen_names:
                        relevant.append(col)
                        seen_names.add(col["name"])

    # Priority 2: Foreign keys
    if "foreign_keys" in umf_data:
        for fk in umf_data["foreign_keys"]:
            fk_col = fk.get("column")
            if fk_col and fk_col != target_col["name"]:
                for col in umf_data.get("columns", []):
                    if col["name"] == fk_col and col["name"] not in seen_names:
                        relevant.append(col)
                        seen_names.add(col["name"])

    # Priority 3: Columns mentioned in description
    if target_desc:
        for col in umf_data.get("columns", []):
            col_name = col["name"]
            if col_name != target_col["name"] and col_name not in seen_names:
                # Check if column name appears in description
                if (
                    col_name.lower() in target_desc
                    or col_name.lower().replace("_", " ") in target_desc
                ):
                    relevant.append(col)
                    seen_names.add(col_name)

    # Priority 4: Related column names (same prefix/suffix)
    target_parts = target_name.split("_")
    if len(target_parts) > 1:
        prefix = target_parts[0]
        suffix = target_parts[-1]
        for col in umf_data.get("columns", []):
            col_name = col["name"]
            if col_name != target_col["name"] and col_name not in seen_names:
                col_lower = col_name.lower()
                if col_lower.startswith(prefix) or col_lower.endswith(suffix):
                    relevant.append(col)
                    seen_names.add(col_name)

    # Priority 5: Date/time columns (useful for temporal validation)
    for col in umf_data.get("columns", []):
        if col["name"] not in seen_names and len(relevant) < max_columns:
            data_type = col.get("data_type", "").upper()
            if data_type in ["DATE", "DATETIME", "TIMESTAMP"]:
                relevant.append(col)
                seen_names.add(col["name"])

    return relevant[:max_columns]


def generate_column_validation_prompt(
    umf_data: dict[str, Any], col: dict[str, Any]
) -> str:
    """Generate focused validation prompt for a single column.

    Args:
    ----
        umf_data: Full UMF table data for context
        col: Specific column to generate prompt for

    Returns:
    -------
        Validation prompt string

    """
    table_name = umf_data["table_name"]
    table_desc = umf_data.get("description", "No description available")
    col_name = col["name"]
    col_desc = col.get("description", "No description")
    data_type = col.get("data_type", "VARCHAR")
    max_length = col.get("max_length")
    nullable = col.get("nullable", {})
    format_spec = col.get("format", "")
    sample_values = col.get("sample_values", [])
    notes = col.get("notes", [])

    # Generate baseline expectations for this column (includes domain type expectations)
    generator = BaselineExpectationGenerator()
    baseline_expectations = generator.generate_baseline_column_expectations(col)

    # Check if domain type expectations were generated
    has_domain_type_expectations = any(
        exp.get("meta", {}).get("generated_from") == "domain_type"
        for exp in baseline_expectations
    )

    # Required contexts (e.g. LOBs like MD/ME/MP, or any configurable keys)
    req_contexts = [ctx for ctx, is_null in sorted(nullable.items()) if not is_null]

    # Build domain type hint section
    domain_type_section = ""
    domain_type = col.get("domain_type")
    if domain_type:
        try:
            from tablespec.inference.domain_types import DomainTypeRegistry

            registry = DomainTypeRegistry()
            domain_info = registry.get_domain_type(domain_type)
            validation_specs = registry.get_validation_specs(domain_type)

            if domain_info and validation_specs:
                # Use first validation spec if available
                first_spec = validation_specs[0] if validation_specs else {}
                if has_domain_type_expectations:
                    # Domain type validation is already handled
                    domain_type_section = f"""
## Domain Type Already Validated: {domain_type}

Column classified as `{domain_type}` - {domain_info.get("description", "N/A")}

**ALREADY HANDLED**: Standard {domain_type} validation (`{first_spec.get("type", "N/A")}`) auto-generated.

**DO NOT RECREATE** this validation. Focus on:
- Business-specific constraints beyond standard {domain_type} patterns
- Conditional logic or edge cases specific to this data context
- Cross-column dependencies using provenance fields
"""
                else:
                    # Domain type detected but not auto-applied (low confidence or missing spec)
                    domain_type_section = f"""
## Domain Type Hint: {domain_type}

Classified as: `{domain_type}` - {domain_info.get("description", "N/A")}

Consider using: `{first_spec.get("type", "N/A")}` (severity: {first_spec.get("severity", "warning")}).
Only diverge if business requirements differ from standard {domain_type} validation.
"""
        except Exception:
            logger.debug(
                "Failed to load domain type info for column %s.%s", table_name, col_name
            )

    prompt = f"""# Column Validation: {table_name}.{col_name}

## Table Context

**Table**: {table_name}
**Description**: {table_desc}
"""

    # Get relevant columns for context using smart selection
    relevant_columns = _get_relevant_columns_for_context(umf_data, col)
    total_columns = len(umf_data.get("columns", []))

    if relevant_columns:
        prompt += "\n**Relevant columns for context:**\n"
        for c in relevant_columns:
            c_name = c["name"]
            c_type = c.get("data_type", "VARCHAR")
            c_desc = c.get("description", "")
            if c_desc:
                # Truncate description if too long
                desc_preview = c_desc[:60] + "..." if len(c_desc) > 60 else c_desc
                prompt += f"- {c_name} ({c_type}): {desc_preview}\n"
            else:
                prompt += f"- {c_name} ({c_type})\n"

        if total_columns > len(relevant_columns) + 1:  # +1 for the target column
            prompt += f"- ... ({total_columns} total columns in table)\n"
    else:
        prompt += f"\n**Table has {total_columns} columns total**\n"

    prompt += """
## Runtime Provenance Fields

Provenance fields available for validation: **meta_source_name** (filename), **meta_source_checksum** (SHA256), **meta_load_dt** (ingestion time), **meta_snapshot_dt** (file modification), **meta_source_offset** (row number).

Use these for: column-to-filename metadata matching, cross-column validation with provenance, complex parsing (use pending implementation).

"""

    prompt += f"""
## Column Details

**{col_name}** ({data_type}): {col_desc}
"""

    if req_contexts:
        prompt += f"- **Required for contexts**: {', '.join(req_contexts)}\n"
    if format_spec:
        prompt += f"- **Format**: {format_spec}\n"
    if max_length:
        prompt += f"- **Max Length**: {max_length}\n"
    if sample_values:
        # Filter out header pollution
        valid_samples = []
        for sample in sample_values[:5]:
            sample_str = str(sample).strip()
            if not sample_str:
                continue
            is_header = (
                sample_str.lower() == col_name.lower()
                or sample_str.upper() == col_name.upper()
                or sample_str.replace(" ", "_").lower() == col_name.lower()
            )
            if not is_header:
                valid_samples.append(sample)
        if valid_samples:
            prompt += (
                f"- **Sample Values**: {', '.join(str(s) for s in valid_samples[:3])}\n"
            )
    if notes:
        prompt += f"- **Notes**: {notes[0]}\n"

    # Categorize baseline expectations for clearer reporting
    baseline_types = []
    domain_types = []
    for exp in baseline_expectations:
        if exp.get("meta", {}).get("generated_from") == "domain_type":
            domain_types.append(exp["type"].replace("expect_", "").replace("_", " "))
        else:
            baseline_types.append(exp["type"].replace("expect_", "").replace("_", " "))

    prompt += f"""
## Expectations Already Auto-Generated

**{len(baseline_expectations)} expectations handled programmatically:**
"""
    if baseline_types:
        prompt += f"- Baseline validations: {', '.join(f'`{t}`' for t in baseline_types[:3])}{'...' if len(baseline_types) > 3 else ''}\n"
    if domain_types:
        prompt += (
            f"- Domain type validations: {', '.join(f'`{t}`' for t in domain_types)}\n"
        )

    prompt += """
**DO NOT recreate these validations.** Focus on business-specific rules not covered above.
"""

    # Add domain type hint if available
    prompt += domain_type_section

    # Determine task focus based on whether domain type is handled
    if has_domain_type_expectations:
        task_focus = f"""
## Your Task

Since {col_name} has domain type `{domain_type}` with standard validation already applied, focus on:

1. **Business-specific value constraints** not covered by {domain_type} standards
2. **Conditional validation** based on other column values or provenance fields
3. **Data quality rules** specific to this dataset's context
4. **Edge cases or exceptions** to the standard {domain_type} pattern

Only generate expectations if you identify constraints BEYOND the standard {domain_type} validation.
Return empty expectations array if standard validation is sufficient.
"""
    else:
        task_focus = f"""
## Your Task

Generate ONLY single-column expectations for `{col_name}`:

1. **Value sets**: `expect_column_values_to_be_in_set` (status/code/flag fields with <=10 distinct values)
2. **Format patterns**: `expect_column_values_to_match_regex` (IDs, codes, phone numbers)
3. **Numeric ranges**: `expect_column_values_to_be_between` (age, percentages, counts) - NUMERIC ONLY
4. **Complex rules**: `expect_validation_rule_pending_implementation` (checksums, lookups, algorithms)

**Skip:** Column existence, type, nullability, length, date format (baseline handles), multi-column rules (table-level).
"""

    prompt += task_focus + "\n"

    # Add quick reference and pending tree
    quick_reference = format_quick_reference(context="column")
    pending_tree = get_pending_decision_tree()

    # Different output guidance based on domain type status
    if has_domain_type_expectations:
        output_guidance = f"""
## Output Format

Return JSON with business-specific validations ONLY (beyond {domain_type} standards):

```json
{{
  "domain_type_confirmed": "{domain_type}",
  "expectations": []
}}
```

**When to add expectations:**
- Business rules specific to this dataset (not general {domain_type} patterns)
- Conditional logic based on other fields or LOB requirements
- Edge cases or exceptions to standard {domain_type} validation
"""
    else:
        output_guidance = f"""
## Output Format

**REQUIRED structure:**
```json
{{
  "domain_type": "suggested_type",
  "expectations": [
    {{"type": "...", "kwargs": {{}}, "meta": {{}}}}
  ]
}}
```

**Expectation requirements:**
- `type`: Must be from the approved list above
- `kwargs.column`: Always "{col_name}"
- `meta.description`: Clear business justification
- `meta.severity`: "critical", "warning", or "info"
"""

    prompt += f"""
{quick_reference}

{pending_tree}

{output_guidance}

## Critical Rules

- Output ONLY valid JSON (no markdown, no comments, no explanations)
- Do NOT recreate validations already in baseline or domain type
- For STRING columns: NO `expect_column_values_to_be_between` (use regex instead)
- For pending rules: Include detailed `reason_unmappable` and `suggested_implementation`

## Decision Flow

1. Check if domain type validation covers the requirements -> Return empty expectations
2. Identify business-specific constraints -> Add targeted expectations
3. Complex/algorithmic rules -> Use pending implementation with clear rationale
"""

    return prompt


# Deprecated aliases - use the public names above instead
_should_generate_column_prompt = should_generate_column_prompt
_generate_column_validation_prompt = generate_column_validation_prompt
