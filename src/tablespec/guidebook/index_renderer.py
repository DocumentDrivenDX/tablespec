"""Top-level and per-group index pages.

When the discovery root has subfolders, output nests as ``<group>/<table>.html``
and the top index lists groups (each linking to a per-group index). When every
UMF sits at the root, output is flat and a single top index lists every table
directly.
"""

from __future__ import annotations

from html import escape

_PAGE_TITLE = "Data Guidebook"


def _chip(text: str, kind: str = "") -> str:
    cls = "chip " + kind if kind else "chip"
    return f'<span class="{cls}">{escape(text)}</span>'


def _table_type_chip(table_type: str) -> str:
    """Map UMF ``table_type`` to a colored stage chip."""
    mapping = {
        "generated": "chip-gold",
        "ingested": "chip-silver",
        "raw": "chip-bronze",
        "lookup": "chip-silver",
    }
    return _chip(table_type or "unknown", mapping.get(table_type, ""))


def _page(title: str, body: str, footer: str, css: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
{body}
{footer}
</div>
</body>
</html>
"""


def _footer(provenance_sha: str | None) -> str:
    if provenance_sha:
        return f'<div class="footer">Commit <code>{escape(provenance_sha)}</code></div>'
    return ""


def _table_rows(
    tables: list[tuple[str, str, str | None]], *, href_prefix: str = ""
) -> list[str]:
    """Build ``<tr>`` rows for a list of ``(table, table_type, description)``."""
    rows: list[str] = []
    for table_name, table_type, description in sorted(tables):
        desc_html = (
            escape(description) if description else "<span class='muted'>—</span>"
        )
        href = f"{href_prefix}{table_name}.html"
        rows.append(
            f"<tr><td><a href='{escape(href)}'><code>{escape(table_name)}</code></a></td>"
            f"<td>{_table_type_chip(table_type)}</td>"
            f"<td>{desc_html}</td></tr>"
        )
    return rows


def render_group_index(
    group: str,
    tables: list[tuple[str, str, str | None]],
    css: str,
    *,
    provenance_sha: str | None = None,
) -> str:
    """Render the per-group index page (lives at ``<group>/index.html``)."""
    title = f"{group} — group index"
    body_parts: list[str] = [
        f'<nav class="crumbs"><a href="../index.html">All tables</a> · {escape(group)}</nav>',
        f"<h1>{escape(group)}</h1>",
        f'<div class="chips">{_chip(group)}{_chip(f"{len(tables)} tables")}</div>',
        "<h2>Tables</h2>",
        "<table><thead><tr><th>Table</th><th>Type</th><th>Description</th></tr></thead><tbody>",
        *_table_rows(tables),
        "</tbody></table>",
    ]
    return _page(title, "".join(body_parts), _footer(provenance_sha), css)


def render_top_index_grouped(
    groups: list[tuple[str, int]],
    css: str,
    *,
    provenance_sha: str | None = None,
) -> str:
    """Render the top-level index listing groups with table counts."""
    rows: list[str] = []
    for group_name, table_count in sorted(groups):
        rows.append(
            f"<tr><td><a href='{escape(group_name)}/index.html'>"
            f"<code>{escape(group_name)}</code></a></td>"
            f"<td>{table_count}</td></tr>"
        )
    total_tables = sum(c for _, c in groups)
    body_parts: list[str] = [
        f"<h1>{_PAGE_TITLE}</h1>",
        '<div class="chips">'
        f"{_chip(f'{len(groups)} groups')}"
        f"{_chip(f'{total_tables} tables')}"
        "</div>",
        "<h2>Groups</h2>",
        "<table><thead><tr><th>Group</th><th>Tables</th></tr></thead><tbody>",
        *rows,
        "</tbody></table>",
    ]
    return _page(_PAGE_TITLE, "".join(body_parts), _footer(provenance_sha), css)


def render_top_index_flat(
    tables: list[tuple[str, str, str | None]],
    css: str,
    *,
    provenance_sha: str | None = None,
) -> str:
    """Render a flat top-level index listing every table directly."""
    body_parts: list[str] = [
        f"<h1>{_PAGE_TITLE}</h1>",
        f'<div class="chips">{_chip(f"{len(tables)} tables")}</div>',
        "<h2>Tables</h2>",
        "<table><thead><tr><th>Table</th><th>Type</th><th>Description</th></tr></thead><tbody>",
        *_table_rows(tables),
        "</tbody></table>",
    ]
    return _page(_PAGE_TITLE, "".join(body_parts), _footer(provenance_sha), css)
