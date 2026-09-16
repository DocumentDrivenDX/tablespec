"""Domain map page: the context map rendered from ``domain.yaml`` files.

When the guidebook root contains domain directories (see
:mod:`tablespec.domains`), the generator writes ``domains.html`` next to the
top-level index. The page lists every domain with its owner and exports, the
supplier edges each domain declares (with the DDD integration pattern), and
the cross-domain foreign keys found in the tables themselves. It links into
the existing per-group indexes because a domain directory *is* a guidebook
group.

Direction words are **supplier** and **consumer** on purpose: the guidebook's
lineage view already owns "upstream" and "downstream" for value provenance
(ADR-018), and a context-map edge is a different kind of relationship.
"""

from __future__ import annotations

from html import escape

from tablespec.domains import LoadedDomain
from tablespec.guidebook.index_renderer import _chip, _footer, _page

DOMAIN_MAP_FILENAME = "domains.html"
_TITLE = "Domain Map"


def _domain_rows(domains: dict[str, LoadedDomain]) -> list[str]:
    rows: list[str] = []
    for name in sorted(domains):
        d = domains[name]
        exports = (
            ", ".join(f"<code>{escape(t)}</code>" for t in d.metadata.exports)
            or "<span class='muted'>none</span>"
        )
        owner = (
            escape(d.metadata.owner)
            if d.metadata.owner
            else "<span class='muted'>—</span>"
        )
        desc = (
            escape(d.metadata.description)
            if d.metadata.description
            else "<span class='muted'>—</span>"
        )
        rows.append(
            f"<tr><td><a href='{escape(name)}/index.html'><code>{escape(name)}</code></a></td>"
            f"<td>{owner}</td><td>{len(d.tables)}</td><td>{exports}</td><td>{desc}</td></tr>"
        )
    return rows


def _supplier_rows(domains: dict[str, LoadedDomain]) -> list[str]:
    rows: list[str] = []
    for consumer in sorted(domains):
        for supplier, rel in sorted(domains[consumer].metadata.suppliers.items()):
            consumes = (
                ", ".join(f"<code>{escape(t)}</code>" for t in rel.consumes)
                or "<span class='muted'>—</span>"
            )
            rows.append(
                f"<tr><td><code>{escape(supplier)}</code></td>"
                f"<td><code>{escape(consumer)}</code></td>"
                f"<td>{_chip(rel.pattern.value)}</td><td>{consumes}</td></tr>"
            )
    return rows


def _xref_rows(domains: dict[str, LoadedDomain]) -> list[str]:
    rows: list[str] = []
    for name in sorted(domains):
        d = domains[name]
        for table_key in sorted(d.tables):
            umf = d.tables[table_key]
            if not umf.relationships or not umf.relationships.foreign_keys:
                continue
            for fk in umf.relationships.foreign_keys:
                target_domain = fk.target_domain
                if not target_domain or target_domain == name:
                    continue
                src = f"{name}.{umf.table_name}.{fk.column}"
                dst = f"{target_domain}.{fk.target_table}.{fk.references_column}"
                dst_href = f"{escape(target_domain)}/{escape(fk.target_table)}.html"
                pattern = (
                    _chip(fk.integration.value)
                    if fk.integration
                    else "<span class='muted'>—</span>"
                )
                rows.append(
                    f"<tr><td><code>{escape(src)}</code></td>"
                    f"<td><a href='{dst_href}'><code>{escape(dst)}</code></a></td>"
                    f"<td>{pattern}</td></tr>"
                )
    return rows


def render_domain_map(
    domains: dict[str, LoadedDomain],
    css: str,
    *,
    provenance_sha: str | None = None,
) -> str:
    """Render the domain map page."""
    n_tables = sum(len(d.tables) for d in domains.values())
    supplier_rows = _supplier_rows(domains)
    xref_rows = _xref_rows(domains)
    body: list[str] = [
        '<nav class="crumbs"><a href="index.html">All tables</a> · Domain map</nav>',
        f"<h1>{_TITLE}</h1>",
        '<div class="chips">'
        f"{_chip(f'{len(domains)} domains')}"
        f"{_chip(f'{n_tables} tables')}"
        f"{_chip(f'{len(supplier_rows)} supplier edges')}"
        "</div>",
        "<h2>Domains</h2>",
        "<table><thead><tr><th>Domain</th><th>Owner</th><th>Tables</th>"
        "<th>Exports</th><th>Description</th></tr></thead><tbody>",
        *_domain_rows(domains),
        "</tbody></table>",
        "<h2>Supplier edges</h2>",
        "<p class='muted'>Declared in each consumer's <code>domain.yaml</code>. "
        "Direction is supplier to consumer.</p>",
        "<table><thead><tr><th>Supplier</th><th>Consumer</th><th>Pattern</th>"
        "<th>Consumes</th></tr></thead><tbody>",
        *(
            supplier_rows
            or ["<tr><td colspan='4' class='muted'>none declared</td></tr>"]
        ),
        "</tbody></table>",
        "<h2>Cross-domain references</h2>",
        "<p class='muted'>Foreign keys whose target lives in another domain.</p>",
        "<table><thead><tr><th>From</th><th>To</th><th>Integration</th></tr></thead><tbody>",
        *(xref_rows or ["<tr><td colspan='3' class='muted'>none</td></tr>"]),
        "</tbody></table>",
    ]
    return _page(_TITLE, "".join(body), _footer(provenance_sha), css)


__all__ = ["DOMAIN_MAP_FILENAME", "render_domain_map"]
