# SPDX-License-Identifier: MIT OR Apache-2.0
"""Documentation prompt generator - Generates table documentation prompts."""

from typing import Any


def generate_documentation_prompt(umf_data: dict[str, Any]) -> str:
    """Generate documentation prompt for a specific table."""
    table_name = umf_data["table_name"]

    prompt = f"""# Documentation Generation Prompt for {table_name}

Please analyze the following healthcare data table specification and generate comprehensive documentation.

## Table Information
- **Name**: {table_name}
- **Source**: {umf_data.get("source_file", "Centene healthcare data specifications")}
- **Description**: {umf_data.get("description", f"Data table containing {len(umf_data['columns'])} fields")}

## Column Specifications

"""

    for col in umf_data["columns"]:
        prompt += f"### {col['name']}\n"
        prompt += f"- **Type**: {col.get('data_type', 'VARCHAR')}\n"
        prompt += (
            f"- **Description**: {col.get('description', 'No description provided')}\n"
        )

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
