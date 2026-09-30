"""HTML shells for guidebook pages.

Each page is a small shell: shared ``assets/site.css`` + ``assets/site.js``,
the shared ``assets/catalog.js`` (navigation + search), and the page's own
payload inlined as JSON. Everything loads via relative ``<link>``/``<script
src>`` -- no frameworks, no network requests -- so the site works from
``file://``, any static host, or an app's static mount. ``self_contained=True``
inlines the assets instead (for embedding a single page, e.g. a srcdoc iframe).
"""

from __future__ import annotations

from html import escape
from importlib import resources
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

    from tablespec.guidebook.models import GroupDoc, HomeDoc, TableDoc

ASSET_NAMES = ("site.css", "site.js")


def asset_text(name: str) -> str:
    """Return the text of a packaged asset."""
    return (
        resources.files("tablespec.guidebook")
        .joinpath("assets", name)
        .read_text(encoding="utf-8")
    )


def write_assets(output_dir: Path) -> list[Path]:
    """Copy the shared assets into ``output_dir/assets``."""
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in ASSET_NAMES:
        path = assets_dir / name
        path.write_text(asset_text(name), encoding="utf-8")
        written.append(path)
    return written


def group_depth(group: str) -> int:
    """Directory depth of a group's pages below the output root."""
    return group.count("/") + 1 if group else 0


def _script_safe(text: str) -> str:
    """Make text safe to embed inside a ``<script>`` element."""
    return text.replace("</", "<\\/")


def catalog_script(catalog: dict[str, Any]) -> str:
    """Return ``assets/catalog.js`` content."""
    return f"window.CATALOG = {json.dumps(catalog, separators=(',', ':'))};\n"


def _page(
    *,
    page_title: str,
    kind: str,
    depth: int,
    doc: BaseModel,
    site_title: str,
    provenance_sha: str | None,
    self_contained: bool,
) -> str:
    root = "../" * depth
    data = {
        "kind": kind,
        "root": root,
        "title": site_title,
        "provenance_sha": provenance_sha,
        "standalone": self_contained,
        "doc": doc.model_dump(mode="json", exclude_none=True),
    }
    payload = _script_safe(json.dumps(data, separators=(",", ":")))
    if self_contained:
        head_assets = f"<style>{asset_text('site.css')}</style>"
        body_assets = f"<script>{_script_safe(asset_text('site.js'))}</script>"
    else:
        head_assets = f'<link rel="stylesheet" href="{root}assets/site.css">'
        body_assets = (
            f'<script src="{root}assets/catalog.js"></script>\n'
            f'<script src="{root}assets/site.js"></script>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(page_title)}</title>
{head_assets}
</head>
<body>
<div id="app"><noscript>This page needs JavaScript enabled.</noscript></div>
<script type="application/json" id="page-data">{payload}</script>
{body_assets}
</body>
</html>
"""


def render_home_page(
    doc: HomeDoc, *, provenance_sha: str | None = None, self_contained: bool = False
) -> str:
    """Render ``index.html`` for a grouped corpus."""
    return _page(
        page_title=doc.title,
        kind="home",
        depth=0,
        doc=doc,
        site_title=doc.title,
        provenance_sha=provenance_sha,
        self_contained=self_contained,
    )


def render_group_page(
    doc: GroupDoc,
    *,
    title: str,
    provenance_sha: str | None = None,
    self_contained: bool = False,
) -> str:
    """Render ``<group>/index.html`` (or the root ``index.html`` of a flat corpus)."""
    return _page(
        page_title=f"{doc.name} · {title}" if doc.name else title,
        kind="group",
        depth=group_depth(doc.name),
        doc=doc,
        site_title=title,
        provenance_sha=provenance_sha,
        self_contained=self_contained,
    )


def render_table_page(
    doc: TableDoc,
    *,
    title: str,
    provenance_sha: str | None = None,
    self_contained: bool = False,
) -> str:
    """Render ``<group>/<table>.html``."""
    return _page(
        page_title=f"{doc.id} · {title}",
        kind="table",
        depth=group_depth(doc.group),
        doc=doc,
        site_title=title,
        provenance_sha=provenance_sha,
        self_contained=self_contained,
    )
