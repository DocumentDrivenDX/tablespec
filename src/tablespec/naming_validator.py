# SPDX-License-Identifier: MIT OR Apache-2.0
"""Validate naming conventions in UMF schemas."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tablespec.models import UMF


def validate_naming_conventions(umf: UMF) -> list[tuple[str, str]]:
    """Validate that table and column names follow lowercase_snake_case convention.

    Args:
        umf: UMF schema to validate

    Returns:
        List of (entity_name, error_message) tuples for violations

    """
    errors = []

    # Validate table name
    if not _is_valid_snake_case(umf.table_name):
        errors.append(
            (
                "table_name",
                f"Table name must be lowercase_snake_case (found: {umf.table_name})",
            )
        )

    # Validate column names
    for col in umf.columns:
        if not _is_valid_snake_case(col.name):
            errors.append(
                (
                    col.name,
                    f"Column name must be lowercase_snake_case (found: {col.name})",
                )
            )

    return errors


def validate_column_naming(umf: UMF) -> list[tuple[str, str]]:
    """Deprecated: Use validate_naming_conventions instead.

    Validate that all column names follow lowercase_snake_case convention.

    Args:
        umf: UMF schema to validate

    Returns:
        List of (column_name, error_message) tuples for violations

    """
    errors = []

    for col in umf.columns:
        # Check if column name is lowercase_snake_case
        if not _is_valid_snake_case(col.name):
            errors.append(
                (
                    col.name,
                    f"Column name must be lowercase_snake_case (found: {col.name})",
                )
            )

    return errors


def _is_valid_snake_case(name: str) -> bool:
    """Check if a name is valid lowercase_snake_case.

    Valid patterns:
    - lowercase letters, digits, underscores only
    - starts with lowercase letter
    - no consecutive underscores
    - no trailing/leading underscores

    Args:
        name: Name to validate

    Returns:
        True if valid, False otherwise

    """
    # Must match: start with lowercase, then lowercase/digits/underscores, no trailing underscore
    return bool(re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", name))
