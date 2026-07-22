"""Validate relationships between tables in UMF schemas."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tablespec.models import UMF


class RelationshipValidator:
    """Validate foreign key and relationship integrity."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Initialize validator.

        Args:
        ----
            logger: Optional logger instance

        """
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self.errors: list[tuple[str, str]] = []

    def validate_foreign_keys(
        self, umf: UMF, all_tables: dict[str, UMF]
    ) -> list[tuple[str, str]]:
        """Validate foreign key relationships.

        Checks that:
        - Referenced table exists in all_tables
        - Referenced column exists in referenced table
        - Source column exists in current table
        - Referenced table alias matches if used

        Args:
        ----
            umf: Current table UMF
            all_tables: Dict of all available tables by name/alias

        Returns:
        -------
            List of (error_type, error_message) tuples

        """
        self.errors = []

        if not umf.relationships or not umf.relationships.foreign_keys:
            return self.errors

        for fk in umf.relationships.foreign_keys:
            # Check source column exists
            source_col = next(
                (col for col in umf.columns if col.name.lower() == fk.column.lower()),
                None,
            )
            if not source_col:
                self.errors.append(
                    (
                        "missing_source_column",
                        f"Foreign key source column '{fk.column}' not found in {umf.table_name}",
                    )
                )
                continue

            # Check referenced table exists
            ref_table = all_tables.get(fk.references_table.lower())
            if not ref_table:
                # Try with aliases
                ref_table = next(
                    (
                        t
                        for t in all_tables.values()
                        if fk.references_table.lower()
                        in [a.lower() for a in (t.aliases or [])]
                    ),
                    None,
                )
                if not ref_table:
                    self.errors.append(
                        (
                            "missing_referenced_table",
                            f"Referenced table '{fk.references_table}' not found (from {umf.table_name}.{fk.column})",
                        )
                    )
                    continue

            # Check referenced column exists
            ref_col = next(
                (
                    col
                    for col in ref_table.columns
                    if col.name.lower() == fk.references_column.lower()
                ),
                None,
            )
            if not ref_col:
                self.errors.append(
                    (
                        "missing_referenced_column",
                        f"Referenced column '{fk.references_column}' not found in {fk.references_table} (from {umf.table_name}.{fk.column})",
                    )
                )

        return self.errors

    def validate_incoming_relationships(
        self, umf: UMF, all_tables: dict[str, UMF]
    ) -> list[tuple[str, str]]:
        """Validate incoming relationships (reverse foreign keys).

        Checks that source tables exist and have corresponding foreign keys.

        Args:
        ----
            umf: Current table UMF
            all_tables: Dict of all available tables by name/alias

        Returns:
        -------
            List of (error_type, error_message) tuples

        """
        errors = []

        if not umf.relationships or not umf.relationships.incoming:
            return errors

        for incoming in umf.relationships.incoming:
            # Check source table exists
            source_table = all_tables.get(incoming.source_table.lower())
            if not source_table:
                # Try with aliases
                source_table = next(
                    (
                        t
                        for t in all_tables.values()
                        if incoming.source_table.lower()
                        in [a.lower() for a in (t.aliases or [])]
                    ),
                    None,
                )
                if not source_table:
                    errors.append(
                        (
                            "missing_source_table_for_incoming",
                            f"Source table '{incoming.source_table}' not found (references {umf.table_name})",
                        )
                    )
                    continue

            # Check source column exists
            source_col = next(
                (
                    col
                    for col in source_table.columns
                    if col.name.lower() == incoming.source_column.lower()
                ),
                None,
            )
            if not source_col:
                errors.append(
                    (
                        "missing_source_column_for_incoming",
                        f"Source column '{incoming.source_column}' not found in {incoming.source_table} (references {umf.table_name})",
                    )
                )

        return errors

    def validate_all_relationships(
        self, tables: list[UMF]
    ) -> dict[str, list[tuple[str, str]]]:
        """Validate all relationships in a set of tables.

        Args:
        ----
            tables: List of UMF schemas to validate

        Returns:
        -------
            Dict mapping table names to lists of errors

        """
        # Build table lookup by name and aliases
        all_tables: dict[str, UMF] = {}
        for umf in tables:
            all_tables[umf.table_name.lower()] = umf
            if umf.aliases:
                for alias in umf.aliases:
                    all_tables[alias.lower()] = umf

        # Validate each table's relationships
        results = {}
        for umf in tables:
            errors = []
            errors.extend(self.validate_foreign_keys(umf, all_tables))
            errors.extend(self.validate_incoming_relationships(umf, all_tables))
            if errors:
                results[umf.table_name] = errors

        return results
