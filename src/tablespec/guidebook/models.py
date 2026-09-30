"""Page payloads for the guidebook site.

Fields ending in ``_html`` hold pre-escaped HTML produced server-side by
``format_prose``; every other string is inserted by the page as text.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from tablespec.lineage.models import (  # noqa: TC001 - needed at runtime for Pydantic models
    LineageGraph,
    SourceFile,
    SourceLocation,
)


class RuleDoc(BaseModel):
    """A validation rule (Great Expectations expectation)."""

    type: str
    severity: str = "warning"
    description: str | None = None
    kwargs: dict[str, Any] | None = None


class CandidateDoc(BaseModel):
    """One derivation candidate of a column."""

    priority: int
    table: str
    table_id: str | None = Field(default=None, description="None for 'intermediate'")
    column: str | None = None
    expression: str | None = Field(default=None, description="Formatted SQL")
    table_instance: str | None = None
    join_filter: str | None = None
    row_filter: str | None = None
    via: str | None = None
    reason_html: str | None = None


class SurvivorshipDoc(BaseModel):
    """How candidates are combined."""

    strategy: str
    explanation_html: str | None = None
    default_value: str | None = None
    default_condition: str | None = None


class UsedByRef(BaseModel):
    """A downstream column that reads this column (ADR-018: FK is downstream-only)."""

    column_id: str
    via: Literal["derivation", "fk"]


class ColumnDoc(BaseModel):
    """Everything shown for one column."""

    name: str
    data_type: str
    description: str | None = None
    canonical_name: str | None = None
    format: str | None = None
    length: int | None = None
    nullable: dict[str, bool] | bool | None = None
    key_type: str | None = None
    source: str | None = None
    internal: bool = False
    default: str | None = None
    provenance_policy: str | None = None
    provenance_notes: str | None = None
    derivation_strategy: str | None = None
    derivation_explanation_html: str | None = None
    candidates: list[CandidateDoc] = Field(default_factory=list)
    survivorship: SurvivorshipDoc | None = None
    validations: list[RuleDoc] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    used_by: list[UsedByRef] = Field(default_factory=list)


class ForeignKeyDoc(BaseModel):
    """A declared join from this table to another."""

    column: str
    references_table_id: str
    references_column: str
    join_filter: str | None = None


class TableDoc(BaseModel):
    """Payload of a table page."""

    id: str
    group: str
    table: str
    table_type: str | None = None
    description: str | None = None
    primary_key: list[str] = Field(default_factory=list)
    source_file: str | None = None
    source_sheet_name: str | None = None
    base_table: str | None = None
    base_table_strategy: str | None = None
    final_filter: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    union_base_tables: list[str] = Field(default_factory=list)
    file: SourceFile | None = None
    location: SourceLocation | None = None
    foreign_keys: list[ForeignKeyDoc] = Field(default_factory=list)
    upstream_tables: list[str] = Field(default_factory=list)
    downstream_tables: list[str] = Field(default_factory=list)
    table_rules: list[RuleDoc] = Field(default_factory=list)
    columns: list[ColumnDoc] = Field(default_factory=list)
    lineage: LineageGraph


class TableSummary(BaseModel):
    """A table row on a group page."""

    name: str
    table_type: str | None = None
    description: str | None = None
    column_count: int = 0


class GroupDoc(BaseModel):
    """Payload of a group page (the home page for a flat root)."""

    name: str = Field(
        description="Group (subfolder); '' for UMFs at the discovery root"
    )
    tables: list[TableSummary] = Field(default_factory=list)


class HomeDoc(BaseModel):
    """Payload of the home page when UMFs are grouped into subfolders."""

    title: str
    groups: list[GroupDoc] = Field(default_factory=list)
