# SPDX-License-Identifier: MIT OR Apache-2.0
"""Data guidebook: a static catalog + lineage site generated from UMFs.

Point it at any directory of UMFs (split ``table.yaml`` directories,
``*.umf.json`` or ``*.umf.yaml`` artifacts). Every column is traced through
its derivations to the source tables it ultimately reads from; the site shows
each table and column with its sources, derivation, consumers, and rules.

Public API:
    discover_umfs           — flat recursive UMF discovery
    generate                — generate the site to an output dir
    render_standalone_table — one table as a single self-contained page
    build_table_doc         — the JSON payload of one table page
"""

from __future__ import annotations

from tablespec.guidebook.discovery import DiscoveredUmf, discover_umfs
from tablespec.guidebook.generator import generate, render_standalone_table
from tablespec.guidebook.payloads import build_table_doc
from tablespec.guidebook.renderer import render_table_page
from tablespec.guidebook.reverse_lineage import build_reverse_lineage_index

__all__ = [
    "DiscoveredUmf",
    "build_table_doc",
    "build_reverse_lineage_index",
    "render_table_page",
    "discover_umfs",
    "generate",
    "render_standalone_table",
]
