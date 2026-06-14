"""Lightweight prose -> HTML formatter for UMF free-text fields.

Used for ``survivorship.explanation`` and similar multi-paragraph fields
that have implicit structure (labels, numbered lists, bullets, inline SQL
fragments) we want to surface in the guidebook.

Design goals:
- **Conservative**: anything we don't recognize stays as a plain paragraph.
  We never invent structure or apply markdown-like transformations the
  author didn't ask for.
- **Safe by default**: every piece of input text is HTML-escaped before
  any wrapping, so structural detection cannot introduce HTML injection.
- **No external deps**: pure Python, ~200 LOC including docstrings.

Recognized constructs:
    - Blank-line-separated blocks.
    - Numbered lists (``1.``, ``2.``, ...) — emitted as ``<ol>``.
    - Bulleted lists (``-`` or ``*``) — emitted as ``<ul>``.
    - "Label:" leading paragraphs (``Source:``, ``Join key:`` etc.) — the
      label is bolded, the rest stays inline.
    - Indented code blocks (4+ space indent on every line of a block) and
      fenced code blocks (``` ``` ``` ```) — emitted as ``<pre><code>``.
    - Inline SQL idioms inside any paragraph or list item — wrapped in
      inline ``<code>``.

Everything else becomes a plain ``<p>`` with line breaks preserved.
"""

from __future__ import annotations

from html import escape
import re

# Patterns used to recognize structure. Compiled once at import time.

_LABEL_RE = re.compile(r"^([A-Z][A-Za-z0-9 _/-]{1,40}):\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_FENCE_RE = re.compile(r"^```")
_INDENTED_CODE_RE = re.compile(r"^ {4,}\S")
# A line whose only non-whitespace content is `---` (or `***`) — used in UMF
# explanations as a horizontal rule between intro and detail sections.
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,})\s*$")

# Curated structural labels that may appear *inline* (mid-paragraph) inside a
# survivorship explanation. When one of these is found mid-sentence, we split
# the paragraph at that point so the label becomes its own bolded section.
#
# We deliberately keep this list narrow to avoid false positives like
# "Source Priority Rules: ..." (where "Source" looks like a label but isn't).
# Derived from a survey of survivorship.explanation fields across UMF corpora.
_STRUCTURAL_LABELS = frozenset(
    {
        "Approach",
        "Business rule",
        "Business rules",
        "Business rules and fallback",
        "Cardinality",
        "Data quality",
        "Default",
        "Default behavior",
        "Default value",
        "Fallback",
        "Fallback behavior",
        "Filter",
        "Filters",
        "Join key",
        "Logic",
        "Mapping strategy",
        "Note",
        "Policy",
        "Provenance policy",
        "Rationale",
        "Rejected candidates",
        "Rejections",
        "Requirement",
        "Selected source",
        "Source",
        "Sources",
        "Static value",
        "Strategy",
        "Transform",
    }
)

# Pre-compute an inline-split regex that matches one of the known labels when
# it appears after some text (mid-paragraph). The lookbehind requires
# preceding text so the line-start case still flows through _LABEL_RE.
_INLINE_LABEL_RE = re.compile(
    r"(?<=\S)\s+(?=("
    + "|".join(
        re.escape(lbl) for lbl in sorted(_STRUCTURAL_LABELS, key=len, reverse=True)
    )
    + r"):\s)"
)

# Inline SQL detector. Matches well-known multi-word SQL fragments that are
# rarely false-positives in English prose (e.g. "CASE WHEN x IS NULL THEN ...").
# Kept simple on purpose — false negatives are fine, false positives would
# misformat readable English.
_INLINE_SQL_RE = re.compile(
    r"""
    (
        # CASE expressions, possibly multi-keyword
        \bCASE\s+WHEN\b[^.]*?\bEND\b
      | # function-call-with-args, all-caps name, common SQL functions
        \b(?:COALESCE|NULLIF|CONCAT|TRIM|UPPER|LOWER|SUBSTRING|REGEXP_REPLACE
           |REGEXP_EXTRACT|CAST|DATE_FORMAT|TO_DATE|MIN|MAX|LEAST|GREATEST
           |ROW_NUMBER|RANK)\s*\([^)]{0,200}\)
      | # Join / select / where fragments — only when followed by a quoted ident
        \b(?:LEFT\s+JOIN|INNER\s+JOIN|SELECT|WHERE|GROUP\s+BY|ORDER\s+BY)\b[^.]{0,80}?(?=[.\s]|$)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def format_prose(text: str | None) -> str:
    """Render free-text prose as structured HTML.

    Returns an empty string for empty/None input. Output is always wrapped
    in a single ``<div class="prose-block">`` so the renderer can style it.
    """
    if not text or not text.strip():
        return ""

    blocks = _split_blocks(text)
    # Split any prose block whose body contains a curated structural label
    # mid-sentence (Fallback behavior:, Rejected candidates:, etc.). This
    # turns dense single-paragraph "Strategy: ... Rationale: ... Cardinality: ..."
    # blocks into one labeled paragraph per section.
    blocks = [sub for block in blocks for sub in _split_inline_labels(block)]
    rendered = [_render_block(block) for block in blocks]
    return '<div class="prose-block">' + "".join(rendered) + "</div>"


def _split_inline_labels(lines: list[str]) -> list[list[str]]:
    """Split a single block on inline structural labels.

    Code and HR blocks pass through unchanged so we don't mangle them.
    Anything else is joined into a single string, split on the inline-label
    regex, and re-emitted as a list of single-line blocks (each starting
    with a ``Label:`` token that the normal label-paragraph renderer
    handles).
    """
    if not lines:
        return [lines]
    first = lines[0].strip()
    if _FENCE_RE.match(first) or _HR_RE.match(first):
        return [lines]
    if all(_INDENTED_CODE_RE.match(line) for line in lines):
        return [lines]

    joined = " ".join(line.strip() for line in lines if line.strip())
    parts = _INLINE_LABEL_RE.split(joined)
    if len(parts) <= 1:
        # No structural label found mid-sentence; keep block as-is.
        return [lines]

    # ``re.split`` with a single capturing group returns
    #   [text_before, label1, text_between, label2, text_after, ...]
    # Reassemble each label+text pair into its own line, prepending any
    # leading text (before the first inline label) as the first block.
    out: list[list[str]] = []
    leading = parts[0].strip()
    if leading:
        out.append([leading])
    # Pairs: (label, text_following_label)
    for i in range(1, len(parts), 2):
        label = parts[i]
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # Strip the leading "Label: " from body — the regex's lookahead
        # didn't consume it. Then re-attach as a proper Label: line so the
        # normal paragraph renderer picks it up.
        prefix = f"{label}: "
        body = body.removeprefix(prefix)
        out.append([f"{label}: {body}".rstrip()])
    return out


def _split_blocks(text: str) -> list[list[str]]:
    """Split on blank lines, returning a list of line-groups.

    Handles fenced code blocks specially so blank lines inside them don't
    split the fence into two blocks. Horizontal-rule lines (``---``, ``***``)
    are emitted as their own single-line blocks so the renderer can turn
    them into ``<hr>``.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current.append(line)
            continue
        if in_fence:
            current.append(raw_line)
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        if _HR_RE.match(line):
            if current:
                blocks.append(current)
                current = []
            blocks.append([line])
            continue
        current.append(raw_line)
    if current:
        blocks.append(current)
    return blocks


def _render_block(lines: list[str]) -> str:
    """Pick a renderer for one line-group and return its HTML."""
    if not lines:
        return ""

    # Horizontal rule: a single line of `---` or `***`.
    if len(lines) == 1 and _HR_RE.match(lines[0]):
        return "<hr>"

    # Fenced code block: first and last lines are ```
    if _FENCE_RE.match(lines[0].strip()):
        inner = lines[1:]
        if inner and _FENCE_RE.match(inner[-1].strip()):
            inner = inner[:-1]
        code = "\n".join(inner)
        return f"<pre><code>{escape(code)}</code></pre>"

    # Indented code block: every line starts with 4+ spaces.
    if all(_INDENTED_CODE_RE.match(line) for line in lines):
        code = "\n".join(line[4:] for line in lines)
        return f"<pre><code>{escape(code)}</code></pre>"

    # Header-then-list pattern: a line like "Logic applied:" introducing a
    # numbered or bulleted list on the following lines. Emit the header as a
    # paragraph and the list as its own <ol>/<ul>.
    if len(lines) >= 2:
        head = lines[0].rstrip()
        rest = lines[1:]
        is_header = head.endswith(":") and not _LABEL_RE.match(head)
        if is_header and all(_NUMBERED_RE.match(line) for line in rest):
            header_html = f"<p>{_inline_html(head)}</p>"
            items = [_inline_html(_NUMBERED_RE.match(line).group(1)) for line in rest]  # type: ignore[union-attr]
            list_html = "<ol>" + "".join(f"<li>{item}</li>" for item in items) + "</ol>"
            return header_html + list_html
        if is_header and all(_BULLET_RE.match(line) for line in rest):
            header_html = f"<p>{_inline_html(head)}</p>"
            items = [_inline_html(_BULLET_RE.match(line).group(1)) for line in rest]  # type: ignore[union-attr]
            list_html = "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
            return header_html + list_html

    # Numbered list: every line starts with N.  / N) — same prefix.
    if all(_NUMBERED_RE.match(line) for line in lines):
        items = [_inline_html(_NUMBERED_RE.match(line).group(1)) for line in lines]  # type: ignore[union-attr]
        return "<ol>" + "".join(f"<li>{item}</li>" for item in items) + "</ol>"

    # Bulleted list.
    if all(_BULLET_RE.match(line) for line in lines):
        items = [_inline_html(_BULLET_RE.match(line).group(1)) for line in lines]  # type: ignore[union-attr]
        return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"

    # Multi-label run-on: every line in a multi-line block is its own
    # `Label: ...` paragraph (common in survivorship explanations where
    # Strategy:, Selected source:, Rejected candidates:, Business rules:,
    # Cardinality: all sit on consecutive lines without blank separators).
    if len(lines) >= 2:
        label_matches = [_LABEL_RE.match(line) for line in lines]
        if all(label_matches):
            return "".join(
                f"<p><strong>{escape(m.group(1))}:</strong> {_inline_html(m.group(2))}</p>"  # type: ignore[union-attr]
                for m in label_matches
            )

    # Label paragraph: first line is `Label: stuff`. Rest of the block (if any)
    # becomes additional inline content separated by <br>.
    label_match = _LABEL_RE.match(lines[0])
    if label_match:
        label = label_match.group(1)
        rest_text = label_match.group(2)
        body_lines = [rest_text, *lines[1:]]
        body_html = "<br>".join(_inline_html(line) for line in body_lines)
        return f"<p><strong>{escape(label)}:</strong> {body_html}</p>"

    # Default paragraph with line breaks preserved.
    body_html = "<br>".join(_inline_html(line) for line in lines)
    return f"<p>{body_html}</p>"


def _inline_html(line: str) -> str:
    """Escape ``line``, then wrap recognized SQL idioms in inline ``<code>``.

    Escaping happens first so we are guaranteed not to emit attacker-controlled
    HTML. The regex then operates on already-escaped text. We rebuild the
    output by alternating between escaped non-match segments and ``<code>``-
    wrapped escaped matches.
    """
    escaped = escape(line)
    pieces: list[str] = []
    last_end = 0
    for match in _INLINE_SQL_RE.finditer(escaped):
        start, end = match.span()
        if start > last_end:
            pieces.append(escaped[last_end:start])
        pieces.append(f"<code>{escaped[start:end]}</code>")
        last_end = end
    if last_end < len(escaped):
        pieces.append(escaped[last_end:])
    return "".join(pieces)
