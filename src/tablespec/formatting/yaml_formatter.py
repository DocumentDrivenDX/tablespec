"""Unified YAML formatter using pure ruamel.yaml for consistent, idempotent formatting.

This module provides a high-level API for formatting YAML files with:
1. Dictionary key sorting (alphabetical)
2. Literal block scalars (|-) for multi-line and long strings
3. Consistent indentation (2-space mapping, 4-space sequence, offset 2)
4. 72-character line length
5. Comment preservation (YAML comments are retained through formatting)

The formatter is idempotent - running it multiple times produces identical output.
"""

from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.constructor import ConstructorError
from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

from tablespec.formatting.constants import YAML_LINE_LENGTH

# YAML 1.1 boolean literals that must be quoted when meant as strings
# These are parsed as True/False by YAML parsers if unquoted
# See: https://yaml.org/type/bool.html
YAML_BOOLEAN_LITERALS = frozenset(
    {
        # True values
        "true",
        "True",
        "TRUE",
        "yes",
        "Yes",
        "YES",
        "on",
        "On",
        "ON",
        # False values
        "false",
        "False",
        "FALSE",
        "no",
        "No",
        "NO",
        "off",
        "Off",
        "OFF",
    }
)

# YAML 1.1 null literals that must be quoted when meant as strings
YAML_NULL_LITERALS = frozenset(
    {
        "null",
        "Null",
        "NULL",
        "~",
    }
)


class YAMLFormatError(Exception):
    """Raised when YAML formatting fails."""


def sort_recursive(obj: Any) -> Any:
    """Sort object recursively for deterministic YAML output.

    IMPORTANT: Never sorts lists - order matters for columns and validations!
    Only sorts dictionary keys for deterministic output.

    This function preserves ruamel.yaml's CommentedMap and CommentedSeq objects
    to retain comments during formatting.

    Args:
        obj: Object to sort

    Returns:
        Sorted dict keys (recursively) but preserved list order

    """
    if isinstance(obj, CommentedMap):
        # Sort keys in-place to preserve comments attached to the CommentedMap
        sorted_keys = sorted(obj.keys(), key=str)
        # Create a new CommentedMap with sorted keys, preserving comments
        new_map = CommentedMap()
        # Copy over any top-level comments from the original map
        if hasattr(obj, "ca") and obj.ca:
            new_map.ca.comment = obj.ca.comment
        for key in sorted_keys:
            new_map[key] = sort_recursive(obj[key])
            # Preserve comments attached to this key
            if hasattr(obj, "ca") and obj.ca and key in obj.ca.items:
                new_map.ca.items[key] = obj.ca.items[key]
        return new_map

    if isinstance(obj, dict):
        # Plain dict - sort keys alphabetically
        return {k: sort_recursive(obj[k]) for k in sorted(obj.keys(), key=str)}

    if isinstance(obj, (CommentedSeq, list)):
        # NEVER sort lists - order matters!
        if isinstance(obj, CommentedSeq):
            new_seq = CommentedSeq([sort_recursive(item) for item in obj])
            # Preserve comments on the sequence
            if hasattr(obj, "ca") and obj.ca:
                new_seq.ca.comment = obj.ca.comment
            return new_seq
        return [sort_recursive(item) for item in obj]

    return obj


def prepare_for_yaml(obj: Any) -> Any:
    """Prepare object for YAML serialization with proper type preservation.

    Handles several concerns:
    1. Converts multi-line strings to LiteralScalarString for block format (|-)
    2. Quotes strings that look like YAML boolean/null literals to prevent coercion
    3. Preserves escape sequences and special characters
    4. Preserves CommentedMap/CommentedSeq to retain comments

    Policy:
    - Boolean-like strings (true, false, yes, no, on, off): Force single-quoted
    - Null-like strings (null, ~): Force single-quoted
    - Strings with newlines: Convert to literal block preserving newlines
    - Short strings: Keep as plain/quoted (ruamel.yaml auto-chooses)

    Args:
        obj: Object to prepare (recursively processes dicts and lists)

    Returns:
        Object with strings converted appropriately for YAML serialization

    """
    if isinstance(obj, CommentedMap):
        # Preserve CommentedMap structure and comments
        for key in obj:
            obj[key] = prepare_for_yaml(obj[key])
        return obj

    if isinstance(obj, dict):
        return {k: prepare_for_yaml(v) for k, v in obj.items()}

    if isinstance(obj, CommentedSeq):
        # Preserve CommentedSeq structure and comments
        for i, item in enumerate(obj):
            obj[i] = prepare_for_yaml(item)
        return obj

    if isinstance(obj, list):
        return [prepare_for_yaml(item) for item in obj]

    if isinstance(obj, str):
        # CRITICAL: Quote strings that look like YAML boolean or null literals
        # Without quoting, these become actual booleans/None after YAML round-trip
        # This fixes the PR #548 bug where value_set: [true, false] became booleans
        if obj in YAML_BOOLEAN_LITERALS or obj in YAML_NULL_LITERALS:
            return SingleQuotedScalarString(obj)

        # Quote strings that YAML parsers may coerce to floats/ints
        # e.g. ".", ".0", "1_000", "0x1F", "1e3", or bare underscores
        if obj and not obj.isspace():
            stripped = obj.strip()
            if stripped in (".", "..", "...", "_") or (
                stripped.replace(".", "", 1)
                .replace("_", "")
                .replace("-", "", 1)
                .replace("+", "", 1)
                .replace("e", "", 1)
                .replace("E", "", 1)
                .isdigit()
                and not stripped.isalpha()
                and stripped
                != obj  # only if stripping changed it, or contains dots/underscores
            ):
                try:
                    float(stripped)
                    return SingleQuotedScalarString(obj)
                except ValueError:
                    pass

        # Check if string contains non-printable characters that YAML doesn't allow
        # in literal blocks:
        # - Control characters < 0x20 (except tab, newline, carriage return)
        # - DEL character (0x7F)
        # - C1 control characters (0x80-0x9F)
        # These must stay as quoted strings with escape sequences
        has_control_chars = any(
            (ord(char) < 0x20 and char not in ["\t", "\n", "\r"])
            or ord(char) == 0x7F  # DEL
            or (0x80 <= ord(char) <= 0x9F)  # C1 control characters
            for char in obj
        )

        if has_control_chars:
            # Keep as regular string so ruamel.yaml will quote and escape it
            return obj

        # Check if string has significant leading/trailing whitespace
        # The |- chomping indicator strips trailing whitespace, so we must preserve
        # strings with meaningful whitespace as quoted strings
        if obj and (obj[0].isspace() or obj[-1].isspace()):
            # Has leading or trailing whitespace - keep as quoted string
            return obj

        # Check if string should use literal block format
        # Only use literal blocks for strings that already have newlines
        # Long single-line strings stay as quoted strings (ruamel.yaml won't wrap them
        # because we set width=4096)
        has_newlines = "\n" in obj

        if has_newlines:
            # Use literal block scalar (|-) for multi-line strings
            # The |- chomping indicator strips trailing newlines for cleaner output
            return LiteralScalarString(obj)

    # Return other types unchanged (int, float, bool, None, etc.)
    return obj


def format_yaml_string(content: str) -> str:
    """Format YAML content string using pure ruamel.yaml.

    This is the core in-memory formatter that doesn't touch the filesystem.
    Use this when you want to format YAML before writing to disk.

    Pipeline:
    1. Load YAML content
    2. Sort dictionary keys alphabetically
    3. Convert long/multi-line strings to literal blocks
    4. Serialize with consistent formatting

    The formatter is idempotent - running it multiple times produces identical output.

    Note: Top-level lists are not supported. UMF files always have dictionaries
    at the root level (column:, validations:), so this restriction doesn't affect
    our use case.

    Args:
        content: YAML content as string

    Returns:
        Formatted YAML string

    Raises:
        YAMLFormatError: If formatting fails or input has a top-level list

    """
    try:
        # Configure ruamel.yaml for parsing
        yaml_parser = YAML()
        yaml_parser.preserve_quotes = True
        yaml_parser.default_flow_style = False

        # Strip leading --- if present
        content_to_parse = content.lstrip()
        if content_to_parse.startswith("---\n"):
            content_to_parse = content_to_parse[4:]
        elif content_to_parse.startswith("---"):
            content_to_parse = content_to_parse[3:]

        # Load YAML - fall back to PyYAML's safe_load if ruamel chokes on
        # ambiguous scalars like "._" that YAML 1.1 resolvers tag as float
        try:
            data = yaml_parser.load(StringIO(content_to_parse))
        except (ValueError, ConstructorError):
            import yaml as pyyaml

            data = pyyaml.safe_load(content_to_parse)

        if data is None:
            return content

        # Check for top-level list (unsupported)
        if isinstance(data, list):
            msg = (
                "Top-level lists are not supported by the YAML formatter. "
                "UMF files should always have a dictionary at the root level with "
                "'column:' and 'validations:' keys. If you're seeing this error, "
                "your YAML file may be structured incorrectly."
            )
            raise YAMLFormatError(msg)

        # Sort keys recursively
        sorted_data = sort_recursive(data)

        # Prepare strings for literal block formatting
        prepared_data = prepare_for_yaml(sorted_data)

        # Configure ruamel.yaml for serialization
        yaml_writer = YAML()
        yaml_writer.default_flow_style = False
        # Set width to a very large value to prevent wrapping of quoted strings
        # (which can corrupt data by adding indentation spaces)
        # Our literal blocks handle long strings cleanly instead
        yaml_writer.width = 4096
        yaml_writer.explicit_start = False
        yaml_writer.explicit_end = False
        yaml_writer.indent(mapping=2, sequence=4, offset=2)
        yaml_writer.preserve_quotes = False

        # Serialize to string
        output = StringIO()
        yaml_writer.dump(prepared_data, output)
        return output.getvalue()

    except YAMLFormatError:
        raise
    except Exception as e:
        msg = f"Error formatting YAML: {e}"
        raise YAMLFormatError(msg) from e


def format_yaml_dict(data: dict[str, Any]) -> str:
    """Format Python dict to formatted YAML string.

    This is optimized for formatting data structures before saving to disk.

    Args:
        data: Python dictionary to format

    Returns:
        Formatted YAML string ready to write to file

    Raises:
        YAMLFormatError: If formatting fails or input is not a dict

    """
    if not isinstance(data, dict):
        msg = f"Expected dict, got {type(data).__name__}"
        raise YAMLFormatError(msg)

    try:
        # Sort and prepare data
        sorted_data = sort_recursive(data)
        prepared_data = prepare_for_yaml(sorted_data)

        # Configure ruamel.yaml
        yaml_writer = YAML()
        yaml_writer.default_flow_style = False
        yaml_writer.width = YAML_LINE_LENGTH
        yaml_writer.explicit_start = False
        yaml_writer.explicit_end = False
        yaml_writer.indent(mapping=2, sequence=4, offset=2)
        yaml_writer.preserve_quotes = False

        # Serialize
        output = StringIO()
        yaml_writer.dump(prepared_data, output)
        return output.getvalue()

    except Exception as e:
        msg = f"Error formatting dict to YAML: {e}"
        raise YAMLFormatError(msg) from e


def format_yaml_file(filepath: Path, check_only: bool = False) -> bool:
    """Format a single YAML file using pure ruamel.yaml.

    Args:
        filepath: Path to YAML file
        check_only: If True, only check if changes needed (don't write)

    Returns:
        True if changes were made (or needed in check mode)

    Raises:
        YAMLFormatError: If formatting fails

    """
    if not filepath.exists():
        msg = f"File not found: {filepath}"
        raise YAMLFormatError(msg)

    try:
        # Read original content
        original_content = filepath.read_text(encoding="utf-8")

        # Format using in-memory formatter
        final_content = format_yaml_string(original_content)

        # Compare output to original to detect actual changes
        changed = original_content != final_content

        if changed and not check_only:
            filepath.write_text(final_content, encoding="utf-8")

        return changed

    except Exception as e:
        msg = f"Error formatting {filepath}: {e}"
        raise YAMLFormatError(msg) from e


def format_yaml_files(
    filepaths: list[Path], check_only: bool = False
) -> tuple[int, int, list[str]]:
    """Format multiple YAML files.

    Args:
        filepaths: List of YAML file paths
        check_only: If True, only check if changes needed (don't write)

    Returns:
        Tuple of (changed_count, error_count, error_messages)
        - changed_count: Number of files that changed (or need changes)
        - error_count: Number of files with errors
        - error_messages: List of error messages

    """
    changed_count = 0
    error_count = 0
    error_messages = []

    for filepath in filepaths:
        try:
            if format_yaml_file(filepath, check_only=check_only):
                changed_count += 1
        except YAMLFormatError as e:
            error_count += 1
            error_messages.append(str(e))

    return changed_count, error_count, error_messages
