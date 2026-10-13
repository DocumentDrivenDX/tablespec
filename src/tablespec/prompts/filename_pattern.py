"""Filename pattern prompt generator - Generates prompts for extracting metadata from filenames."""

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

import yaml


class SummarizedConfigurations(TypedDict):
    """Type definition for summarized configuration structure."""

    patterns: list[str]
    examples: list[str]
    enumerations: dict[str, list[str]]
    notes: list[str]


def _convert_phase0_json_to_umf_structure(
    raw_data: dict, file_path: Path
) -> dict | None:
    """Convert Phase 0 raw JSON extraction to UMF-like structure for prompt generation.

    Phase 0 JSON structure:
        {"data": {"columns": [0, 1, 2], "data": [[row1_col1, row1_col2, ...], ...]}}

    UMF lookup structure (target):
        {"table_name": "...", "source_file": "...", "sheet_name": "...",
         "config_data": {"configurations": [{"specification": "...", "details": "...", "additional": [...]}]}}

    Args:
    ----
        raw_data: Raw JSON data from Phase 0 extraction
        file_path: Path to the source JSON file (for metadata)

    Returns:
    -------
        UMF-like dictionary structure, or None if conversion fails

    """
    if "data" not in raw_data:
        return None

    data_block = raw_data["data"]
    if "data" not in data_block:
        return None

    rows = data_block["data"]
    if not rows or len(rows) < 2:  # Need at least header + 1 data row
        return None

    # Extract table name from filename
    table_name = file_path.stem

    # Detect naming conventions worksheet structure by checking header row
    # Expected headers: ["S. No.", "File Name", "Naming Convention", "Details"]
    # or similar patterns where column 2 contains the actual filename pattern
    header_row = rows[0]
    is_naming_conventions_format = False
    pattern_col_idx = -1
    file_name_col_idx = -1

    if header_row and len(header_row) >= 3:
        header_lower = [str(h).lower() if h else "" for h in header_row]
        # Check for naming convention column patterns
        for idx, h in enumerate(header_lower):
            if "naming" in h and ("convention" in h or "covention" in h):  # Handle typo
                pattern_col_idx = idx
                is_naming_conventions_format = True
            elif "file" in h and "name" in h and pattern_col_idx == -1:
                file_name_col_idx = idx
            elif "detail" in h:
                pass

    # Build configurations from rows
    seen_rows: set[tuple[str, ...]] = set()
    configurations = []

    for idx, row in enumerate(rows):
        if idx == 0:
            # Header row - skip
            continue

        normalized_row = tuple(
            "" if cell is None else str(cell).strip() for cell in row
        )

        if not any(normalized_row):
            # Skip fully blank rows
            continue

        if normalized_row in seen_rows:
            # Skip duplicate rows (common when merged cells are repeated)
            continue
        seen_rows.add(normalized_row)

        config: dict[str, object] = {}

        if is_naming_conventions_format and pattern_col_idx >= 0:
            # Special handling for naming conventions worksheets
            # Map columns correctly: File Name -> specification, Pattern -> details
            if file_name_col_idx >= 0 and file_name_col_idx < len(normalized_row):
                config["specification"] = normalized_row[file_name_col_idx]
            elif len(normalized_row) >= 2:
                # Fallback: use column 1 (skip S. No. in column 0)
                config["specification"] = normalized_row[1]

            if pattern_col_idx < len(normalized_row):
                # Put the naming pattern as "details" so it gets recognized as a pattern
                pattern_value = normalized_row[pattern_col_idx]
                # Prefix with "File Name Format: " to trigger pattern detection
                config["details"] = (
                    f"File Name Format: {pattern_value}" if pattern_value else ""
                )

            # Collect additional context (details column and any other columns)
            additional = []
            for col_idx, value in enumerate(normalized_row):
                if col_idx in (0, file_name_col_idx, pattern_col_idx):
                    continue  # Skip S. No., file name, and pattern columns
                if value and value.strip():
                    additional.append(value)
            if additional:
                config["additional"] = additional
        else:
            # Standard format handling
            if len(normalized_row) >= 1:
                config["specification"] = normalized_row[0]
            if len(normalized_row) >= 2:
                config["details"] = normalized_row[1]
            if len(normalized_row) >= 3:
                additional = [
                    value for value in normalized_row[2:] if value and value.strip()
                ]
                if additional:
                    config["additional"] = additional

        configurations.append(config)

    # Build UMF-like structure
    return {
        "table_name": table_name,
        "source_file": file_path.parent.name,  # Workbook name
        "sheet_name": table_name,
        "config_data": {"configurations": configurations},
    }


def _flatten_values(texts: Iterable[str]) -> list[str]:
    """Split multi-value strings into individual tokens."""
    values: list[str] = []
    for text in texts:
        cleaned = text.replace("<br>", "\n")
        # Replace common separators with newline for unified splitting
        cleaned = re.sub(r"[;,]", "\n", cleaned)
        for raw_token in cleaned.splitlines():
            token = raw_token.strip()
            if not token:
                continue
            values.append(token)
    return values


def _summarize_configurations(configs: list[dict]) -> SummarizedConfigurations:
    """Extract patterns, examples, enumerations, and notes from raw configs."""
    summary: SummarizedConfigurations = {
        "patterns": [],
        "examples": [],
        "enumerations": {},
        "notes": [],
    }

    pattern_keywords = ("file name format", "naming convention", "pattern", "format")
    example_keywords = ("example", "sample file")
    enumeration_keywords = (
        "vendor",
        "state",
        "lob",
        "project",
        "projecttype",
        "file type",
        "possible values",
        "values",
        "valid values",
        "load",
    )

    for config in configs:
        spec = str(config.get("specification", "")).strip()
        details = str(config.get("details", "")).strip()
        additional = [str(val).strip() for val in config.get("additional", [])]

        combined_texts = [text for text in [details, *additional] if text]
        spec_lower = spec.lower()

        details_lower = details.lower()

        if any(
            keyword in spec_lower or keyword in details_lower
            for keyword in pattern_keywords
        ):
            for text in combined_texts or [spec]:
                if text and text not in summary["patterns"]:
                    summary["patterns"].append(text)
            continue

        if any(
            keyword in spec_lower or keyword in details_lower
            for keyword in example_keywords
        ):
            for value in _flatten_values(combined_texts or [details]):
                if value not in summary["examples"]:
                    summary["examples"].append(value)
            continue

        if any(
            keyword in spec_lower or keyword in details_lower
            for keyword in enumeration_keywords
        ):
            values = _flatten_values(combined_texts or [details])
            if values:
                label = spec if spec and not spec.isdigit() else details
                label = label or "Values"
                summary["enumerations"][label] = values
            continue

        # Retain other informative notes
        informative_texts = combined_texts or [spec, details]
        for raw_text in informative_texts:
            text = raw_text.strip()
            if text and text not in summary["notes"]:
                summary["notes"].append(text)

    return summary


def _collect_sheet_aliases(
    extraction_dir: Path, limit: int = 40
) -> tuple[list[str], bool]:
    """Collect distinct sheet names from Phase 0 extraction for alias references."""
    if not extraction_dir or not extraction_dir.exists():
        return ([], False)

    sheet_names: set[str] = set()
    for json_file in sorted(extraction_dir.rglob("*.json")):
        if json_file.name.startswith("_"):
            continue
        sheet_names.add(json_file.stem)

    sorted_names = sorted(sheet_names)
    truncated = len(sorted_names) > limit
    if truncated:
        sorted_names = sorted_names[:limit]

    return (sorted_names, truncated)


def generate_filename_pattern_prompt(
    naming_input: Path | list[Path], extraction_dir: Path | None = None
) -> str | None:
    """Generate prompt for extracting filename patterns from naming convention files.

    Args:
    ----
        naming_input: Either:
            - Path to directory containing lookup UMF YAML files (legacy Phase 1 lookups)
            - list[Path] of raw JSON files from Phase 0 extraction (new approach)
        extraction_dir: Optional path to Phase 0 extraction directory containing JSON files

    Returns:
    -------
        Prompt string if naming convention files are found, None otherwise

    """
    # Handle both directory (legacy) and file list (new) inputs
    naming_files = []
    if isinstance(naming_input, Path):
        # Legacy: directory with .lookup.yaml files (Phase 1 output)
        for pattern in ["*File_Naming*.lookup.yaml", "*Naming_Standards*.lookup.yaml"]:
            naming_files.extend(sorted(naming_input.glob(pattern)))
    elif isinstance(naming_input, list):
        # New: list of raw JSON files (Phase 0 output)
        naming_files = naming_input
    else:
        return None

    if not naming_files:
        return None

    # Load naming convention data
    naming_data = []
    for file_path in naming_files:
        # Detect file type and load appropriately
        if file_path.suffix == ".yaml":
            # UMF YAML format (from Phase 1 lookups)
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                naming_data.append(data)
        elif file_path.suffix == ".json":
            # Raw JSON format (from Phase 0 extraction)
            with open(file_path, encoding="utf-8") as f:
                raw_data = json.load(f)
                # Convert Phase 0 JSON to UMF-like structure for prompt generation
                converted_data = _convert_phase0_json_to_umf_structure(
                    raw_data, file_path
                )
                if converted_data:
                    naming_data.append(converted_data)

    # Build prompt
    prompt = """# Filename Pattern Extraction

## Objective
Identify canonical table names, filename patterns, dynamic source variables, aliases, and supporting metadata for each inbound file type. Use the naming convention excerpts below and focus on filename semantics only (column layouts and validation rules are handled elsewhere).

"""

    # Add extracted sheet names if available
    sheet_aliases, truncated = (
        _collect_sheet_aliases(extraction_dir) if extraction_dir else ([], False)
    )
    if sheet_aliases:
        prompt += "## Sheet Names Observed During Extraction\n\n"
        prompt += "**IMPORTANT:** Each sheet name below represents a DISTINCT table with its own unique schema. "
        prompt += "Create a separate canonical name for each sheet that appears in the extraction. "
        prompt += "Do NOT merge multiple sheet names into a single canonical name unless they are truly the same table with case variations.\n\n"
        prompt += ", ".join(f"`{name}`" for name in sheet_aliases)
        if truncated:
            prompt += ", ..."
        prompt += "\n\n"

    prompt += "## Naming Convention Summaries\n\n"

    # Add naming convention data
    for idx, data in enumerate(naming_data, 1):
        table_name = data.get("table_name", f"Naming_Spec_{idx}")
        prompt += f"### {table_name}\n\n"
        prompt += f"- **Source workbook:** {data.get('source_file', 'Unknown')}\n"
        prompt += f"- **Worksheet:** {data.get('sheet_name', 'Unknown')}\n"

        configs = data.get("config_data", {}).get("configurations", [])
        if configs:
            summary = _summarize_configurations(configs)

            if summary["patterns"]:
                prompt += "\n**Patterns & Variants**\n"
                for pattern in summary["patterns"]:
                    prompt += f"- {pattern}\n"

            if summary["enumerations"]:
                prompt += "\n**Enumerated Values**\n"
                for label, values in sorted(summary["enumerations"].items()):
                    formatted_values = ", ".join(values[:12])
                    if len(values) > 12:
                        formatted_values += ", ..."
                    prompt += f"- {label}: {formatted_values}\n"

            if summary["examples"]:
                prompt += "\n**Example Filenames**\n"
                for example in summary["examples"][:8]:
                    prompt += f"- {example}\n"
                if len(summary["examples"]) > 8:
                    prompt += "- ...\n"

            if summary["notes"]:
                prompt += "\n**Additional Notes**\n"
                for note in summary["notes"][:6]:
                    prompt += f"- {note}\n"
                if len(summary["notes"]) > 6:
                    prompt += "- ...\n"

        prompt += "\n"

    prompt += """## Task Focus

**Create one canonical name for each unique table in the extraction** (see Sheet Names section above).

For each distinct table:
- Determine the canonical table name from the **table identifier** in the filename pattern (e.g., OutreachList, OutreachListPCP, OutreachListDiags are SEPARATE tables).
- The fixed portion of the filename pattern (between variable segments like vendor/state/date) identifies the table.
- **DO NOT collapse multiple tables into one canonical name** - if they have different sheet names in the extraction, they are different tables.
- Describe each filename pattern as a regex with capture groups.
- Escape regex metacharacters properly and double-escape backslashes inside JSON strings (e.g., `\\\\d`, `\\\\.`) so the regex field parses with `json.loads()`.
- Label capture groups according to the semantics present (vendor, subvendor, state, lob, assessment_year, load_mode, etc.). Only include captures that exist in the pattern.
- Surface enumerated values or other metadata that help downstream processing.
- Record aliases (sheet names, case variations, known alternates) - but ONLY for the SAME table.
- Craft a long-form description that reconciles all relevant context for that file type (purpose, source, cadence, pattern expectations, notable exceptions, and examples).

Do **not** document column schemas or field-level validation rules here -- they are produced by later phases.

## Output Format: Valid JSON Only

**IMPORTANT**: Your output will be parsed with Python's `json.loads()`. Return only valid JSON - no markdown fences, no comments, no code.

**For `valid_values` arrays**: Use only quoted strings. Extract "MD, ME, MP" as `["MD", "ME", "MP"]`.

## Output Contract

Return a JSON object with a single `tables` key containing a dictionary keyed by canonical table name (snake_case). Each table entry must include:
- `canonical_name`: Canonical table name in PascalCase format (e.g., OutreachList, SupplementalContact, DispositionReport). This should preserve the human-readable casing from specifications.
- `aliases`: Array of known alternate names (including sheet names when different).
- `description`: Rich narrative summarizing business purpose, sourcing, frequency, and filename expectations. Incorporate enumerations and examples from the summaries above when helpful.
- `regex`: Regular expression describing the filename pattern.
- `captures`: Object mapping 1-based capture indexes to semantic identifiers (e.g., `source_vendor`, `source_state`, `source_assessment_year`, `source_load_mode`). Only map captures you actually emit.
- `delimiter`: (Optional) File delimiter character (e.g., "|", ",", "\\t"). Default is "|" if not specified.
- `encoding`: (Optional) Text encoding (e.g., "utf-8", "ascii", "latin-1"). Default is "utf-8" if not specified.
- `header`: (Optional) Whether first row contains column names (true/false). Default is true if not specified.
- `skip_rows`: (Optional) Number of rows to skip at beginning (integer). Default is 0 if not specified.
- `field_metadata`: Optional object where keys match capture identifiers and values describe the field. Include when available:
  - `description` (recommended)
  - `valid_values` (optional, include only when explicitly enumerated in the specification)

  **Guidelines for `valid_values`:**
  - Include when the specification explicitly enumerates allowed values (e.g., "Valid values: MD, ME, MP")
  - Include for clearly bounded sets like load modes (I/A/U) or documented LOB codes
  - OPTIONAL for open-ended fields like vendor names, project IDs, or dates
  - Do NOT force-extract from example filenames unless the spec indicates the list is exhaustive

Return only the raw JSON object -- no explanations, markdown fences, or additional text before or after it.

## Example Output Format

Here is a complete working example showing the correct JSON structure:

```json
{
  "tables": {
    "outreach_list": {
      "canonical_name": "OutreachList",
      "aliases": ["OutreachList", "OutReachList"],
      "description": "Member outreach list delivered by vendors for daily/weekly outreach programs. Filename embeds vendor, optional sub-vendor, state, LOB, project id, file date, and file type code.",
      "regex": "(?i)^([A-Z0-9]+)(?:-([A-Z0-9]+))?_(?:([A-Z]{2})_)?(MD|ME|MP|MKP)_OutreachList_([0-9]+)_([0-9]{8})_(I|A|U)\\\\.txt$",
      "captures": {
        "1": "vendor",
        "2": "subvendor",
        "3": "state",
        "4": "lob",
        "5": "project_id",
        "6": "file_date_yyyymmdd",
        "7": "load_mode"
      },
      "delimiter": "|",
      "encoding": "utf-8",
      "header": true,
      "skip_rows": 0,
      "field_metadata": {
        "vendor": {
          "description": "Primary vendor name; HARMONY for shared contracts with HCMG",
          "valid_values": ["HCMG", "HARMONY", "SIGNIFY", "INOVALON"]
        },
        "subvendor": {
          "description": "Optional sub-vendor appended with hyphen",
          "valid_values": ["CCS", "INOVALON", "SIGNIFY"]
        },
        "state": {
          "description": "Two-letter state code",
          "valid_values": ["TX", "IL", "FL", "NC"]
        },
        "lob": {
          "description": "Line of Business: MD=Medicaid, ME=Medicare, MP=Marketplace",
          "valid_values": ["MD", "ME", "MP", "MKP"]
        },
        "load_mode": {
          "description": "File type: I=Initial, A=Append/Incremental, U=Update",
          "valid_values": ["I", "A", "U"]
        }
      }
    }
  }
}
```

**KEY POINTS**:
- Top-level structure MUST have a `tables` key containing all table definitions
- `captures` is a FLAT object with numeric string keys ("1", "2", "3", etc.)
- Each value in `captures` is a SINGLE STRING identifying the field (e.g., "source_vendor")
- Do NOT nest other table definitions or objects inside `captures`
- Multiple tables go INSIDE the `tables` object, NOT nested inside each other

## Extracting valid_values from Examples

**CRITICAL**: Parse example filenames to extract concrete values for filename components:

Example: `HCMG_TX_MD_OutreachList_1234_20210318_A.txt`
- From this single example, extract:
  - `vendor`: "HCMG"
  - `state`: "TX"
  - `lob`: "MD"
  - `project_id`: "1234"
  - `file_date`: "20210318"
  - `load_mode`: "A"

When multiple examples are provided, combine values across all examples:
- If you see: `HCMG_TX_...`, `SIGNIFY_FL_...`, `INOVALON_CA_...`
- Then extract: `vendor: ["HCMG", "SIGNIFY", "INOVALON"]` and `state: ["TX", "FL", "CA"]`

**Do NOT omit `valid_values` for fields just because they appear "open-ended"** - include sample values from examples even if the field might accept other values in production.

### REMINDER: JSON Format Requirements for `valid_values`

When you extract values like `"MD"`, `"ME"`, `"MP"`:
- Output format: `"valid_values": ["MD", "ME", "MP"]`
- NOT as code: `"valid_values": ["MD", "ME, MP".split(", ")]`
- NOT with arrays: `"valid_values": ["MD", [0], "ME"]`

The entire JSON object must parse successfully with Python's `json.loads()`. Any deviation from pure JSON format will cause pipeline failures.

## Critical Rules

- **Each extracted sheet name represents a unique table** - do not merge OutreachList, OutreachListPCP, OutreachListDiags, etc. into a single canonical name.
- The fixed table identifier in filename patterns (e.g., "OutreachList" vs "OutreachListDiags") distinguishes different tables.
- Aliases are for case variations and alternative spellings of the SAME table, not for grouping related tables.
- Regexes should anchor both ends (`^` and `$`) and escape literal periods.
- Use non-capturing groups for optional structure segments; only capture meaningful variables.
- Use snake_case for capture identifiers (e.g., `vendor`, `lob`, `state`). Do NOT use a `source_` prefix unless the unprefixed name would conflict with an existing data column in the table.
- Load mode values (I, R, A, U) should be included when present, with metadata describing each code.
- Ensure alias values are globally unique across canonical names; prefer lowercase/uppercase variants in addition to sheet names.
- **Extract and include `valid_values` for EVERY captured field** - this is essential for downstream sample data generation.
- Output MUST be valid JSON (no comments, trailing commas, or markdown code fences).

Your output will be parsed directly with `json.loads()`.
"""

    return prompt


__all__ = ["generate_filename_pattern_prompt"]
