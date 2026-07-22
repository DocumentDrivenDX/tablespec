"""Per-column validation rule prompt generator.

This module provides a unified interface for generating validation rule prompts
using the same per-column approach as survivorship mapping.

Unlike the original generate_validation_prompt (table-level), this generates
focused prompts for individual columns or table-level validation groups.
"""

from typing import Any

from tablespec.prompts.expectation_guide import get_llm_generatable_expectations


def generate_validation_prompt_per_column(
    table_name: str,
    table_description: str,
    column_name: str | None = None,
    column_data: dict[str, Any] | None = None,
    context: str = "column",
    umf_data: dict[str, Any] | None = None,
) -> str:
    """Generate a focused validation rule prompt.

    Generates validation prompts for either:
    - Single column (context="column") - column-specific constraints
    - Table-level rules (context="table", column_name=None) - cross-column constraints

    Args:
        table_name: Name of the target table
        table_description: Description of the table
        column_name: Name of column (required if context="column")
        column_data: UMF column metadata (required if context="column")
        context: Either "column" or "table"
        umf_data: Full UMF data (required if context="table" to include column schema)

    Returns:
        Focused validation rule prompt string

    """
    if context == "column":
        return _generate_column_validation_prompt_focused(
            table_name, table_description, column_name, column_data
        )
    if context == "table":
        return _generate_table_validation_prompt_focused(
            table_name, table_description, umf_data
        )
    msg = f"Unknown context: {context}. Must be 'column' or 'table'"
    raise ValueError(msg)


def _generate_column_validation_prompt_focused(
    table_name: str,
    table_description: str,
    column_name: str | None,
    column_data: dict[str, Any] | None,
) -> str:
    """Generate validation prompt for a single column.

    Args:
        table_name: Table name
        table_description: Table description
        column_name: Column name
        column_data: Column UMF metadata

    Returns:
        Validation prompt for the column

    """
    if not column_name or not column_data:
        msg = "column_name and column_data are required for column context"
        raise ValueError(msg)

    col_desc = column_data.get("description", "No description")
    data_type = column_data.get("data_type", "VARCHAR")
    max_length = column_data.get("max_length")
    nullable = column_data.get("nullable", {})
    format_spec = column_data.get("format", "")
    domain_type = column_data.get("domain_type")

    # Required contexts (e.g. LOBs like MD/ME/MP, or any configurable keys)
    req_contexts = [ctx for ctx, is_null in sorted(nullable.items()) if not is_null]

    # Build auto-generated validations list
    auto_validations = [
        "- Column existence check",
        f"- Data type validation ({data_type})",
        f"- Nullability constraints (required for: {', '.join(req_contexts) if req_contexts else 'none'})",
    ]
    if max_length:
        auto_validations.append(f"- Max length constraint ({max_length} characters)")
    if format_spec:
        auto_validations.append(f"- Format validation ({format_spec})")
    if domain_type:
        auto_validations.append(
            f"- Domain type constraints ({domain_type} format/value set)"
        )

    # Get column-level expectation types
    expectation_types = get_llm_generatable_expectations(context="column")

    return f"""# Validation Rules: {table_name}.{column_name}

Generate validation constraints for a single column.

## Column Details

- **Table**: {table_name}
- **Column**: {column_name}
- **Type**: {data_type}
- **Max Length**: {max_length or "N/A"}
- **Required Contexts**: {", ".join(req_contexts) if req_contexts else "None"}
- **Description**: {col_desc}
{f"- **Format**: {format_spec}" if format_spec else ""}

## Table Context

{table_description}

## Auto-Generated Validations (Don't Duplicate)

The following are already auto-generated from schema metadata:
{chr(10).join(auto_validations)}

**Focus ONLY on business logic validations beyond these basics.**

## Business Logic Validation Rules

Generate business-specific validation rules for this column.

**Available Constraint Types**:
{chr(10).join(f"- {exp_type}" for exp_type in expectation_types[:10])}

## Output Format

Return a JSON object with expectations array, reasoning, and domain type feedback:

```json
{{
  "expectations": [
    {{
      "expectation_type": "expect_column_values_to_be_in_set",
      "kwargs": {{}},
      "meta": {{
        "severity": "error",
        "description": "Brief description of what this validates"
      }}
    }}
  ],
  "reasoning": "Explain why these expectations were chosen or why the array is empty. If no business-specific constraints are needed beyond auto-generated baseline validations, explain that explicitly.",
  "domain_type_feedback": "Assess whether the domain_type is accurate or suggest improvements (optional, omit if no domain type concerns)"
}}
```

## Strict Requirements

1. **ONLY use ExpectationTypes from "Available Constraint Types" above**
2. **Return valid JSON object** with "expectations", "reasoning", and optional "domain_type_feedback"
3. **Each expectation must have**: expectation_type (snake_case), kwargs, meta
4. **Meta must include**: severity (error/warning/info) and description
5. **No partial constraints** - all kwargs must be populated
6. **Always include reasoning** - explain your decision-making, especially for empty expectations arrays
"""


def _generate_table_validation_prompt_focused(
    table_name: str,
    table_description: str,
    umf_data: dict[str, Any] | None = None,
) -> str:
    """Generate table-level validation prompt for cross-column constraints.

    Args:
        table_name: Table name
        table_description: Table description
        umf_data: Full UMF data including columns

    Returns:
        Validation prompt for table-level constraints

    """
    # Get table-level expectation types
    expectation_types = get_llm_generatable_expectations(context="table")

    # Extract column names from UMF data
    columns_section = ""
    if umf_data and "columns" in umf_data:
        column_names = [
            col.get("name", "") for col in umf_data["columns"] if col.get("name")
        ]
        if column_names:
            columns_section = f"""
## Available Columns

The following columns are defined in this table's schema. **Use ONLY these column names** in your validation rules:

{chr(10).join(f"- {col_name}" for col_name in sorted(column_names))}

**CRITICAL**: Do NOT invent or guess column names. Reference ONLY the columns listed above.
"""

    return f"""# Validation Rules: {table_name} (Table-Level)

Generate table-level validation constraints for cross-column relationships.

## Table Details

- **Table**: {table_name}
- **Description**: {table_description}
{columns_section}
## Table-Level Constraints

Generate validation rules that span multiple columns or validate table-level properties.

**Available Constraint Types**:
{chr(10).join(f"- {exp_type}" for exp_type in expectation_types[:15])}

## Examples of Table-Level Constraints

- Row count expectations (ExpectTableRowCountToBeBetween)
- Column set expectations (ExpectTableColumnsToMatchOrderedList)
- Uniqueness constraints (ExpectColumnPairValuesToBeUnique)
- Referential integrity (ExpectColumnsToExist)

## Output Format

Return a JSON object with expectations array and reasoning:

```json
{{
  "expectations": [
    {{
      "expectation_type": "expect_table_row_count_to_be_between",
      "kwargs": {{}},
      "meta": {{
        "severity": "error",
        "description": "Table should have between X and Y rows"
      }}
    }}
  ],
  "reasoning": "Explain why these table-level expectations were chosen or why the array is empty. If no table-wide constraints are needed, explain that explicitly."
}}
```

## Strict Requirements

1. **ONLY use ExpectationTypes from "Available Constraint Types" above**
2. **Return valid JSON object** with "expectations" and "reasoning"
3. **Each expectation must have**: expectation_type (snake_case), kwargs, meta
4. **Meta must include**: severity (error/warning/info) and description
5. **No partial constraints** - all kwargs must be populated
6. **Focus on cross-column and table-wide constraints** - column-level rules go elsewhere
7. **Always include reasoning** - explain your decision-making, especially for empty expectations arrays
"""
