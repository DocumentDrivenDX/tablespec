"""Relationship prompt generator - Generates FK relationship detection prompts."""

import logging
from pathlib import Path

import yaml

from .utils import clean_description, is_relationship_relevant_column

logger = logging.getLogger(__name__)


def generate_relationship_prompt(umf_dir: Path, lookup_dir: Path) -> str:
    """Generate comprehensive relationship detection prompt."""
    # Load all UMF files for relationship analysis
    all_tables = {}
    lookup_tables = {}

    # Load main data tables
    umf_files = sorted(umf_dir.glob("*.umf.yaml"))
    filtered_count = 0
    for umf_file in umf_files:
        try:
            with umf_file.open() as f:
                umf_data = yaml.safe_load(f)

            # Skip generated tables (they are outputs, not relationship sources)
            table_type = umf_data.get("table_type", "provided")
            if table_type == "generated":
                filtered_count += 1
                continue

            table_name = umf_data["table_name"]
            all_tables[table_name] = umf_data
        except Exception:
            logger.debug("Failed to load UMF file %s, skipping", umf_file)

    # Load lookup tables if they exist
    if lookup_dir.exists():
        lookup_files = sorted(lookup_dir.glob("*.lookup.yaml"))
        for lookup_file in lookup_files:
            try:
                with lookup_file.open() as f:
                    lookup_data = yaml.safe_load(f)

                table_name = lookup_data["table_name"]
                lookup_tables[table_name] = lookup_data
            except Exception:
                logger.debug("Failed to load lookup file %s, skipping", lookup_file)

    prompt = """# Healthcare Data Table Relationship Analysis

You are a healthcare data architect analyzing table relationships in a payer data management system. Please identify potential foreign key relationships between tables based on column names, data types, and descriptions.

## CRITICAL: Column Name Accuracy

When creating relationships, you MUST use the EXACT column names as they appear in the table specifications below.
DO NOT normalize or standardize column names in your output - use them exactly as shown.

For example:
- If Table A has "ClientMemberId" and Table B has "ClientMbrID", use those exact names
- DO NOT output both as "CLIENT_MEMBER_ID" even if they represent the same concept
- Your job is to identify the relationships, not to standardize the naming

## Analysis Guidelines

1. **Identify Clear Relationships**: Look for columns that reference the same entity across tables (e.g., CLIENT_MEMBER_ID appearing in multiple tables)

2. **Handle Column Name Variations**: Use fuzzy matching to identify relationships between columns with similar names but different formatting. Common patterns include:
   - Abbreviations: Member/Mbr, Client/Clnt, Provider/Prov, Phone/Ph, Email/Em
   - Case variations: ClientMemberId vs CLIENT_MEMBER_ID vs clientmemberid
   - Separator differences: Client_Member_ID vs ClientMemberID vs Client-Member-ID
   - ID suffixes: MemberID vs MemberId vs Member_ID vs MemberIdentifier

## Examples of Fuzzy Matching Relationships

**Example 1**: Member ID variations (use exact column names)
- OutreachList.ClientMemberId <-> SupplementalContact.ClientMbrID (confidence: 0.90)
- OutreachList.ClientMemberId <-> Vendor_Assessment.ClientMemberId (confidence: 0.95)
- DisenrollmentFile.ClientMbrID <-> SupplementalPhone.ClientMbrID (confidence: 0.95)

Note: Even though ClientMemberId and ClientMbrID represent the same concept, they must be listed with their exact column names.

## Fuzzy Matching Algorithm with Cardinality Weighting

Apply this systematic approach:

1. Normalize column names for comparison
2. Check for abbreviation patterns
3. **Estimate cardinality from column characteristics:**
   - Does name suggest uniqueness? (ID, KEY, NUMBER, CODE)
   - Does description mention unique/primary/identifier?
   - What is the data type? (INTEGER IDs often unique, VARCHAR(2) likely not)
4. **Calculate weighted similarity:**
   - Base similarity from name matching (0-1.0)
   - Multiply by cardinality factor (0.3-1.0 based on expected uniqueness)
- Final score = name_similarity x cardinality_factor
5. **Only create relationship if:**
   - Weighted score > 0.70 AND
   - This is the highest scoring match between these two tables
6. **IMPORTANT**: In the output JSON, use the ORIGINAL column names, not the normalized versions

## CRITICAL: Cardinality and Unique Constraints in Relationship Selection

**Fundamental Principle**: Relationships should use the highest cardinality (most unique) columns available.

### Understanding Cardinality:

1. **Unique Constraints = Highest Cardinality**
   - Primary keys are guaranteed unique (100% cardinality)
   - Unique indexes ensure high cardinality
   - ID/identifier columns typically have unique or near-unique values
   - These make the BEST join keys (confidence: 0.90-1.0)

2. **Cardinality Indicators from Column Names:**
   - Columns ending in: _ID, _NUM, _NUMBER, _CODE, _KEY (typically high cardinality)
   - Columns with "identifier", "number" in description (typically unique)
   - Foreign key references to other tables (inherit cardinality from source)

3. **Low Cardinality Warning Signs:**
   - Date/time columns (often only a few unique values per dataset)
   - Type/category columns (TYPE, STATUS, FLAG, CATEGORY)
   - Descriptive text fields (NAME, DESC, DESCRIPTION when not entity names)
   - Boolean or flag columns (Y/N, 0/1, TRUE/FALSE)
   - These should RARELY be primary join keys (confidence: <0.50)

### Mathematical Basis:
- Cardinality = (unique values) / (total rows)
- High cardinality (>50%) = good for joins
- Low cardinality (<10%) = poor for joins, causes cartesian products

### When Multiple Columns Match Between Tables:

**Selection Algorithm:**
1. Calculate expected cardinality for each matching column
2. Choose the column with highest expected cardinality
3. If cardinality is similar, prefer columns with:
   - Unique constraints mentioned in description
   - "ID" or "identifier" in the name
   - Simpler data types (INTEGER over VARCHAR)

**Example Decision Process:**
- Table A and B both have: DateColumn, TypeColumn, and IdentifierColumn
- DateColumn: ~5 unique values (5% cardinality) -> confidence: 0.3
- TypeColumn: ~10 unique values (10% cardinality) -> confidence: 0.4
- IdentifierColumn: ~900 unique values (90% cardinality) -> confidence: 0.95
- **Result**: Use IdentifierColumn for the relationship

3. **Consider Healthcare Domain**: Use your knowledge of healthcare data patterns:
   - Member/Patient identifiers typically link enrollment, claims, and clinical data
   - Provider identifiers link claims to provider information
   - Claim numbers link claim headers to detail lines
   - Authorization numbers link authorizations to claims
   - Drug codes (NDC) and procedure codes link to reference tables

4. **Confidence Scoring Based on Cardinality**:

Calculate confidence using expected cardinality:
   - **0.90-1.0**: Columns with unique constraints or ID-pattern names
   - **0.80-0.89**: High cardinality columns without explicit uniqueness
   - **0.60-0.79**: Moderate cardinality (composite keys, partial identifiers)
   - **0.30-0.59**: Low cardinality matches (only note as correlation, not primary join)
   - **Below 0.30**: Not a meaningful relationship

**Cardinality Estimation Formula:**
   - If column name contains ID/KEY/NUM/CODE: Start at 0.8
   - If description mentions "unique": Add 0.15
   - If description mentions "identifier": Add 0.1
   - If column is date/type/flag: Cap at 0.5
   - If exact name match: Add 0.1
   - If fuzzy match only: Subtract 0.05

5. **Relationship Types**:
   - **primary_to_foreign**: Clear primary key to foreign key relationship
   - **foreign_to_foreign**: Both columns are foreign keys referencing same entity
   - **many_to_many**: Relationship likely requires a junction table
   - **hierarchical**: Parent-child relationship within same entity type

## Relationship Deduplication Rules

**CRITICAL**: When you find multiple potential relationships between the same table pair:

1. **Keep only the highest cardinality relationship as primary**
2. **List others as "metadata_correlation" type (not for joining)**
3. **Never create multiple foreign_to_foreign relationships between the same two tables**

Example output for multiple matches:
```json
[
  {
"source_table": "TableA",
"source_column": "RecordID",
"target_table": "TableB",
"target_column": "RecordID",
"relationship_type": "foreign_to_foreign",
"confidence": 0.95,
"reasoning": "High cardinality unique identifier match"
  },
  {
"source_table": "TableA",
"source_column": "CreatedDate",
"target_table": "TableB",
"target_column": "CreatedDate",
"relationship_type": "metadata_correlation",
"confidence": 0.35,
"reasoning": "Low cardinality date correlation, not suitable for joins"
  }
]
```

## CRITICAL: JSON Structure Requirements

**Each relationship MUST be a complete, flat object with ALL required fields:**

Required fields for every relationship:
1. `source_table` (string)
2. `source_column` (string)
3. `target_table` (string)
4. `target_column` (string)
5. `relationship_type` (string)
6. `confidence` (number between 0 and 1)
7. `reasoning` (string)
8. `cardinality` (string)

**FORBIDDEN patterns that will cause parsing errors:**

NEVER nest a `relationships` array inside a relationship object:
```json
{
  "source_table": "Table1",
  "source_column": "ID",
  "relationships": [...]
}
```

NEVER embed JSON structures in field values:
```json
{
  "source_table": "Table1",
  "source_column": "CLIENT_M{\\n  \\"relationships\\": [..."
}
```

NEVER omit required fields:
```json
{
  "source_table": "Table1",
  "source_column": "ID"
}
```

CORRECT format - flat object with all required fields:
```json
{
  "source_table": "Table1",
  "source_column": "RecordID",
  "target_table": "Table2",
  "target_column": "RecordID",
  "relationship_type": "foreign_to_foreign",
  "confidence": 0.95,
  "reasoning": "High cardinality unique identifier match",
  "cardinality": "one-to-many"
}
```

**Before submitting your output:**
1. Verify each relationship in the array is a complete, flat object
2. Verify each relationship has all 8 required fields
3. Verify no relationship contains nested arrays or objects
4. Verify all field values are simple strings/numbers (not JSON structures)

## Relationship Completeness Check

After identifying relationships, verify:
- Central/hub tables (those with many columns referenced elsewhere) should have many relationships
- Detail/child tables typically connect to their parent via a high-cardinality key
- Tables with no relationships are quite rare - most tables connect to at least one other
- If a table seems isolated, double-check for ID columns that might match others

## Available Tables and Columns

"""

    # Add each table's metadata
    for table_name in sorted(all_tables.keys()):
        umf_data = all_tables[table_name]

        # Filter to only relationship-relevant columns
        relevant_columns = []
        for col in umf_data["columns"]:
            col_name = col["name"]
            col_type = col.get("data_type", "VARCHAR")
            col_desc = col.get("description", "No description")

            if is_relationship_relevant_column(col_name, col_desc, col_type):
                relevant_columns.append(col)

        # Skip table if no relevant columns found
        if not relevant_columns:
            continue

        prompt += f"\n### Table: {table_name}\n"

        if umf_data.get("description"):
            prompt += f"**Description**: {umf_data['description']}\n\n"

        prompt += "**Columns**:\n"

        for col in relevant_columns:
            col_name = col["name"]
            col_type = col.get("data_type", "VARCHAR")
            col_desc = clean_description(col.get("description", "No description"))

            # Use compact format - remove nullable info and sample values
            prompt += f"- `{col_name}` ({col_type}): {col_desc}\n"

    # Add lookup tables section if any exist
    if lookup_tables:
        prompt += f"\n## Lookup Tables ({len(lookup_tables)} tables)\n\n"
        prompt += "**IMPORTANT**: Lookup tables contain reference/code data with high cardinality primary keys.\n"
        prompt += "Look for columns in main tables that might reference these lookup table primary keys.\n"
        prompt += "Common patterns: STATUS, DISPOSITION, TYPE, CODE columns linking to lookup tables.\n\n"

        for table_name in sorted(lookup_tables.keys()):
            lookup_data = lookup_tables[table_name]

            # Find primary key and key columns for lookup tables
            primary_key = None
            lookup_columns = []

            for col in lookup_data.get("columns", []):
                col_name = col["name"]
                col_type = col.get("data_type", "VARCHAR")
                is_pk = col.get("is_primary_key", False)

                if is_pk:
                    primary_key = col_name

                # Always include primary key and common lookup columns
                if is_pk or any(
                    keyword in col_name.lower()
                    for keyword in [
                        "status",
                        "type",
                        "code",
                        "definition",
                        "description",
                    ]
                ):
                    lookup_columns.append(col)

            if lookup_columns:
                prompt += f"\n### Lookup Table: {table_name}\n"

                if lookup_data.get("description"):
                    prompt += f"**Description**: {lookup_data['description']}\n"

                if primary_key:
                    prompt += f"**Primary Key**: `{primary_key}` (use this for foreign key relationships)\n"

                prompt += "**Key Columns**:\n"

                for col in lookup_columns:
                    col_name = col["name"]
                    col_type = col.get("data_type", "VARCHAR")
                    col_desc = clean_description(
                        col.get("description", "No description")
                    )
                    pk_marker = (
                        " (PRIMARY KEY)" if col.get("is_primary_key", False) else ""
                    )

                    prompt += f"- `{col_name}` ({col_type}){pk_marker}: {col_desc}\n"

    prompt += """

## Expected Output Format

**IMPORTANT**: The output JSON has THREE separate sections:
1. `relationships` array - Contains ONLY flat relationship objects (no nesting)
2. `relationship_groups` array - Separate section for grouping analysis
3. `data_integrity_notes` array - Separate section for observations

Please provide your analysis in the following JSON format:

```json
{
  "relationships": [
    {
      "source_table": "Table1",
      "source_column": "COLUMN_NAME",
      "target_table": "Table2",
      "target_column": "COLUMN_NAME",
      "relationship_type": "primary_to_foreign|foreign_to_foreign|many_to_many|hierarchical|lookup_to_main",
      "confidence": 0.95,
      "reasoning": "Clear explanation of why this relationship exists",
      "cardinality": "one-to-one|one-to-many|many-to-one|many-to-many"
    },
    {
      "source_table": "Table3",
      "source_column": "ANOTHER_COLUMN",
      "target_table": "Table4",
      "target_column": "ANOTHER_COLUMN",
      "relationship_type": "foreign_to_foreign",
      "confidence": 0.92,
      "reasoning": "Another clear explanation",
      "cardinality": "many-to-one"
    }
  ],
  "relationship_groups": [
    {
      "entity_type": "Member|Provider|Claim|Authorization|etc",
      "description": "How this entity type connects across tables",
      "tables_involved": ["Table1", "Table2", "Table3"],
      "key_columns": ["COLUMN1", "COLUMN2"]
    }
  ],
  "data_integrity_notes": [
    "Any observations about potential data quality issues or missing relationships"
  ]
}
```

**Field Validation Checklist** - Every relationship object must have:
- source_table: String (table name from specifications)
- source_column: String (exact column name from table)
- target_table: String (table name from specifications)
- target_column: String (exact column name from table)
- relationship_type: String (one of the allowed types)
- confidence: Number between 0.0 and 1.0
- reasoning: String explaining the relationship
- cardinality: String (one of: one-to-one, one-to-many, many-to-one, many-to-many)

## Analysis Request

Analyze all tables and identify relationships following these principles:

1. **For each table pair, select the highest cardinality relationship**
2. **Prefer columns with unique constraints or ID-like patterns**
3. **Avoid low-cardinality fields** (dates, types, flags) for primary relationships
4. **One primary relationship per table pair** - others marked as metadata_correlation
5. **Trust cardinality over name similarity** - exact name match with low cardinality is worse than fuzzy match with high cardinality

**Special Focus on Lookup Table Relationships:**
6. **Identify lookup table references**: Look for columns in main tables that reference lookup table primary keys
7. **Common lookup patterns**: STATUS -> Disposition_Statuses, TYPE -> Standard_Dispositions, CODE -> Master_Data
8. **Use lookup_to_main relationship type**: When a main table column references a lookup table primary key
9. **High confidence for exact matches**: Lookup relationships should have confidence 0.90+ when column names suggest status/type/code patterns

**Expected patterns:**
- Some central tables will have many relationships (these are typically "hub" tables)
- Other tables will have only a few relationships (typically "detail" or "lookup" tables)
- Tables with no relationships are quite rare in integrated systems
- Focus on quality over quantity - better to have fewer high-confidence, high-cardinality relationships than many low-quality ones

**Use the EXACT column names** from the specifications - do not normalize them in your output

Remember: A good join key distributes data evenly (high cardinality), while a bad join key creates cartesian products (low cardinality).

Focus on relationships that are internal to this dataset - do not assume external reference tables exist unless they are listed above.

## FINAL OUTPUT VALIDATION

Before submitting your JSON output, perform these validation checks:

1. **Structure Validation:**
   - The output is valid JSON (no syntax errors)
   - Top-level object has exactly 3 keys: "relationships", "relationship_groups", "data_integrity_notes"
   - Each key maps to an array (not an object or nested structure)

2. **Relationships Array Validation:**
   - Every item in the "relationships" array is a flat object (no nested arrays or objects)
   - Every relationship has ALL 8 required fields (source_table, source_column, target_table, target_column, relationship_type, confidence, reasoning, cardinality)
   - No relationship has extra keys like "relationships", "related_tables", or any nested structures
   - All field values are simple types (strings for text, numbers for confidence)

3. **Field Value Validation:**
   - No field value contains embedded JSON or newline characters
   - Column names match EXACTLY as shown in specifications (no normalization)
   - Table names match EXACTLY as shown in specifications
   - Confidence values are between 0.0 and 1.0

If any validation check fails, fix the issue before outputting. Malformed JSON will cause pipeline failures.
"""

    return prompt


# Deprecated alias - use the public name above instead
_generate_relationship_prompt = generate_relationship_prompt
