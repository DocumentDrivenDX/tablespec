"""Pydantic models for the design-time column lineage graph.

Table ids are ``group.table`` (just ``table`` for UMFs at the discovery root)
and column ids append ``.column``. Edges point upstream -> downstream (data
flows from ``source`` to ``target``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EdgeKind = Literal[
    "column",  # candidate.column reference
    "expression",  # column referenced inside candidate.expression
    "base_column",  # derivation.strategy: base_column
    "primary_key",  # derivation.strategy: primary_key
    "unpivot",  # unpivot value column fans out to unpivot_columns
    "sibling",  # {{col:...}} / intermediate reference to another column of the same table
]

LeafKind = Literal[
    "source_column",  # a column read from a source table's data
    "filename_capture",  # value captured from the file name by filename_pattern
    "source_metadata",  # ingestion metadata (meta_* columns) of a source table
    "constant",  # literal default / NULL / union_value
    "runtime_metadata",  # generated-table metadata stamped at runtime
    "unresolved",  # table or column could not be found
]


class SourceFile(BaseModel):
    """Source facts for a non-generated table (from ``umf.effective_source()``)."""

    kind: str = Field(
        default="delimited", description="delimited | parquet | json | jdbc"
    )
    filename_regex: str | None = None
    captures: dict[int, str] = Field(default_factory=dict)
    delimiter: str | None = None
    encoding: str | None = None
    header: bool | None = None
    quote_char: str | None = None
    source_directory: str | None = Field(
        default=None, description="Effective folder (source_directory or table name)"
    )


class SourceLocation(BaseModel):
    """Where a source table's data is read from; doubles as the source system."""

    source_system: str
    path: str


class LineageTable(BaseModel):
    """A table participating in the lineage graph."""

    id: str
    group: str
    table: str
    table_type: str | None = Field(
        default=None, description="None when the UMF was not found"
    )
    description: str | None = None
    base_table: str | None = None
    base_inferred: bool = False
    file: SourceFile | None = None
    location: SourceLocation | None = None


class LineageColumn(BaseModel):
    """A column participating in the lineage graph."""

    id: str
    table_id: str
    name: str
    data_type: str | None = None
    source: str | None = None
    description: str | None = None
    internal: bool = False
    leaf_kind: LeafKind | None = Field(
        default=None, description="Set only when no upstream edges"
    )
    capture_group: int | None = None
    constant: str | None = None


class LineageEdge(BaseModel):
    """Upstream column -> downstream column."""

    source: str
    target: str
    kind: EdgeKind
    priority: int | None = None
    table_instance: str | None = None
    join_filter: str | None = None
    row_filter: str | None = None
    via: str | None = Field(
        default=None, description="join_via lookup table (a join bridge)"
    )
    expression: str | None = None


class LeafSource(BaseModel):
    """An ultimate source of a target column."""

    column_id: str
    table_id: str
    column: str
    leaf_kind: LeafKind
    source_system: str | None = None
    location: str | None = None
    filename_regex: str | None = None
    capture_group: int | None = None
    path_priority: list[int] = Field(default_factory=list)
    hops: int = 0


class LineageGraph(BaseModel):
    """Upstream subgraph reachable from ``targets`` plus per-target leaf summaries."""

    targets: list[str] = Field(default_factory=list)
    tables: dict[str, LineageTable] = Field(default_factory=dict)
    columns: dict[str, LineageColumn] = Field(default_factory=dict)
    edges: list[LineageEdge] = Field(default_factory=list)
    leaf_summaries: dict[str, list[LeafSource]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
