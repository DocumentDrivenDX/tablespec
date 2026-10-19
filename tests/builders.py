# SPDX-License-Identifier: MIT OR Apache-2.0
"""UMF Builder DSL for composable test fixtures.

Provides a fluent builder API for constructing UMF objects in tests,
replacing verbose dict literals and repetitive helper functions.

Usage:
    umf = (
        UMFBuilder("my_table")
        .column("id", "INTEGER", key_type="primary")
        .column("name", "VARCHAR", length=100, nullable=False)
        .column("amount", "DECIMAL", precision=10, scale=2)
        .primary_key("id")
        .description("My test table")
        .build()
    )
"""

from __future__ import annotations

from typing import Any

from tablespec.models.umf import (
    ForeignKey,
    Nullable,
    Relationships,
    UMF,
    UMFColumn,
)


class UMFBuilder:
    """Fluent builder for UMF test fixtures."""

    def __init__(self, table_name: str, version: str = "1.0") -> None:
        self._table_name = table_name
        self._version = version
        self._columns: list[dict[str, Any]] = []
        self._column_names: set[str] = set()
        self._primary_key: list[str] | None = None
        self._foreign_keys: list[ForeignKey] = []
        self._description: str | None = None
        self._table_type: str | None = None

    def column(
        self,
        name: str,
        data_type: str = "VARCHAR",
        *,
        nullable: bool | dict[str, bool] | Nullable | None = None,
        length: int | None = None,
        precision: int | None = None,
        scale: int | None = None,
        domain_type: str | None = None,
        description: str | None = None,
        sample_values: list[str] | None = None,
        format: str | None = None,
        key_type: str | None = None,
        source: str | None = None,
        **kwargs: Any,
    ) -> UMFBuilder:
        """Add a column definition. Returns self for chaining."""
        if name in self._column_names:
            msg = f"Duplicate column name: '{name}'"
            raise ValueError(msg)
        self._column_names.add(name)

        # Normalize nullable to a Nullable object or None
        resolved_nullable: Nullable | None = None
        if isinstance(nullable, bool):
            # Convert bool to a Nullable with a default context key
            resolved_nullable = Nullable(**{"default": nullable})
        elif isinstance(nullable, dict):
            resolved_nullable = Nullable(**nullable)
        elif isinstance(nullable, Nullable):
            resolved_nullable = nullable

        col_data: dict[str, Any] = {
            "name": name,
            "data_type": data_type,
        }
        if resolved_nullable is not None:
            col_data["nullable"] = resolved_nullable
        if length is not None:
            col_data["length"] = length
        if precision is not None:
            col_data["precision"] = precision
        if scale is not None:
            col_data["scale"] = scale
        if domain_type is not None:
            col_data["domain_type"] = domain_type
        if description is not None:
            col_data["description"] = description
        if sample_values is not None:
            col_data["sample_values"] = sample_values
        if format is not None:
            col_data["format"] = format
        if key_type is not None:
            col_data["key_type"] = key_type
        if source is not None:
            col_data["source"] = source
        col_data.update(kwargs)

        self._columns.append(col_data)
        return self

    def primary_key(self, *columns: str) -> UMFBuilder:
        """Set the primary key columns."""
        self._primary_key = list(columns)
        return self

    def foreign_key(
        self,
        column: str,
        *,
        references: str,
        confidence: float | None = None,
    ) -> UMFBuilder:
        """Add a foreign key relationship.

        Args:
            column: Source column name.
            references: Target in "table.column" format.
            confidence: Optional confidence score (0.0-1.0).
        """
        parts = references.split(".", 1)
        if len(parts) != 2:
            msg = f"references must be 'table.column' format, got: '{references}'"
            raise ValueError(msg)
        ref_table, ref_column = parts
        fk = ForeignKey(
            column=column,
            references_table=ref_table,
            references_column=ref_column,
            confidence=confidence,
        )
        self._foreign_keys.append(fk)
        return self

    def description(self, desc: str) -> UMFBuilder:
        """Set the table description."""
        self._description = desc
        return self

    def table_type(self, tt: str) -> UMFBuilder:
        """Set the table type."""
        self._table_type = tt
        return self

    def build(self) -> UMF:
        """Build and return a validated UMF Pydantic object."""
        columns = [UMFColumn(**col_data) for col_data in self._columns]

        relationships: Relationships | None = None
        if self._foreign_keys:
            relationships = Relationships(foreign_keys=self._foreign_keys)

        return UMF(
            version=self._version,
            table_name=self._table_name,
            columns=columns,
            primary_key=self._primary_key,
            description=self._description,
            table_type=self._table_type,
            relationships=relationships,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation suitable for generate_sql_ddl() etc.

        Filters out None values to match the dict-based patterns used
        in schema generator tests.
        """
        umf = self.build()
        return umf.model_dump(exclude_none=True)
