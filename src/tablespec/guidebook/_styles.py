"""Shared inline CSS for guidebook pages.

Kept in one place so the table renderer and index renderer produce visually
consistent output. Inline-only by design — every page is self-contained so it
works the same opened from disk or browsed via ``python -m http.server``.
"""

from __future__ import annotations

CSS = """
:root {
  --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --accent: #0b5fff;
  --border: #e3e3e3; --card: #fff; --code-bg: #f4f4f4; --badge-bg: #eef2ff;
}
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
       color: var(--fg); background: var(--bg); }
.container { max-width: 1100px; margin: 0 auto; padding: 24px 32px 80px; }
h1, h2, h3, h4 { line-height: 1.25; }
h1 { font-size: 1.9rem; margin: 0 0 4px; }
h2 { font-size: 1.35rem; margin: 32px 0 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
h3 { font-size: 1.1rem; margin: 20px 0 6px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.muted { color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 16px; }
.chip { background: var(--badge-bg); color: var(--accent); border-radius: 999px;
        padding: 2px 10px; font-size: 0.8rem; }
.chip-warn { background: #fff4e5; color: #b75c00; }
.chip-bronze { background: #f3e7d8; color: #8a5a1a; }
.chip-silver { background: #e6e9ee; color: #495465; }
.chip-gold { background: #fff5d6; color: #8a6a00; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px 20px; margin: 12px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 18px; font-size: 0.92rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
         vertical-align: top; }
th { background: #f7f7f7; font-weight: 600; }
code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
pre { background: var(--code-bg); padding: 12px 14px; border-radius: 6px;
      overflow-x: auto; font-size: 0.85rem; }
details { margin: 6px 0 14px; }
details summary { cursor: pointer; color: var(--accent); font-weight: 500; }
.col-anchor { scroll-margin-top: 12px; padding: 14px 16px; border-left: 3px solid var(--border);
              margin: 18px 0; }
.col-anchor:target { border-left-color: var(--accent); background: #f0f6ff; }
.kv { display: grid; grid-template-columns: 160px 1fr; gap: 4px 16px; margin: 8px 0; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.toc { columns: 2; column-gap: 32px; font-size: 0.92rem; }
.toc a { display: block; padding: 2px 0; }
.footer { margin-top: 60px; padding-top: 16px; border-top: 1px solid var(--border);
          color: var(--muted); font-size: 0.85rem; }
.warn { color: #b75c00; }
.crumbs { font-size: 0.9rem; margin-bottom: 16px; color: var(--muted); }
.crumbs a { color: var(--accent); }
/* Column-overview table: fixed layout so expanding a lineage cell does
   not reflow the other columns. Widths come from the <colgroup> in the
   renderer. */
table.column-overview { table-layout: fixed; }
table.column-overview td { word-wrap: break-word; overflow-wrap: anywhere; }
.lineage-cell { display: flex; flex-direction: column; gap: 2px; max-width: 100%; }
.lineage-side { margin: 0; max-width: 100%; }
.lineage-side summary {
  display: inline;
  list-style: none;
  cursor: pointer;
  color: var(--accent);
  font-weight: 500;
}
.lineage-side summary::marker,
.lineage-side summary::-webkit-details-marker { display: none; }
.lineage-side summary::before { content: "\\25B8\\00A0"; color: var(--muted); }
.lineage-side[open] summary::before { content: "\\25BE\\00A0"; }
.lineage-side .arrow { color: var(--muted); margin-right: 4px; }
.lineage-side ul {
  margin: 6px 0 0 4px;
  padding-left: 18px;
  font-size: 0.85rem;
  max-width: 100%;
}
.lineage-side li { margin: 2px 0; overflow-wrap: anywhere; }
/* Prose blocks produced by `format_prose` (survivorship explanations, etc.) */
.prose-block { margin: 0; }
.prose-block p { margin: 0 0 8px; }
.prose-block p:last-child { margin-bottom: 0; }
.prose-block strong { color: var(--fg); }
.prose-block ol, .prose-block ul { margin: 4px 0 10px; padding-left: 22px; }
.prose-block li { margin: 2px 0; }
.prose-block code { background: var(--code-bg); padding: 1px 4px;
                    border-radius: 3px; font-size: 0.9em; }
.prose-block pre { margin: 6px 0 10px; }
.prose-block hr { border: 0; border-top: 1px solid var(--border);
                  margin: 10px 0; }
/* Per-candidate SQL block: header (priority + source) + reason prose +
   <pre><code>. Used when a column has multiple derivation candidates so
   the reader can tell why two near-identical SQL blocks both appear. */
.candidate-block { margin: 10px 0; padding: 8px 12px;
                   border-left: 3px solid var(--border); background: #fff; }
.candidate-block + .candidate-block { margin-top: 14px; }
.candidate-header { font-size: 0.9rem; margin-bottom: 6px;
                    color: var(--muted); }
.candidate-header .chip { margin-right: 6px; }
.candidate-filter { margin-top: 4px; font-size: 0.88rem; color: var(--muted); }
.candidate-filter code { background: var(--code-bg); padding: 1px 5px;
                         border-radius: 3px; font-size: 0.92em;
                         color: var(--fg); }
.candidate-block .prose-block { margin: 4px 0 0; font-size: 0.92rem; }
.candidate-block pre { margin: 0; }
.candidate-reason { margin-top: 8px; font-size: 0.92rem; }
.candidate-reason > strong { color: var(--muted); margin-right: 4px; }
""".strip()
