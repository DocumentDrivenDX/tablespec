"""End-to-end guidebook generation from a directory of UMFs.

Discover every UMF under a root, trace each table's column lineage to its
source tables, and write a static catalog + lineage site: one page per table,
a page per group, a home page, and shared assets (``assets/site.css``,
``assets/site.js``, and ``assets/catalog.js`` for navigation and search).
Output nests by group (parent subfolder) when groups are present, otherwise it
is flat.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tablespec.guidebook.models import GroupDoc, HomeDoc
from tablespec.guidebook.payloads import (
    build_catalog,
    build_table_doc,
    build_used_by,
    table_summary,
)
from tablespec.guidebook.render import (
    catalog_script,
    render_group_page,
    render_home_page,
    render_table_page,
    write_assets,
)
from tablespec.lineage import DiscoveredUMFProvider, LineageBuilder, table_id

if TYPE_CHECKING:
    from tablespec.lineage import LineageGraph
    from tablespec.models.umf import UMF

TITLE = "Guidebook"


def generate(
    root: Path,
    output_dir: Path,
    *,
    group: str | None = None,
    provenance_sha: str | None = None,
    self_contained: bool = False,
    title: str = TITLE,
) -> list[Path]:
    """Generate the guidebook site from the UMFs under ``root``.

    Args:
        root: Directory to discover UMFs in (recursively).
        output_dir: Directory to write into. Created if missing.
        group: If set, only (re)write this group's table pages. Group and home
            pages are NOT regenerated (single-group mode) so a partial run
            doesn't rewrite them with a stale view. Lineage, search, and "used
            by" links still span the whole corpus.
        provenance_sha: Optional git SHA shown in page footers.
        self_contained: Inline the CSS/JS into every page (no shared assets,
            no cross-page links or search) for embedding single pages.
        title: Site title.

    Returns:
        Paths of all files written.

    """
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    provider = DiscoveredUMFProvider(root)
    groups = provider.list_groups()

    # Discovery already skipped UMFs that fail to load (US-046-AC4).
    builder = LineageBuilder(provider)
    umfs: dict[str, list[UMF]] = {}
    graphs: dict[str, LineageGraph] = {}
    for group_name in groups:
        umfs[group_name] = []
        for name in provider.list_tables(group_name):
            umf = provider.get_umf(group_name, name)
            if umf is None:
                continue
            umfs[group_name].append(umf)
            graphs[table_id(group_name, name)] = builder.trace_table(group_name, name)

    selected = [g for g in groups if group is None or g == group]
    if not any(umfs.get(g) for g in selected):
        # No table pages would be written; do not emit an empty site.
        return []

    used_by = build_used_by(
        list(graphs.values()),
        {table_id(g, u.table_name): u for g, tables in umfs.items() for u in tables},
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    if not self_contained:
        written.extend(write_assets(output_dir))
        _write(
            output_dir / "assets" / "catalog.js",
            catalog_script(build_catalog(title, umfs)),
        )

    page_opts = {"provenance_sha": provenance_sha, "self_contained": self_contained}
    for group_name in selected:
        for umf in umfs[group_name]:
            doc = build_table_doc(
                group_name, umf, graphs[table_id(group_name, umf.table_name)], used_by
            )
            out_dir = output_dir / group_name if group_name else output_dir
            _write(
                out_dir / f"{umf.table_name}.html",
                render_table_page(doc, title=title, **page_opts),
            )

    if group is not None:
        return written

    group_docs = [
        GroupDoc(name=g, tables=[table_summary(u) for u in umfs[g]])
        for g in groups
        if umfs[g]
    ]
    if groups == [""]:
        # Flat corpus: the home page is the (only) group's table list.
        _write(
            output_dir / "index.html",
            render_group_page(group_docs[0], title=title, **page_opts),
        )
        return written

    for doc in group_docs:
        if doc.name:
            _write(
                output_dir / doc.name / "index.html",
                render_group_page(doc, title=title, **page_opts),
            )
    home = HomeDoc(title=title, groups=group_docs)
    _write(output_dir / "index.html", render_home_page(home, **page_opts))
    return written


def render_standalone_table(root: Path, table_ref: str, *, title: str = TITLE) -> str:
    """Render one table (``group.table`` or ``table``) as a single self-contained page."""
    provider = DiscoveredUMFProvider(Path(root))
    parsed_group, _, table = table_ref.rpartition(".")
    umf = provider.get_umf(parsed_group, table)
    if umf is None:
        msg = f"Table not found: {table_ref}"
        raise ValueError(msg)
    graph = LineageBuilder(provider).trace_table(parsed_group, table)
    used_by = build_used_by([graph], {table_id(parsed_group, table): umf})
    doc = build_table_doc(parsed_group, umf, graph, used_by)
    return render_table_page(doc, title=title, self_contained=True)
