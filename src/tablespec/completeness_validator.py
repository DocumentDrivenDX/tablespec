"""Validate UMF schema completeness.

This module validates that UMF schemas have:
1. All required provenance metadata columns
2. Valid domain type mappings
3. Required baseline validations for each column
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# REQUIRED_BASELINE_EXPECTATION_TYPES may not be defined in gx_baseline yet
try:
    from tablespec.gx_baseline import REQUIRED_BASELINE_EXPECTATION_TYPES
except ImportError:
    REQUIRED_BASELINE_EXPECTATION_TYPES: frozenset[str] = frozenset()

# ingestion.constants may not be ported yet
try:
    from tablespec.ingestion.constants import PROVENANCE_COLUMNS
except ImportError:
    # Fallback: define provenance columns inline (canonical list from sync_baseline)
    PROVENANCE_COLUMNS: dict[str, Any] = {
        "meta_source_name": {"name": "meta_source_name", "data_type": "VARCHAR"},
        "meta_source_checksum": {
            "name": "meta_source_checksum",
            "data_type": "VARCHAR",
        },
        "meta_load_dt": {"name": "meta_load_dt", "data_type": "DATETIME"},
        "meta_snapshot_dt": {"name": "meta_snapshot_dt", "data_type": "DATETIME"},
        "meta_source_offset": {"name": "meta_source_offset", "data_type": "INTEGER"},
        "meta_checksum": {"name": "meta_checksum", "data_type": "VARCHAR"},
        "meta_pipeline_version": {
            "name": "meta_pipeline_version",
            "data_type": "VARCHAR",
        },
        "meta_component": {"name": "meta_component", "data_type": "VARCHAR"},
    }

if TYPE_CHECKING:
    from tablespec.models import UMF


# Required provenance column names
REQUIRED_PROVENANCE_COLUMNS = set(PROVENANCE_COLUMNS.keys())

# Re-export for backwards compatibility and simpler name
REQUIRED_BASELINE_TYPES = REQUIRED_BASELINE_EXPECTATION_TYPES


def validate_provenance_columns(umf: UMF) -> list[tuple[str, str]]:
    """Validate that all required provenance metadata columns are present.

    Args:
        umf: UMF schema to validate

    Returns:
        List of (column_name, error_message) tuples for missing columns

    """
    errors: list[tuple[str, str]] = []

    # Get actual column names from UMF
    actual_columns = {col.name for col in umf.columns}

    # Check for missing provenance columns
    for required_col in sorted(REQUIRED_PROVENANCE_COLUMNS):
        if required_col not in actual_columns:
            errors.append(
                (
                    required_col,
                    f"Missing required provenance column: {required_col}",
                )
            )

    return errors


def validate_domain_types(umf: UMF) -> list[tuple[str, str]]:
    """Validate that domain_type values map to valid domain definitions.

    Args:
        umf: UMF schema to validate

    Returns:
        List of (column_name, error_message) tuples for invalid domain types

    """
    try:
        from tablespec.inference.domain_types import DomainTypeRegistry
    except ImportError:
        logger.debug("inference module not available, skipping domain type validation")
        return []

    errors: list[tuple[str, str]] = []
    registry = DomainTypeRegistry()
    valid_domain_types = set(registry.list_domain_types())

    for col in umf.columns:
        domain_type = getattr(col, "domain_type", None)
        if domain_type and domain_type not in valid_domain_types:
            errors.append(
                (
                    col.name,
                    f"Invalid domain_type '{domain_type}'. "
                    f"Valid types: {', '.join(sorted(valid_domain_types))}",
                )
            )

    return errors


def validate_baseline_expectations(umf: UMF) -> list[tuple[str, str]]:
    """Validate that required baseline validations exist for each column.

    Checks that every column has:
    - expect_column_to_exist

    Args:
        umf: UMF schema to validate

    Returns:
        List of (column_name, error_message) tuples for missing validations

    """
    errors: list[tuple[str, str]] = []

    # Build index of existing validation rule_types by column
    validations_by_column: dict[str, set[str]] = {}
    if umf.validation_rules and umf.validation_rules.column_level:
        for col_name, rules in umf.validation_rules.column_level.items():
            validations_by_column[col_name] = {rule.rule_type for rule in rules}

    # Check each column has required baseline validations
    for col in umf.columns:
        col_validations = validations_by_column.get(col.name, set())
        missing_types = REQUIRED_BASELINE_TYPES - col_validations

        for missing_type in sorted(missing_types):
            errors.append(
                (
                    col.name,
                    f"Missing required baseline validation: {missing_type}",
                )
            )

    return errors


def _get_column_validations(umf: UMF, column_name: str) -> list[Any]:
    """Get all validations for a specific column.

    Args:
        umf: UMF schema
        column_name: Column name to get validations for

    Returns:
        List of ValidationRule objects for the column

    """
    if not umf.validation_rules or not umf.validation_rules.column_level:
        return []

    return umf.validation_rules.column_level.get(column_name, [])
