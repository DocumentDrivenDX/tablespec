"""Survivorship prompt generator - Generates data survivorship mapping prompts."""

import re
from pathlib import Path
from typing import Any

from .utils import load_umf


def _get_compatible_types(target_type: str) -> set[str]:
    """Get data types compatible with target type for survivorship mapping.

    Args:
        target_type: Target column data type (e.g., "StringType", "IntegerType")

    Returns:
        Set of compatible type names

    """
    # Map type to compatible types
    compatibility = {
        "StringType": {"StringType", "CharType", "TextType"},
        "CharType": {"StringType", "CharType", "TextType"},
        "TextType": {"StringType", "CharType", "TextType"},
        "IntegerType": {"IntegerType", "DecimalType"},
        "DecimalType": {"IntegerType", "DecimalType", "FloatType"},
        "FloatType": {"DecimalType", "FloatType"},
        "DateType": {"DateType", "DatetimeType"},
        "DatetimeType": {"DateType", "DatetimeType"},
        "BooleanType": {"BooleanType"},
    }

    return compatibility.get(target_type, {target_type})


def generate_survivorship_prompt(target_table_name: str, umf_dir: Path) -> str:
    """Generate survivorship prompt with actual table and column information."""
    # Load the target table UMF
    target_umf_file = umf_dir / f"{target_table_name}.specs.umf.yaml"
    if not target_umf_file.exists():
        msg = f"UMF file not found: {target_umf_file}"
        raise FileNotFoundError(msg)

    target_umf = load_umf(target_umf_file)

    # Find all provided tables (potential sources)
    source_tables = []
    for umf_file in umf_dir.glob("*.specs.umf.yaml"):
        umf = load_umf(umf_file)
        table_type = umf.get("table_type")
        if not table_type:
            # Fallback to checking source file for backward compatibility
            source_file = umf.get("source_file", "")
            if (
                "outbound" in source_file.lower()
                or "inbound" not in source_file.lower()
            ):
                table_type = "provided"

        if table_type == "provided":
            source_tables.append(umf)

    # Collect data for template
    table_names = sorted([umf.get("table_name", "") for umf in source_tables])

    # Build table-column mapping
    table_columns = {}
    for source_umf in sorted(source_tables, key=lambda x: x.get("table_name", "")):
        table_name = source_umf.get("table_name", "")
        columns = [col.get("name", "") for col in source_umf.get("columns", [])]
        table_columns[table_name] = columns

    # Build target column descriptions
    target_columns = []
    for col in target_umf.get("columns", []):
        col_name = col.get("name", "")
        col_type = col.get("data_type", "VARCHAR")
        col_desc = col.get("description", "")[:80]
        target_columns.append(f"- **{col_name}** ({col_type}): {col_desc}")

    # Build table name list
    table_name_list = "\n".join(f"- {name}" for name in table_names)

    # Build column enum sections
    column_sections = []
    for table_name, columns in table_columns.items():
        column_list = "\n".join(f"- {col}" for col in columns)
        column_sections.append(f"\n**{table_name}:**\n{column_list}")

    # Generate structured prompt using template literal
    return f"""# Survivorship Mapping: {target_table_name}

Generate JSON mappings to derive columns from source tables using ONLY the exact column names provided below.

## REQUIRED: Use Only These Exact Names

### Valid Table Names (enum):
{table_name_list}

### Valid Column Names (per table):

{chr(10).join(column_sections)}

## Target Table: {target_table_name}
### Columns needing mappings:
{chr(10).join(target_columns)}

## REQUIRED OUTPUT FORMAT

Your output MUST be valid JSON with this structure:

```json
{{
  "metadata": {{
"table_name": "{target_table_name}",
"version": "4.0",
"description": "Brief description of target table purpose",
"primary_key": "PRIMARY_KEY_COLUMN",
"generated_by": "tablespec-pipeline-ai"
  }},
  "mappings": {{
"TARGET_COLUMN_NAME": {{
  "candidates": [
    {{
      "table": "ExactTableNameFromEnum",
      "column": "ExactColumnNameFromEnum",
      "priority": 1
    }}
  ],
  "survivorship": {{
    "strategy": "highest_priority",
    "description": "Brief explanation of why this strategy"
  }}
}}
  }},
  "survivorship_strategies": {{
"highest_priority": {{
  "description": "Select value from highest priority source",
  "rules": [
    "Check candidates in priority order",
    "Return first non-null value",
    "Use default if all null"
  ]
}},
"most_recent_date": {{
  "description": "Select most recent date value",
  "rules": [
    "Convert all candidates to date",
    "Return maximum date value",
    "If all null, return null"
  ]
}}
  }},
  "normalization": {{
"phone_numbers": {{
  "description": "Standardize phone numbers to 10-digit format",
  "rules": [
    "Remove all non-digit characters",
    "Remove leading '1' if present",
    "Validate exactly 10 digits remain"
  ],
  "example": "(555) 123-4567 -> 5551234567"
}}
  }}
}}
```

## STRICT OUTPUT REQUIREMENTS:
1. **ONLY use table names from the 'Valid Table Names' enum above**
2. **ONLY use column names from the 'Valid Column Names' for each table**
3. **DO NOT invent, modify, or guess any names not listed**
4. **If a logical mapping seems to exist but exact name doesn't match, skip it**
5. **Include all sections: metadata, mappings, survivorship_strategies, normalization**
6. **Validate every table/column reference against the enums above**
7. **Return ONLY the JSON object - no markdown code blocks, no explanations**

## JSON FORMATTING NOTES:
- Arrows (->, =>) are fine in JSON strings - they're just text
- Colons, commas, quotes are handled naturally in JSON
- Use arrow characters freely in examples if they help clarity
- JSON is more forgiving than YAML for special characters

## FINAL REQUIREMENT
Return ONLY a valid JSON object. Your output will be parsed with `json.load()`.
- NO markdown code blocks (no ```json)
- NO explanations or commentary
- ONLY the raw JSON object
"""


def generate_survivorship_prompt_per_column(
    target_table_name: str,
    target_table_description: str,
    target_col_name: str,
    target_col_description: str,
    target_col_type: str,
    source_candidates: list[tuple[float, str, list[str]]],
    source_umfs: list[dict[str, Any]],
    column_metadata: dict[str, Any] | None = None,
    excluded_tables: list[str] | None = None,
    config: dict[str, Any] | None = None,
    relationships: dict[str, Any] | None = None,
    relationship_graph: dict[str, Any] | None = None,
    joinable_tables: dict[str, int] | None = None,
) -> str:
    """Generate survivorship prompt for a single target column.

    This is a lightweight prompt focusing on one column with pre-filtered candidates,
    reducing token usage and context complexity.

    Args:
        target_table_name: Name of target table
        target_table_description: Description of target table
        target_col_name: Name of target column
        target_col_description: Description of target column
        target_col_type: Data type of target column
        source_candidates: List of (score, source_col, [table_names]) tuples
        source_umfs: List of source table UMF metadata
        column_metadata: Full column metadata dict from UMF (includes provenance_policy, pivot fields, etc.)
        excluded_tables: List of table names to exclude from survivorship
        config: Survivorship config dict (excluded_tables, provenance_defaults, pivot_patterns)
        relationships: Full relationships data from relationships.json
        relationship_graph: Built relationship graph for quick lookups
        joinable_tables: Dict of {table_name: hop_distance} from primary source

    Returns:
        Prompt string for single-column survivorship mapping

    """
    # Initialize defaults
    column_metadata = column_metadata or {}
    excluded_tables = excluded_tables or []
    config = config or {}
    relationships = relationships or {}
    relationship_graph = relationship_graph or {}
    joinable_tables = joinable_tables or {}
    # Extract provenance policy and pivot metadata from column
    provenance_policy = column_metadata.get("provenance_policy")
    provenance_notes = column_metadata.get("provenance_notes")
    pivot_field = column_metadata.get("pivot_field", False)
    pivot_source_table = column_metadata.get("pivot_source_table")
    pivot_source_column = column_metadata.get("pivot_source_column")
    pivot_index = column_metadata.get("pivot_index")
    pivot_max_count = column_metadata.get("pivot_max_count")
    reporting_requirement = column_metadata.get("reporting_requirement")
    nullable = column_metadata.get("nullable", {})

    # Build index of source table and column descriptions
    source_table_desc = {}
    source_col_desc = {}

    for umf in source_umfs:
        table_name = umf.get("table_name", "")
        if table_name:
            source_table_desc[table_name] = umf.get("description", "")
            for col in umf.get("columns", []):
                col_name = col.get("name", "")
                if col_name:
                    key = f"{table_name}.{col_name}"
                    source_col_desc[key] = col.get("description", "")

    # Build candidate scoring map for annotation in schema reference
    # Map of (table_name, col_name) -> (score, hop_distance)
    candidate_scores = {}

    for score, source_col, table_names in source_candidates:
        # Store score and hop distance for each table.column combination
        for table in table_names:
            hop_distance = joinable_tables.get(table, None)  # None if not joinable
            candidate_scores[(table, source_col)] = (score, hop_distance)

    # Build sections for the prompt
    # Section 1: Provenance Policy
    provenance_section = ""
    if provenance_policy:
        policy_descriptions = {
            "enterprise_only": """**CRITICAL CONSTRAINT**: This field captures direct care delivery or client interaction.

- **Source**: Enterprise systems ONLY (disposition_tracking, scheduling, appointment_tracking, contact_information)
- **Current Status**: Enterprise systems not yet integrated
- **Action**: Return EMPTY candidates list (zero candidates)
- **Explanation Required**: State that field requires enterprise systems and no suitable sources exist in provided files
- **Examples**: disposition_status, hra_completed, member_completion_phone, appointment_date, chart_id
- **Do NOT**: Use prior_yr_xxx fields as substitutes - they are historical context, not current activity
- **Do NOT**: Use provided file columns that are semantically unrelated, even if names seem similar""",
            "outreach_only": """**CRITICAL CONSTRAINT**: This field comes from payer-provided outreach files.

- **Source**: Provided files ONLY (outreach_list, outreach_list_gaps, supplemental_contact, etc.)
- **Current Status**: All provided files are available
- **Action**: Select from provided tables. Must have >=1 candidate.
- **Examples**: birth_date, member_first_name, client_member_id, gap conditions, member demographics
- **Priority**: Use outreach_list as primary, related tables (gaps/diags/pcp/guardian) as supplemental
- **Do NOT**: Use enterprise tables or excluded transactional tables (claims, labs)""",
            "enterprise_preferred": """**Prefer enterprise when available, fallback to provided files.**

- **Source**: Enterprise systems first, provided files as fallback
- **Use Case**: Fields where enterprise may have more current/verified data
- **Examples**: member_phone (enterprise-verified override), member_email (updated contact info)
- **Action**: Check enterprise tables first; if unavailable or null, use provided file sources""",
            "survivorship": """**Standard multi-source logic applies. Consider all available sources.**

- **Source**: Any non-excluded table with semantic match
- **Action**: Prioritize based on data quality, currency, and source authority
- **Use Case**: Fields that may come from multiple systems with equal validity""",
        }
        policy_desc = policy_descriptions.get(provenance_policy, "Unknown policy")

        provenance_section = f"""

## Provenance Policy

**Policy**: `{provenance_policy}`

{policy_desc}

"""
        if provenance_notes:
            provenance_section += f"""**Additional Context**: {provenance_notes}

"""

    # Section 1.5: Provenance Policy Inference Guidance (when no explicit policy)
    inference_section = ""
    if not provenance_policy:
        inference_section = """

## Inferring Provenance Policy

**No explicit provenance policy is set for this field.** Use the following rules to determine the appropriate data sourcing strategy:

### Treat as `enterprise_preferred` when:

- Field represents **contact information or demographics** (email, phone, address, name components)
- **AND** type-compatible outreach sources exist in the schema reference (e.g., supplemental_email, supplemental_phone, outreach_list)
- Field description may mention enterprise capture timing (e.g., "obtained when...", "during assessment", "at completion"), BUT the field is fundamentally a demographic attribute, not an operational event
- **Examples**: member_email, member_phone, member_address, member_city, member_zip

**Critical distinction**: A field described as "email obtained when assessment is completed" is STILL just an email address (demographic data). The phrase "obtained when" describes WHEN it may be captured/updated by enterprise, not that it's ONLY valid at that moment. The email itself exists in both enterprise systems AND payer demographics.

**MANDATORY LOGIC for contact info/demographics**:
1. IF field is contact info (email, phone, address) AND type-compatible outreach sources exist (supplemental_email, supplemental_phone, outreach_list)
2. THEN you MUST include those sources as candidates
3. The description may mention "obtained when X" or "during Y" - IGNORE that language for contact fields
4. Enterprise timing language describes when the value MAY BE UPDATED, not when it's exclusively valid

**Expected behavior**: Include candidates from outreach files (supplemental_*, outreach_list) with appropriate priority. The field can source from payer demographics NOW, and enterprise sources will be added as higher-priority candidates when available.

**STRICT REQUIREMENT**: Do NOT reject supplemental_email/supplemental_phone/supplemental_contact/outreach_list sources for email/phone/address fields. These are ALWAYS valid candidates for contact info, regardless of description wording about enterprise capture timing.

### Treat as `enterprise_only` when:

- Field is PURELY operational/transactional data with NO demographic analog in outreach files
- Field captures enterprise-specific workflow state, dates, or identifiers
- **Examples**: disposition_status, chart_id, appointment_date, hra_completed_date, scheduled_date, cm_referral_date
- These fields have NO semantically valid outreach equivalents (do NOT use prior_yr_xxx as substitutes)

**Special case - Contact Context Fields:**
- Field names like `*_contact_phone`, `successful_*_phone`, `attempted_*_email`, `*_call_phone`
- **These capture which phone/email was USED during enterprise activity**, not member demographics
- Description patterns indicating enterprise activity context:
  - "Required if vendor..." / "Populate when vendor..."
  - "phone/email used to contact" / "phone/email used for successful contact"
  - "if successfully contact" / "when contact is made"
  - Found in disposition/results reports (outbound from enterprise)
- **Key distinction**:
  - `member_phone` = demographic (what IS the member's phone)
  - `successful_contact_phone` = operational (which phone was USED to reach them)
- **Examples**: successful_contact_phone, attempted_contact_email, outreach_phone_used
- These fields have NO valid demographic equivalents (member_phone != successful_contact_phone)

**Expected behavior**: Return empty candidates list with explanation that enterprise systems are not yet integrated.

### Treat as `outreach_only` when:

- Field is master demographics maintained by payer
- Field is a join key or identifier from provided files
- **Examples**: client_member_id, birth_date, member_first_name, member_last_name, govt_id
- These fields should NEVER come from enterprise systems

**Expected behavior**: Select from provided tables only (outreach_list, supplemental_*, etc.).

### Key Principle

**When in doubt between `enterprise_only` and `enterprise_preferred`**:
1. **First check**: Does the description indicate this captures enterprise ACTIVITY context ("if vendor...", "when contacted", "phone used to...")? -> `enterprise_only`
2. **Name patterns**: Does the name indicate activity context (*_contact_*, successful_*, attempted_*)? -> `enterprise_only`
3. **Only if neither**: If it's demographic contact info (email, phone, address) and outreach sources exist -> `enterprise_preferred`
4. **Only use `enterprise_only`** for purely operational fields OR contact fields that capture activity context

"""

    # Section 2: Excluded Tables
    excluded_section = ""
    if excluded_tables:
        excluded_list = "\n".join([f"- {table}" for table in excluded_tables])
        excluded_section = f"""

## Excluded Tables

The following tables are excluded from survivorship mapping and should NOT be used:

{excluded_list}

These tables are either transactional data (claims, labs) or status indicators (optout, disenrollment)
that do not contain authoritative member demographics.

"""

    # Section 2.5: Data Sources & System Architecture
    data_flow_section = ""
    if config:
        provenance_defaults = config.get("provenance_defaults", {})
        provided_tables = provenance_defaults.get(
            "provided_tables", provenance_defaults.get("outreach_only_tables", [])
        )  # Backward compat
        enterprise_tables = provenance_defaults.get("enterprise_only_tables", [])

        if provided_tables or enterprise_tables:
            data_flow_section = """

## Data Sources & System Architecture

"""
            if provided_tables:
                provided_list = ", ".join(provided_tables)
                data_flow_section += f"""**Provided Files** (from payer - outreach packet):
- Tables: {provided_list}
- These files contain member demographics, care gaps, and outreach campaign data provided by the payer

"""

            if enterprise_tables:
                enterprise_list = ", ".join(enterprise_tables)
                data_flow_section += f"""**Enterprise Systems** (care delivery systems):
- Tables: {enterprise_list}
- These systems capture direct client interaction, care delivery, scheduling, and follow-up activities

"""
            else:
                data_flow_section += """**Enterprise Systems** (currently unavailable):
- Examples: disposition_tracking, scheduling_system, appointment_tracking, claims_system
- These systems capture direct client interaction, care delivery, scheduling, and follow-up activities
- **Status**: Not yet integrated - enterprise-only fields will have zero valid candidates

"""

            data_flow_section += """**Data Flow Between Systems**:
1. **Outreach Cycle Start**: Payer provides outreach files -> Enterprise uses for care management
2. **Care Delivery**: Enterprise captures interactions (IHAs, appointments, disposition status)
3. **Results Return**: Enterprise sends results back to payer via disposition file
4. **Next Cycle**: Payer includes enterprise results in next outreach as `prior_yr_xxx` fields

**Examples of Round-Trip Fields**:
- `prior_yr_disp_status`: Enterprise disposition -> Payer -> Returns as prior year context
- `prior_yr_iha_cmplt_dt`: Enterprise IHA completion -> Payer -> Returns as prior year context
- These historical fields show what happened in PREVIOUS cycles, not current care delivery

**Critical Distinction**:
- **Current activity fields** (disposition_status, hra_completed, appointment_date) -> Enterprise systems
- **Prior year fields** (prior_yr_xxx) -> Provided files (historical context from previous cycle)
- **Member demographics** (name, DOB, address) -> Provided files (payer-maintained master data)

"""

    # Section 3: Table Relationships
    relationships_section = ""
    if relationship_graph and joinable_tables:
        # Find primary source (usually outreach_list)
        primary_source = (
            "outreach_list"
            if "outreach_list" in relationship_graph
            else target_table_name
        )

        relationships_section = f"""

## Table Relationships

**Primary Source**: {primary_source}

"""
        # Show direct relationships
        if primary_source in relationship_graph:
            outgoing = relationship_graph[primary_source].get("outgoing", [])
            incoming = relationship_graph[primary_source].get("incoming", [])

            if outgoing:
                relationships_section += """
**Directly Joinable Tables** (via foreign keys):

"""
                for rel in outgoing:
                    target = rel.get("target_table", "")
                    source_col = rel.get("source_column", "")
                    target_col = rel.get("target_column", "")
                    cardinality = rel.get("cardinality", {})
                    card_type = cardinality.get("type", "")
                    relationships_section += f"- {primary_source}.{source_col} -> {target}.{target_col} ({card_type})\n"

            if incoming:
                relationships_section += """
**Tables that Reference Primary Source**:

"""
                for rel in incoming:
                    source = rel.get("source_table", "")
                    source_col = rel.get("source_column", "")
                    target_col = rel.get("target_column", "")
                    cardinality = rel.get("cardinality", {})
                    card_type = cardinality.get("type", "")
                    relationships_section += f"- {source}.{source_col} -> {primary_source}.{target_col} ({card_type})\n"

    # Section 4: Source Priority Rules
    priority_section = """

## Source Priority Rules

1. **Primary Source**: Use values from the primary source table (typically `outreach_list`) when available
2. **Supplemental Sources**: Use directly related tables (gaps, diags, guardian, pcp) to fill missing columns
3. **Enterprise Override**: If this field has `enterprise_preferred` or `enterprise_only` policy, prioritize enterprise systems
4. **Only Join Related Tables**: Only use tables shown in the "Table Relationships" section or marked as directly joinable
5. **Avoid Unrelated Tables**: Do not use tables with no clear join path or that are marked as excluded

"""

    # Section 5: Pivot Field Handling
    pivot_section = ""
    if pivot_field and pivot_source_table:
        # Detect prefix pattern from column name
        match = re.search(r"^([a-zA-Z_]+?)(\d+)(_.*)?$", target_col_name)
        prefix = match.group(1) if match else "Value"
        suffix = match.group(3) if match and match.group(3) else ""

        pivot_section = f"""

## Pivot Field Handling

**This field is part of a numbered pivot sequence** (e.g., {prefix}1, {prefix}2, {prefix}3{suffix}).

- **Source Table**: {pivot_source_table} has multiple rows per member
- **Pivot Column**: {pivot_source_column or "value column"}
- **This Field Index**: Position {pivot_index} in the sequence (max: {pivot_max_count})
- **Pivot Logic**: Row 1 -> {prefix}1{suffix}, Row 2 -> {prefix}2{suffix}, etc.

When mapping, specify the source column name (e.g., `{pivot_source_column or "quality_gap_group"}`).
The SQL generation system will automatically handle the pivot logic to map values to the correct numbered field.

"""

    # Section 6: Type-Compatible Schema Reference
    schema_reference_section = ""
    if source_umfs:
        compatible_types = _get_compatible_types(target_col_type)
        compatible_types_str = ", ".join(sorted(compatible_types))

        schema_reference_section = f"""
## Schema Reference: Type-Compatible Fields

The target field `{target_col_name}` has type `{target_col_type}`. Below are ALL fields from available source tables that have compatible types ({compatible_types_str}), shown with table aliases and canonical names to help decode description references:

"""

        for source_umf in sorted(source_umfs, key=lambda x: x.get("table_name", "")):
            table_name = source_umf.get("table_name", "")
            canonical_name = source_umf.get("canonical_name", table_name)
            aliases = source_umf.get("aliases", [])
            table_desc = source_umf.get("description", "")

            # Skip if table is excluded
            if table_name in excluded_tables:
                continue

            # Build table header with aliases
            aliases_str = f", Aliases: [{', '.join(aliases)}]" if aliases else ""
            schema_reference_section += (
                f"\n### {table_name} (Canonical: {canonical_name}{aliases_str})\n"
            )
            if table_desc:
                schema_reference_section += f"*{table_desc}*\n\n"

            # Extract filename-derived columns from file_format.filename_pattern
            file_format = source_umf.get("file_format") or {}
            filename_pattern = file_format.get("filename_pattern") or {}
            captures = filename_pattern.get("captures", {})

            # Add filename-derived columns as virtual columns
            filename_columns = []
            for capture_index, column_name in sorted(captures.items()):
                # Create virtual column entry
                filename_columns.append(
                    {
                        "name": column_name,
                        "canonical_name": column_name.upper(),  # Typically uppercase
                        "data_type": "StringType",  # Filename captures are always strings
                        "source": "filename",
                        "description": f"Extracted from filename (capture group {capture_index})",
                        "aliases": [],
                    }
                )

            # Combine data columns + filename columns for iteration
            all_columns = list(source_umf.get("columns", [])) + filename_columns

            # Filter and show compatible fields
            compatible_fields = []
            for col in all_columns:
                col_name = col.get("name", "")
                col_type = col.get("data_type", "")
                col_canonical = col.get("canonical_name", col_name)
                col_aliases = col.get("aliases", [])
                col_desc = col.get("description", "")

                # Check type compatibility
                if col_type in compatible_types:
                    # Check if this field is a pre-filtered candidate
                    candidate_info = candidate_scores.get((table_name, col_name))

                    # Format: field_name (Canonical: CanonicalName, Aliases: [...]) [relevance, hop] - description
                    aliases_part = (
                        f", Aliases: [{', '.join(col_aliases)}]" if col_aliases else ""
                    )
                    canonical_part = (
                        f"Canonical: {col_canonical}"
                        if col_canonical != col_name
                        else ""
                    )

                    if canonical_part or aliases_part:
                        name_info = f" ({canonical_part}{aliases_part})"
                    else:
                        name_info = ""

                    # Add candidate scoring info if present
                    score_info = ""
                    if candidate_info:
                        score, hop_distance = candidate_info
                        score_info = f" **[relevance: {score:.2%}"

                        if hop_distance is not None:
                            if hop_distance == 0:
                                score_info += ", primary table"
                            elif hop_distance == 1:
                                score_info += ", direct join"
                            else:
                                score_info += f", {hop_distance}-hop join"

                        score_info += "]**"

                    # Show full description (no truncation)
                    desc_part = f" - {col_desc}" if col_desc else ""

                    compatible_fields.append(
                        f"- {col_name}{name_info}{score_info}{desc_part}"
                    )

            if compatible_fields:
                schema_reference_section += "\n".join(compatible_fields) + "\n"
            else:
                schema_reference_section += "*No compatible fields*\n"

        schema_reference_section += """
**Notes**:
- Fields marked with **[relevance: X%, ...]** were pre-selected based on name similarity and should be given priority
- When a field description references another table/field (e.g., "Refer Outreachlist file MEMBIND1"), use this schema reference to map canonical/source names to actual field names
- You may use ANY type-compatible field from this section, whether or not it has a relevance score

"""

    # Build reporting requirement section
    reporting_section = ""
    if reporting_requirement:
        req_label = {
            "R": "Required",
            "O": "Optional",
            "S": "Suggested",
        }.get(reporting_requirement, reporting_requirement)
        reporting_section = (
            f"\n- **Reporting Requirement**: {reporting_requirement} ({req_label})"
        )

    # Build nullable section
    nullable_section = ""
    if nullable:
        nullable_parts = [
            f"{ctx}: {str(val).lower()}" for ctx, val in sorted(nullable.items())
        ]
        if nullable_parts:
            nullable_section = f"\n- **Nullable**: {', '.join(nullable_parts)}"

    return f"""# Survivorship Mapping: {target_table_name}.{target_col_name}

Map a single target column to source tables using provided candidates.

## Target Table

- **Name**: {target_table_name}
- **Description**: {target_table_description}

## Target Column

- **Name**: {target_col_name}
- **Type**: {target_col_type}
- **Description**: {target_col_description}{reporting_section}{nullable_section}
{provenance_section}{inference_section}{excluded_section}{data_flow_section}{relationships_section}{priority_section}{pivot_section}{schema_reference_section}
## Output Format

Return a JSON object with this exact structure:

```json
{{
  "column": "{target_col_name}",
  "candidates": [
    {{
      "table": "ExactTableNameFromAbove",
      "column": "ExactColumnNameFromAbove",
      "expression": null,
      "priority": 1,
      "reason": "REQUIRED: Explain why this source was selected and why it has this priority",
      "join_filter": null,
      "table_instance": null
    }},
    {{
      "table": "AlternativeTable",
      "column": "AlternativeColumn",
      "expression": null,
      "priority": 2,
      "reason": "REQUIRED: Explain why this is a fallback and how it differs from priority 1",
      "join_filter": null,
      "table_instance": null
    }}
  ],
  "survivorship": {{
    "strategy": "highest_priority",
    "explanation": "REQUIRED: Comprehensive explanation that includes:
- Overall mapping strategy and approach
- Why selected sources were chosen (reference business rules, data quality, cardinality)
- Why other candidates were rejected (semantic mismatch, wrong table type, excluded)
- For empty candidates: enumerate key candidates examined and explain why each was unsuitable
- Expected behavior or fallback logic when applicable",
    "default_value": "IHA",
    "default_condition": "until assessment is completed"
  }}
}}
```

**Field Descriptions:**
- `column`: (optional) Source column name. Required unless `expression` is provided.
- `expression`: (optional) SQL expression for computed values (e.g., `"CONCAT_WS(' ', fname, lname)"`). Use instead of `column` for concatenation/computation.
- `join_filter`: (optional) SQL WHERE clause for filtering table joins (e.g., `"pcp_type = 'P4Q'"`). Use when joining same table with different filters.
- `table_instance`: (optional) Unique alias for table+filter combination (e.g., `"pcp_assigned"`, `"pcp_imputed"`). Required when same table is joined multiple times with different filters.

**Note**: Most fields will use simple `column` mapping. Only use advanced fields (`expression`, `join_filter`, `table_instance`) when patterns described in "Advanced Mapping Patterns" section apply.

**Note on default values:**
- Use `""` (empty string) for "leave blank" instructions: `{{"default_value": "", "default_condition": "if no value found"}}`
- Use `null` when no default is specified or field should be omitted
- Use specific values ("NA", "Unknown", 0, etc.) when explicitly mentioned

## Strict Rules

1. **Use ONLY table and column names from the "Schema Reference: Type-Compatible Fields" section above**
   - Prioritize fields marked with **[relevance: X%]** as they were pre-selected based on name similarity
   - Use any other type-compatible field if the description indicates a specific source
2. **DO NOT invent names not listed in the schema reference**
3. **Include ONLY the candidates that make sense for this column**
4. **priority: 1 is the best match, priority: 2 is fallback, etc.**
5. **Respect provenance policy**: If field is `enterprise_only`, do NOT use outreach tables. If `outreach_only`, do NOT use enterprise tables.
6. **Prefer directly joinable tables** over non-joinable tables
7. **REQUIRED: Every candidate MUST have a "reason" explaining why it was selected and its priority**
8. **REQUIRED: "explanation" must be comprehensive and include:**
   - Strategic rationale for the mapping approach
   - Specific candidate fields considered (especially when none selected or some rejected)
   - Why certain sources were preferred or excluded (reference business rules, data types, semantic fit)
   - Business rules and priority considerations applied
   - If no candidates selected: detailed reasoning about what was examined and why nothing was suitable
   - Expected fallback behavior or default logic when applicable
9. **Extract default values from target column description:**
   - **Explicit defaults**: If description contains "default to X", "Default it to X", "default value is X", extract X as `default_value`
   - **Implicit blank/empty defaults**: Recognize patterns indicating empty or null values:
     * "leave it blank", "leave blank", "populate as blank", "set to empty" -> `""`  (empty string)
     * "if missing, omit", "omit if not found" -> `null`
     * "if not available, N/A", "default to not applicable", "use NA when missing" -> `"N/A"` or `"NA"`
   - Extract condition phrase as `default_condition` (e.g., "if there is no first call date", "until assessment is completed", "when not available", "if value is not available")
   - Use appropriate type:
     * Empty string `""` for "blank" or "empty" instructions
     * `null` for "omit" instructions or when truly absent
     * String values for "N/A", "NA", "Unknown", etc.
     * Integer for whole numbers (e.g., 0, 99999)
     * Float for decimals (e.g., 0.0)
     * Boolean for true/false values
   - Examples:
     * "default to 0" -> `{{"default_value": 0}}`
     * "Default it to IHA" -> `{{"default_value": "IHA"}}`
     * "If there is no first call date, leave it blank" -> `{{"default_value": "", "default_condition": "if there is no first call date"}}`
     * "When not available, use NA" -> `{{"default_value": "NA", "default_condition": "when not available"}}`
     * "Populate 9999-12-31 if date unknown" -> `{{"default_value": "9999-12-31", "default_condition": "if date unknown"}}`
   - If no default mentioned, leave both fields as `null`
10. **If you cannot explain why a candidate should be included, DO NOT include it**
11. **Return ONLY valid JSON - no explanations or markdown outside the JSON**

## Advanced Mapping Patterns

### Pattern 1: Parallel Field Groups with Different Filters

When you encounter parallel field groups (e.g., `pcp_*` and `pcp2_*` fields), analyze whether they source from the same table but with different filtering logic:

**Example**: Primary vs Secondary PCP fields
- `pcp_name`, `pcp_npi`, `pcp_address` -> Assigned PCP (P4Q type)
- `pcp2_name`, `pcp2_npi`, `pcp2_address` -> Imputed PCP (IMP type)

**Implementation using `join_filter` and `table_instance`:**

```json
{{
  "column": "pcp_name",
  "candidates": [
    {{
      "table": "outreach_list_pcp",
      "table_instance": "pcp_assigned",
      "expression": "CONCAT_WS(' ', pcp_fname, pcp_lname)",
      "priority": 1,
      "join_filter": "pcp_type = 'P4Q'",
      "reason": "Assigned PCP (P4Q type) with full name concatenation"
    }},
    {{
      "table": "outreach_list_pcp",
      "table_instance": "pcp_imputed",
      "expression": "CONCAT_WS(' ', pcp_fname, pcp_lname)",
      "priority": 2,
      "join_filter": "pcp_type = 'IMP'",
      "reason": "Imputed PCP (IMP type) as fallback"
    }}
  ]
}}
```

```json
{{
  "column": "pcp2_name",
  "candidates": [
    {{
      "table": "outreach_list_pcp",
      "table_instance": "pcp_imputed",
      "expression": "CONCAT_WS(' ', pcp_fname, pcp_lname)",
      "priority": 1,
      "reason": "Imputed PCP only (reuses pcp_imputed instance)"
    }}
  ],
  "survivorship": {{
    "default_value": "NA",
    "default_condition": "if not provided"
  }}
}}
```

**Key principles:**
- Use `join_filter` to specify SQL WHERE conditions for filtering table joins
- Use `table_instance` to create unique aliases for same table with different filters
- **Reuse `table_instance` names** across columns when the filter is identical (e.g., both `pcp_name` priority 2 and `pcp2_name` priority 1 use `"pcp_imputed"`)
- This avoids redundant joins while maintaining correct semantics

### Pattern 2: Field Concatenation

When a target field requires combining multiple source columns (e.g., full name from first + last):

**Use the `expression` field instead of `column`:**

```json
{{
  "column": "provider_full_name",
  "candidates": [
    {{
      "table": "provider_roster",
      "expression": "CONCAT_WS(' ', provider_fname, provider_lname)",
      "priority": 1,
      "reason": "Concatenate first and last name with space separator"
    }}
  ]
}}
```

**Notes:**
- When using `expression`, set `column: null` or omit it
- Use `CONCAT_WS(' ', col1, col2)` for space-separated concatenation (handles nulls gracefully)
- The expression should be valid SQL that references columns from the source table

### Pattern 3: Detecting Filter-Based Disambiguation

**Indicators that filtering may be needed:**
- Target column descriptions mention specific type values (e.g., "P4Q type", "IMP provider")
- Parallel field naming patterns with numeric suffixes (pcp vs pcp2, contact1 vs contact2)
- Descriptions that say "primary" vs "secondary" or "assigned" vs "imputed"
- Source table has a type/status column with multiple distinct values

**When to use filtering:**
- If target description explicitly mentions filtering by a type/status field
- If parallel field groups exist and descriptions indicate they use different subsets of same source
- If a source table has multiple rows per key and different fields need different row selection logic
"""


# Deprecated aliases - use the public names above instead
_generate_survivorship_prompt = generate_survivorship_prompt
