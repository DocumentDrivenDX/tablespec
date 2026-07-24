"""End-to-end guidebook generation from a directory of UMFs.

Discover every UMF under a root, render one self-contained HTML page per table,
build per-group and top-level indexes, and emit a search index. Output nests by
group (parent subfolder) when groups are present, otherwise it is flat.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path

from tablespec.guidebook._styles import CSS
from tablespec.guidebook.discovery import discover_umfs, load_discovered_umf
from tablespec.guidebook.index_renderer import (
    render_group_index,
    render_top_index_flat,
    render_top_index_grouped,
)
from tablespec.guidebook.renderer import render_table_page
from tablespec.guidebook.reverse_lineage import build_reverse_lineage_index
from tablespec.guidebook.search_index import build_search_index

logger = logging.getLogger(__name__)


def generate(
    root: Path,
    output_dir: Path,
    *,
    group: str | None = None,
    provenance_sha: str | None = None,
) -> list[Path]:
    """Generate guidebook HTML pages from the UMFs under ``root``.

    Args:
        root: Directory to discover UMFs in (recursively).
        output_dir: Directory to write HTML into. Created if missing.
        group: If set, only render UMFs in this group. When set, indexes are
            NOT regenerated (single-group mode) so a partial run doesn't rewrite
            the top index with a stale view.
        provenance_sha: Optional git SHA shown in page footers.

    Returns:
        List of paths to all files written (table pages, indexes, search index).

    """
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(UTC)
    discovered = discover_umfs(root)
    # The reverse-lineage index always spans the whole corpus so cross-group
    # links resolve even when rendering a single group.
    reverse_index = build_reverse_lineage_index(root, discovered)

    selected = [d for d in discovered if group is None or d.group == group]
    has_groups = any(d.group for d in discovered)

    if not selected:
        # No table pages would be written; do not emit empty index-only trees.
        return []

    written: list[Path] = []
    # group -> [(table, table_type, description)] for index pages.
    per_group: dict[str, list[tuple[str, str, str | None]]] = {}

    for unit in selected:
        try:
            # Same dispatch discovery used -- split dir / .umf.json / .umf.yaml.
            umf = load_discovered_umf(unit.path)
            html = render_table_page(
                umf,
                reverse_index,
                group=unit.group,
                provenance_sha=provenance_sha,
                generated_at=generated_at,
            )
        except Exception as exc:
            logger.warning("Failed to render %s/%s: %s", unit.group, unit.table, exc)
            continue

        out_dir = output_dir / unit.group if unit.group else output_dir
        out_path = out_dir / f"{unit.table}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        written.append(out_path)
        per_group.setdefault(unit.group, []).append(
            (unit.table, getattr(umf, "table_type", None) or "unknown", umf.description)
        )
        logger.info("Wrote %s", out_path)

    if group is not None:
        # Single-group mode: leave indexes alone.
        return written

    # Per-group indexes (only for non-empty groups).
    for group_name, rows in per_group.items():
        if not group_name:
            continue
        index_html = render_group_index(
            group_name, rows, CSS, provenance_sha=provenance_sha
        )
        index_path = output_dir / group_name / "index.html"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(index_html, encoding="utf-8")
        written.append(index_path)

    # Top-level index: grouped when groups exist, flat otherwise.
    if has_groups:
        group_counts = [(name, len(rows)) for name, rows in per_group.items() if name]
        top_html = render_top_index_grouped(
            group_counts, CSS, provenance_sha=provenance_sha
        )
    else:
        flat_rows = per_group.get("", [])
        top_html = render_top_index_flat(flat_rows, CSS, provenance_sha=provenance_sha)
    top_path = output_dir / "index.html"
    top_path.write_text(top_html, encoding="utf-8")
    written.append(top_path)

    written.append(build_search_index(output_dir, selected))
    return written
