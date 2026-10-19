# SPDX-License-Identifier: MIT OR Apache-2.0
"""Shared utilities for prompt generation."""

import re
from pathlib import Path

import yaml


def is_relationship_relevant_column(
    col_name: str, col_desc: str, col_type: str
) -> bool:
    """Filter columns to only include those relevant for relationship discovery."""
    col_name_lower = col_name.lower()
    col_desc_lower = col_desc.lower()

    # Include columns with ID-like patterns in name
    id_patterns = [
        "id",
        "_id",
        "code",
        "number",
        "npi",
        "tin",
        "key",
        "mbr",
        "member",
        "client",
        "encounter",
    ]
    if any(pattern in col_name_lower for pattern in id_patterns):
        return True

    # Include integer types (often foreign keys)
    if col_type.upper() in ["INTEGER", "BIGINT", "INT"]:
        return True

    # Include columns with relationship keywords in description
    relationship_keywords = [
        "identifier",
        "reference",
        "foreign",
        "link",
        "maps to",
        "unique",
        "primary",
    ]
    if any(keyword in col_desc_lower for keyword in relationship_keywords):
        return True

    # Exclude descriptive fields
    exclude_patterns = [
        "name",
        "address",
        "city",
        "state",
        "zip",
        "phone",
        "email",
        "description",
        "note",
        "comment",
    ]
    return not (
        any(pattern in col_name_lower for pattern in exclude_patterns)
        and not any(
            id_pattern in col_name_lower for id_pattern in ["id", "code", "number"]
        )
    )


def clean_description(description: str) -> str:
    """Clean description to remove validation rules and examples."""
    if not description:
        return "No description"

    # Remove common validation patterns
    patterns_to_remove = [
        r"Should be populated if.*?\.",
        r"Valid values:.*?(?=\.|$)",
        r"Sample values for.*?(?=\.|$)",
        r"Ex:.*?(?=\.|$)",
        r"Example:.*?(?=\.|$)",
        r"Must be.*?(?=\.|$)",
        r"Format:.*?(?=\.|$)",
    ]

    cleaned = description
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    # Clean up extra spaces and periods
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\.+", ".", cleaned)

    return cleaned if cleaned else "No description"


def load_umf(umf_file: Path) -> dict:
    """Load UMF data from a YAML file."""
    try:
        with umf_file.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}


# Deprecated aliases - use the public names above instead
_is_relationship_relevant_column = is_relationship_relevant_column
_clean_description = clean_description
_load_umf = load_umf
