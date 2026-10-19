# SPDX-License-Identifier: MIT OR Apache-2.0
"""YAML formatting utilities for UMF files.

This module provides tools for formatting YAML files using pure ruamel.yaml:
- Dictionary key sorting (alphabetical)
- Literal block scalars (|-) for multi-line and long strings
- Consistent indentation (2-space mapping, 4-space sequence, offset 2)
- 72-character line length

The formatter is idempotent and produces human-readable output.
"""

from tablespec.formatting.yaml_formatter import (
    YAMLFormatError,
    format_yaml_dict,
    format_yaml_file,
    format_yaml_files,
    format_yaml_string,
)

__all__ = [
    "YAMLFormatError",
    "format_yaml_dict",
    "format_yaml_file",
    "format_yaml_files",
    "format_yaml_string",
]
