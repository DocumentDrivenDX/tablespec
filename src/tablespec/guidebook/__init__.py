"""Data guidebook generation.

Renders UMF metadata into a navigable, self-contained HTML site — one page per
table plus group/top indexes and a search index. Point it at any directory of
UMFs (split ``table.yaml`` directories or ``*.umf.json`` artifacts).

Public API:
    discover_umfs               — flat recursive UMF discovery
    build_reverse_lineage_index — single-pass forward-lineage builder
    render_table_page           — render one UMF to standalone HTML
    generate                    — generate a full guidebook to an output dir
"""

from __future__ import annotations

from tablespec.guidebook.discovery import DiscoveredUmf, discover_umfs
from tablespec.guidebook.generator import generate
from tablespec.guidebook.renderer import render_table_page
from tablespec.guidebook.reverse_lineage import (
    ReverseLineageIndex,
    build_reverse_lineage_index,
)

__all__ = [
    "DiscoveredUmf",
    "ReverseLineageIndex",
    "build_reverse_lineage_index",
    "discover_umfs",
    "generate",
    "render_table_page",
]
