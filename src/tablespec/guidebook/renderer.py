"""Render one UMF plus reverse-lineage data into a single HTML page.

The output is intentionally self-contained: inline CSS, no JS frameworks, no
network requests. Pages cross-link by relative URL so the same artifact works
opened locally in a browser or browsed via ``python -m http.server``.

Page layout:
    Business view (default, top)         — purpose, downstream consumers, columns
    Engineering view (collapsible)       — derivations, SQL, validations

Rendering reads directly from the ``UMF``/``UMFColumn`` Pydantic models; a thin
``_ColumnView`` adapter exposes exactly the fields the HTML builders need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING, Any

from tablespec.guidebook._styles import CSS as _CSS
from tablespec.guidebook.prose import format_prose
from tablespec.guidebook.reverse_lineage import _split_table_ref
from tablespec.guidebook.sql_format import format_sql

if TYPE_CHECKING:
    from tablespec.guidebook.reverse_lineage import DownstreamRef, ReverseLineageIndex
    from tablespec.models.umf import UMF, UMFColumn


@dataclass(frozen=True)
class _CandidateView:
    """A derivation candidate flattened into (group, table, column, ...)."""

    group: str | None
    table: str
    column: str | None
    expression: str | None
    priority: int
    reason: str | None
    join_filter: str | None


@dataclass(frozen=True)
class _RuleView:
    """A per-column validation rule for display."""

    rule_type: str
    description: str
    severity: str | None


@dataclass(frozen=True)
class _ColumnView:
    """The renderer's view of one column — populated from a ``UMFColumn``."""

    column_name: str
    data_type: str
    description: str | None
    format: str | None
    length: int | None
    provenance_policy: str | None
    survivorship_explanation: str | None
    sample_values: list[str] | None
    candidates: list[_CandidateView] = field(default_factory=list)
    validation_rules: list[_RuleView] = field(default_factory=list)


def _extract_validation_rules(
    column_name: str, expectations: list[dict[str, Any]] | None
) -> list[_RuleView]:
    """Pull GX-style expectations that target ``column_name`` into _RuleView.

    Ported from pulseflow's lineage helper: filters the table-wide expectation
    list to the ones whose ``kwargs.column`` matches, reading the human-readable
    description/severity from each expectation's ``meta``.
    """
    rules: list[_RuleView] = []
    if not expectations:
        return rules
    for validation in expectations:
        kwargs = validation.get("kwargs", {}) or {}
        if kwargs.get("column", "") != column_name:
            continue
        rule_type = validation.get("type", "")
        meta = validation.get("meta", {}) or {}
        rules.append(
            _RuleView(
                rule_type=rule_type,
                description=meta.get("description", f"Rule: {rule_type}"),
                severity=meta.get("severity", "warning"),
            )
        )
    return rules


def _column_view(
    col: UMFColumn,
    expectations: list[dict[str, Any]] | None,
    *,
    current_group: str,
) -> _ColumnView:
    """Build a ``_ColumnView`` from a ``UMFColumn``."""
    candidates: list[_CandidateView] = []
    survivorship_explanation: str | None = None
    if col.derivation:
        if col.derivation.survivorship:
            survivorship_explanation = col.derivation.survivorship.explanation
        for cand in col.derivation.candidates or []:
            cand_group, cand_table = _split_table_ref(cand.table, current_group)
            candidates.append(
                _CandidateView(
                    # Preserve "same group as me" as None so links can fall back
                    # to the current group, matching the original behavior.
                    group=None if cand_group == current_group else cand_group,
                    table=cand_table,
                    column=cand.column,
                    expression=cand.expression,
                    priority=cand.priority,
                    reason=cand.reason,
                    join_filter=cand.join_filter,
                )
            )

    return _ColumnView(
        column_name=col.name,
        data_type=col.data_type,
        description=col.description,
        format=col.format,
        length=col.length,
        provenance_policy=col.provenance_policy,
        survivorship_explanation=survivorship_explanation,
        sample_values=col.sample_values,
        candidates=candidates,
        validation_rules=_extract_validation_rules(col.name, expectations),
    )


def _chip(text: str, kind: str = "") -> str:
    cls = "chip " + kind if kind else "chip"
    return f'<span class="{cls}">{escape(text)}</span>'


def _column_anchor(column_name: str) -> str:
    return f"col-{column_name}"


def _render_lineage_cell(
    col: _ColumnView,
    consumers: list[DownstreamRef],
    *,
    current_group: str,
    base_url: str,
) -> str:
    """Build the combined upstream + downstream cell for the column-overview table.

    Renders a compact dual counter on collapse (``↑ N upstream  ↓ M downstream``)
    where each counter is its own ``<details>`` so the user can expand either
    direction independently. Returns ``"—"`` when the column has no lineage
    in either direction.
    """
    # Upstream: derivation candidates with a named source column. Skip the
    # rare pure-expression candidates (no column) — they have no anchor to
    # link to.
    upstream = [c for c in col.candidates if c.column]
    has_upstream = bool(upstream)
    has_downstream = bool(consumers)

    if not has_upstream and not has_downstream:
        return "—"

    pieces: list[str] = []
    if has_upstream:
        items = "".join(
            f"<li>{_upstream_link(u.group, u.table, u.column, current_group=current_group, base_url=base_url, title=u.reason)}</li>"
            for u in upstream
        )
        pieces.append(
            f"<details class='lineage-side'>"
            f"<summary><span class='arrow'>↑</span> {len(upstream)} upstream</summary>"
            f"<ul>{items}</ul>"
            f"</details>"
        )
    if has_downstream:
        items = "".join(f"<li>{_column_link(c, base_url)}</li>" for c in consumers)
        pieces.append(
            f"<details class='lineage-side'>"
            f"<summary><span class='arrow'>↓</span> {len(consumers)} downstream</summary>"
            f"<ul>{items}</ul>"
            f"</details>"
        )
    return f"<div class='lineage-cell'>{''.join(pieces)}</div>"


def _dedup_consumers(consumers: list[DownstreamRef]) -> list[DownstreamRef]:
    """Collapse multiple references to the same downstream column.

    A column can appear twice when it is both a derivation source and an FK
    target. Prefer the 'derivation' record because it carries the stronger
    semantic link; fall back to 'fk' only if that's all we have.
    """
    best: dict[tuple[str, str, str], DownstreamRef] = {}
    for c in consumers:
        key = (c.group, c.table, c.column)
        existing = best.get(key)
        if existing is None or (existing.via == "fk" and c.via == "derivation"):
            best[key] = c
    return list(best.values())


def _column_link(
    consumer: DownstreamRef,
    base_url: str = "..",
) -> str:
    """Render a downstream consumer as a clickable link to its column anchor.

    Cross-page links use relative paths: ``../{group}/{table}.html#col-{column}``.
    A flat (empty-group) consumer links to ``../{table}.html``. Hover shows the
    consumer column's UMF description so readers can see what the consumer is
    without clicking.
    """
    seg = f"{consumer.group}/" if consumer.group else ""
    href = f"{base_url}/{seg}{consumer.table}.html#{_column_anchor(consumer.column)}"
    label_parts = [p for p in (consumer.group, consumer.table, consumer.column) if p]
    label = ".".join(label_parts)
    title_attr = (
        f' title="{escape(consumer.description)}"' if consumer.description else ""
    )
    suffix = (
        ""
        if consumer.via == "derivation"
        else f" <span class='muted'>(via {consumer.via})</span>"
    )
    return f'<a href="{escape(href)}"{title_attr}>{escape(label)}</a>{suffix}'


def _upstream_link(
    group: str | None,
    table: str,
    column: str | None,
    *,
    current_group: str,
    base_url: str = "..",
    title: str | None = None,
) -> str:
    """Render an upstream source as a clickable link.

    ``title`` is rendered as the link's ``title`` attribute, surfacing the
    derivation reason on hover.
    """
    eff_group = group if group is not None else current_group
    label_parts = [p for p in (eff_group, table) if p]
    if column:
        label_parts.append(column)
    label = ".".join(label_parts)
    seg = f"{eff_group}/" if eff_group else ""
    href = f"{base_url}/{seg}{table}.html"
    if column:
        href += f"#{_column_anchor(column)}"
    title_attr = f' title="{escape(title.strip())}"' if title else ""
    return f'<a href="{escape(href)}"{title_attr}>{escape(label)}</a>'


def _render_business_view(
    umf: UMF,
    columns: list[_ColumnView],
    reverse_index: ReverseLineageIndex,
    *,
    group: str,
    base_url: str,
) -> str:
    parts: list[str] = ['<section class="business-view">']
    parts.append("<h2>Overview</h2>")
    parts.append('<div class="card">')
    if umf.description:
        parts.append(f"<p>{escape(umf.description)}</p>")
    else:
        parts.append(
            "<p class='warn'>No table description set. Add a <code>description</code> field to the UMF.</p>"
        )

    source_file = getattr(umf, "source_file", None)
    primary_key = getattr(umf, "primary_key", None) or []
    parts.append('<dl class="kv">')
    if source_file:
        parts.append(f"<dt>Source file</dt><dd>{escape(str(source_file))}</dd>")
    if primary_key:
        pk_str = ", ".join(escape(p) for p in primary_key)
        parts.append(f"<dt>Primary key</dt><dd><code>{pk_str}</code></dd>")
    parts.append(f"<dt>Total columns</dt><dd>{len(columns)}</dd>")
    parts.append("</dl>")
    parts.append("</div>")

    parts.append("<h2>Columns</h2>")
    # table-layout: fixed (set via .column-overview in CSS) requires explicit
    # column widths from <colgroup> so expanding a row doesn't reflow the table.
    parts.append('<table class="column-overview">')
    parts.append(
        "<colgroup>"
        '<col style="width: 20%">'
        '<col style="width: 14%">'
        '<col style="width: 32%">'
        '<col style="width: 34%">'
        "</colgroup>"
    )
    parts.append(
        "<thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Lineage</th></tr></thead><tbody>"
    )
    for col in columns:
        anchor = _column_anchor(col.column_name)
        consumers = _dedup_consumers(
            reverse_index.lookup(group, umf.table_name, col.column_name)
        )
        lineage_html = _render_lineage_cell(
            col, consumers, current_group=group, base_url=base_url
        )
        desc = (
            escape(col.description)
            if col.description
            else "<span class='muted'>(no description)</span>"
        )
        parts.append(
            f"<tr><td><a href='#{anchor}'><code>{escape(col.column_name)}</code></a></td>"
            f"<td><code>{escape(col.data_type)}</code></td>"
            f"<td>{desc}</td>"
            f"<td>{lineage_html}</td></tr>"
        )
    parts.append("</tbody></table>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_column_section(
    col: _ColumnView,
    umf: UMF,
    reverse_index: ReverseLineageIndex,
    *,
    group: str,
    base_url: str,
) -> str:
    parts: list[str] = []
    anchor = _column_anchor(col.column_name)
    parts.append(f'<div class="col-anchor" id="{anchor}">')
    parts.append(f"<h3><code>{escape(col.column_name)}</code></h3>")

    chips: list[str] = [_chip(col.data_type)]
    if col.format:
        chips.append(_chip(f"format: {col.format}"))
    if col.length:
        chips.append(_chip(f"len ≤ {col.length}"))
    if col.provenance_policy:
        chips.append(_chip(col.provenance_policy))
    parts.append(f'<div class="chips">{"".join(chips)}</div>')

    if col.description:
        parts.append(f"<p>{escape(col.description)}</p>")

    consumers = _dedup_consumers(
        reverse_index.lookup(group, umf.table_name, col.column_name)
    )
    if consumers:
        parts.append("<h4>Downstream consumers</h4><ul>")
        for c in consumers:
            parts.append(f"<li>{_column_link(c, base_url)}</li>")
        parts.append("</ul>")

    if col.candidates:
        # Unified derivation-rule display: one block per candidate covering the
        # WHOLE rule (priority, source, join filter, SQL expression, reason).
        # Iterates ALL candidates ordered by priority — not just the ones with
        # an `expression` — so column-reference candidates with a join filter
        # (e.g. "providers.NAME WHERE specialty = ...") show their rule too.
        candidates = sorted(col.candidates, key=lambda c: c.priority)
        label = "Derivation rule" if len(candidates) == 1 else "Derivation rules"
        parts.append(f"<details open><summary>{label}</summary>")
        for cand in candidates:
            parts.append('<div class="candidate-block">')

            src_link = _upstream_link(
                cand.group,
                cand.table,
                cand.column,
                current_group=group,
                base_url=base_url,
            )
            header_lines = [
                f'<span class="chip">Priority {cand.priority}</span> Source: {src_link}'
            ]
            # join_filter is the WHERE-style scope that disambiguates candidates
            # sharing a source (or otherwise narrows the rule). Always surface it.
            if cand.join_filter:
                header_lines.append(
                    f'<div class="candidate-filter">Filter: '
                    f"<code>{escape(format_sql(cand.join_filter))}</code></div>"
                )
            parts.append(
                '<div class="candidate-header">' + "".join(header_lines) + "</div>"
            )

            # SQL expression only when the candidate carries one (column-only
            # candidates have no expression — their rule is source + filter).
            if cand.expression:
                parts.append(
                    f"<pre><code>{escape(format_sql(cand.expression))}</code></pre>"
                )

            if cand.reason:
                parts.append('<div class="candidate-reason">')
                parts.append("<strong>Why:</strong>")
                parts.append(format_prose(cand.reason))
                parts.append("</div>")
            parts.append("</div>")
        parts.append("</details>")

    if col.survivorship_explanation:
        parts.append("<details><summary>Survivorship logic</summary>")
        parts.append(format_prose(col.survivorship_explanation))
        parts.append("</details>")

    if col.validation_rules:
        parts.append("<details><summary>Validation rules</summary>")
        parts.append(
            "<table><thead><tr><th>Rule</th><th>Severity</th><th>Description</th></tr></thead><tbody>"
        )
        for rule in col.validation_rules:
            sev = rule.severity or "warning"
            parts.append(
                f"<tr><td><code>{escape(rule.rule_type)}</code></td>"
                f"<td>{escape(sev)}</td>"
                f"<td>{escape(rule.description)}</td></tr>"
            )
        parts.append("</tbody></table></details>")

    if col.sample_values:
        sample_str = ", ".join(
            f"<code>{escape(str(v))}</code>" for v in col.sample_values
        )
        parts.append(f"<p class='muted'>Examples: {sample_str}</p>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_engineering_view(
    umf: UMF,
    columns: list[_ColumnView],
    reverse_index: ReverseLineageIndex,
    *,
    group: str,
    base_url: str,
) -> str:
    parts: list[str] = ['<section class="engineering-view">']
    parts.append("<h2>Engineering detail</h2>")
    parts.append(
        "<p class='muted'>Per-column derivations, validations, downstream links. Click any column above to jump.</p>"
    )
    for col in columns:
        parts.append(
            _render_column_section(
                col, umf, reverse_index, group=group, base_url=base_url
            )
        )
    parts.append("</section>")
    return "\n".join(parts)


def render_table_page(
    umf: UMF,
    reverse_index: ReverseLineageIndex,
    *,
    group: str = "",
    provenance_sha: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Render one full table page as a standalone HTML document.

    Args:
        umf: The loaded UMF.
        reverse_index: Pre-built forward-lineage index covering all UMFs.
        group: The UMF's group (parent subfolder, ``""`` if flat). Used for
            lineage lookups and to build the breadcrumb.
        provenance_sha: Optional git SHA to show in the footer.
        generated_at: Timestamp for the footer (defaults to now, UTC).

    """
    generated_at = generated_at or datetime.now(UTC)
    table_type = getattr(umf, "table_type", None) or "unknown"
    expectations = umf.validation_rules.expectations if umf.validation_rules else None
    columns = [
        _column_view(col, expectations, current_group=group) for col in umf.columns
    ]

    title = f"{group} / {umf.table_name}" if group else umf.table_name

    if group:
        crumbs = (
            f'<nav class="crumbs"><a href="../index.html">All tables</a> · '
            f'<a href="index.html">{escape(group)}</a> · {escape(umf.table_name)}</nav>'
        )
    else:
        crumbs = (
            f'<nav class="crumbs"><a href="index.html">All tables</a> · '
            f"{escape(umf.table_name)}</nav>"
        )

    header_chips = _chip(umf.table_name) + _chip(table_type)
    if group:
        header_chips = _chip(group) + header_chips
    header = [
        crumbs,
        f"<h1>{escape(title)}</h1>",
        f'<div class="chips">{header_chips}</div>',
    ]

    # Pages in a group live one level below the output root (../ to reach
    # other groups); flat pages live at the root (./).
    base_url = ".." if group else "."
    business = _render_business_view(
        umf, columns, reverse_index, group=group, base_url=base_url
    )
    engineering = _render_engineering_view(
        umf, columns, reverse_index, group=group, base_url=base_url
    )

    footer_lines = [f"Generated {generated_at.isoformat(timespec='seconds')}"]
    if provenance_sha:
        footer_lines.append(f"Commit <code>{escape(provenance_sha)}</code>")
    footer = '<div class="footer">' + " · ".join(footer_lines) + "</div>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
{"".join(header)}
{business}
{engineering}
{footer}
</div>
</body>
</html>
"""
