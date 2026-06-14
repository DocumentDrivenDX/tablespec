"""Forward-lineage (downstream consumer) index.

Walks every discovered UMF once and inverts the derivation graph so each
upstream column knows who consumes it. The result is consulted while rendering
each page (no runtime lookup once the page is written).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from tablespec.guidebook.discovery import discover_umfs
from tablespec.umf_loader import UMFLoader

if TYPE_CHECKING:
    from pathlib import Path

    from tablespec.guidebook.discovery import DiscoveredUmf

logger = logging.getLogger(__name__)


class DownstreamRef(BaseModel):
    """One downstream consumer of an upstream column."""

    group: str = Field(description="Consumer group (parent subfolder, '' if flat)")
    table: str = Field(description="Consumer table")
    column: str = Field(description="Consumer column")
    via: str = Field(
        description=(
            "How the upstream is consumed: 'derivation' (named in a derivation"
            " candidate) or 'fk' (foreign-key reference)."
        ),
    )
    description: str | None = Field(
        default=None,
        description=(
            "Consumer column description from UMF (used for hover tooltips on"
            " downstream links). Falls back to consumer table description, or"
            " None if neither is set."
        ),
    )


class ReverseLineageIndex(BaseModel):
    """Map of (upstream_group, upstream_table, upstream_column) -> consumers.

    Lookups use string keys 'group.table.column' so the index serializes
    cleanly to JSON. ``group`` may be empty (flat layout); the key then looks
    like '.table.column'.
    """

    consumers: dict[str, list[DownstreamRef]] = Field(default_factory=dict)

    def lookup(self, group: str, table: str, column: str) -> list[DownstreamRef]:
        return self.consumers.get(f"{group}.{table}.{column}", [])


def _split_table_ref(table_ref: str, default_group: str) -> tuple[str, str]:
    """Resolve 'group.table' or bare 'table' to (group, table).

    A qualified reference's prefix is the group (== the source subfolder name);
    a bare reference resolves to the current UMF's group.
    """
    if "." in table_ref:
        group, table = table_ref.split(".", 1)
        return group, table
    return default_group, table_ref


def _consumer_desc(
    consumer_column: str,
    column_descriptions: dict[str, str | None],
    table_description: str | None,
) -> str | None:
    """Pick the best tooltip text for a downstream consumer.

    Prefers the consumer column's UMF description; falls back to the consumer
    table description. Whitespace is stripped so multi-line descriptions
    don't leak newlines into the rendered ``title`` attribute.
    """
    desc = column_descriptions.get(consumer_column) or table_description
    return desc.strip() if desc else None


def build_reverse_lineage_index(
    root: Path,
    discovered: list[DiscoveredUmf] | None = None,
) -> ReverseLineageIndex:
    """Scan all UMF under ``root`` and invert the derivation + FK graph.

    Args:
        root: Discovery root directory.
        discovered: Optionally pass an already-computed discovery list to avoid
            re-walking the tree. When None, ``discover_umfs(root)`` is called.

    """
    if discovered is None:
        discovered = discover_umfs(root)
    loader = UMFLoader()

    consumers: dict[str, list[DownstreamRef]] = {}

    def add(
        upstream_group: str,
        upstream_table: str,
        upstream_column: str,
        ref: DownstreamRef,
    ) -> None:
        key = f"{upstream_group}.{upstream_table}.{upstream_column}"
        consumers.setdefault(key, []).append(ref)

    for unit in discovered:
        try:
            umf = loader.load(unit.path)
        except Exception as exc:
            logger.warning(
                "Skipping %s during reverse-lineage build: %s",
                unit.path,
                exc,
            )
            continue

        table_description = getattr(umf, "description", None) or None
        # Build once per table so FK entries can look up the consumer column's
        # description without re-scanning the UMF.
        column_descriptions = {col.name: col.description for col in umf.columns}

        for column in umf.columns:
            derivation = column.derivation
            if not derivation or not derivation.candidates:
                continue
            for cand in derivation.candidates:
                if not cand.column:
                    continue
                up_group, up_table = _split_table_ref(cand.table, unit.group)
                add(
                    up_group,
                    up_table,
                    cand.column,
                    DownstreamRef(
                        group=unit.group,
                        table=unit.table,
                        column=column.name,
                        via="derivation",
                        description=_consumer_desc(
                            column.name, column_descriptions, table_description
                        ),
                    ),
                )

        relationships = umf.relationships
        if relationships and relationships.foreign_keys:
            for fk in relationships.foreign_keys:
                # A qualified references_table (e.g. "hc_2026_ent.member") names
                # the target group in its prefix; otherwise stay in this group.
                if fk.references_pipeline:
                    target_group = fk.references_pipeline
                    target_table = fk.references_table
                elif fk.references_table:
                    target_group, target_table = _split_table_ref(
                        fk.references_table, unit.group
                    )
                else:
                    continue
                if not (target_table and fk.references_column):
                    continue
                add(
                    target_group,
                    target_table,
                    fk.references_column,
                    DownstreamRef(
                        group=unit.group,
                        table=unit.table,
                        column=fk.column,
                        via="fk",
                        description=_consumer_desc(
                            fk.column, column_descriptions, table_description
                        ),
                    ),
                )

    return ReverseLineageIndex(consumers=consumers)
